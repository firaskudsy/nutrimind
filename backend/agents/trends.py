"""`/trends` chart generation — weight, calories, and sleep over 1w / 1m.

Pulls data live from the MCP servers and renders a single composite PNG for the
Telegram bot (3 rows: weight / calories / sleep × 2 columns: week / month).

Data sourcing (see the probe notes in the /trends design):
  - Weight  — Cronometer `get_weight_history` returns the whole range in ONE call.
  - Sleep   — Google Health `list_data_points(sleep, ...)` returns every night's
              session in the range in one paged call; we sum the asleep stages
              per night.
  - Calories— Cronometer only exposes per-day nutrition, so we fetch it daily for
              the last month (~30 throttled calls).

Everything degrades gracefully: a failed/empty source renders "no data" cells
rather than raising, so a partial outage still yields a useful chart.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
from collections import defaultdict
from datetime import date, datetime, timedelta

import matplotlib

matplotlib.use("Agg")  # headless: render to PNG bytes, no display

import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

from agents import memory  # noqa: E402
from mcp_clients import registry  # noqa: E402

logger = logging.getLogger(__name__)

WINDOWS: list[tuple[str, int]] = [
    ("Last week", 7),
    ("Last month", 30),
]
_MAX_WINDOW_DAYS = 30
_CALORIE_CONCURRENCY = 4  # gentle on the unofficial Cronometer API
_ASLEEP_STAGES = {"LIGHT", "DEEP", "REM"}

_WEIGHT_COLOR = "#2e6fdb"
_CALORIE_COLOR = "#e8843c"
_SLEEP_COLOR = "#8e5bd0"
_TARGET_COLOR = "#c0392b"


# ------------------------------------------------------------------
# MCP plumbing
# ------------------------------------------------------------------


def _ref(name: str):
    return next((r for r in registry.server_refs() if r.name == name), None)


def _unwrap(res) -> dict | list | None:
    """Normalize an MCP tool result into parsed JSON.

    `call_tool` returns either structuredContent (a dict) or a list of text
    parts. Our FastMCP Cronometer tools wrap their payload as
    ``{"result": "<json string>"}``; Google Health returns structured JSON
    directly.
    """
    if isinstance(res, list):
        res = res[0] if res else None
    if isinstance(res, str):
        try:
            res = json.loads(res)
        except json.JSONDecodeError:
            return None
    if (
        isinstance(res, dict)
        and list(res.keys()) == ["result"]
        and isinstance(res["result"], str)
    ):
        try:
            res = json.loads(res["result"])
        except json.JSONDecodeError:
            return None
    return res


# ------------------------------------------------------------------
# Fetchers  ({date -> value} maps)
# ------------------------------------------------------------------


async def _fetch_weight(unit: str, start: date, end: date) -> dict[date, float]:
    ref = _ref("cronometer")
    if ref is None:
        return {}
    try:
        raw = _unwrap(
            await registry.call_tool(
                ref,
                "get_weight_history",
                {"unit": unit, "start_date": start.isoformat(), "end_date": end.isoformat()},
            )
        )
    except Exception as exc:  # noqa: BLE001 - a source outage must not break the chart
        logger.warning("trends: weight fetch failed: %s", exc)
        return {}
    if not isinstance(raw, dict):
        return {}
    hist = raw.get("history")
    data = hist.get("data") if isinstance(hist, dict) else hist
    out: dict[date, float] = {}
    for pt in data or []:
        try:
            out[date.fromisoformat(pt["day"])] = float(pt["value"])
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _offset_seconds(raw: str | None) -> int:
    try:
        return int(str(raw or "0s").rstrip("s"))
    except ValueError:
        return 0


def _sleep_point(dp: dict) -> tuple[date | None, float]:
    """Return (local wake date, asleep hours) for one sleep dataPoint."""
    sleep = dp.get("sleep") or {}
    interval = sleep.get("interval") or {}
    start, end = interval.get("startTime"), interval.get("endTime")
    if not start or not end:
        return None, 0.0
    try:
        t0, t1 = _parse_iso(start), _parse_iso(end)
    except ValueError:
        return None, 0.0
    secs = 0.0
    for stage in sleep.get("stages") or []:
        if stage.get("type") in _ASLEEP_STAGES:
            try:
                secs += (_parse_iso(stage["endTime"]) - _parse_iso(stage["startTime"])).total_seconds()
            except (KeyError, ValueError):
                continue
    if secs <= 0:  # no stage detail — fall back to time in bed
        secs = (t1 - t0).total_seconds()
    # Attribute the night to the local wake-up date (Fitbit's convention).
    off = _offset_seconds(interval.get("endUtcOffset") or interval.get("startUtcOffset"))
    return (t1 + timedelta(seconds=off)).date(), secs / 3600.0


async def _fetch_sleep(start: date, end: date) -> dict[date, float]:
    ref = _ref("google_health")
    if ref is None:
        return {}
    hours: dict[date, float] = defaultdict(float)
    page_token: str | None = None
    try:
        for _ in range(8):  # page cap — plenty for 90 nights
            args = {
                "data_type": "sleep",
                "start_time": f"{start.isoformat()}T00:00:00Z",
                "end_time": f"{(end + timedelta(days=1)).isoformat()}T00:00:00Z",
                "page_size": 100,
            }
            if page_token:
                args["page_token"] = page_token
            raw = _unwrap(await registry.call_tool(ref, "google_health_list_data_points", args))
            if not isinstance(raw, dict):
                break
            data = raw.get("data") or {}
            for dp in data.get("dataPoints") or []:
                night, hrs = _sleep_point(dp)
                if night is not None:
                    hours[night] += hrs
            page_token = data.get("nextPageToken")
            if not page_token:
                break
    except Exception as exc:  # noqa: BLE001
        logger.warning("trends: sleep fetch failed: %s", exc)
    return dict(hours)


async def _fetch_calories(today: date) -> dict[date, float]:
    ref = _ref("cronometer")
    if ref is None:
        return {}
    dates = [today - timedelta(days=i) for i in range(_MAX_WINDOW_DAYS)]  # last month, daily
    sem = asyncio.Semaphore(_CALORIE_CONCURRENCY)

    async def one(d: date) -> tuple[date, float | None]:
        async with sem:
            try:
                raw = _unwrap(
                    await registry.call_tool(ref, "get_daily_nutrition", {"date": d.isoformat()})
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("trends: calorie fetch %s failed: %s", d, exc)
                return d, None
        energy = (raw.get("summary") or {}).get("energy") if isinstance(raw, dict) else None
        return d, energy

    out: dict[date, float] = {}
    for d, energy in await asyncio.gather(*(one(d) for d in dates)):
        if energy is not None and energy > 0:
            out[d] = float(energy)
    return out


# ------------------------------------------------------------------
# Windowing / aggregation
# ------------------------------------------------------------------


def _window(m: dict[date, float], today: date, days: int) -> tuple[list[date], list[float]]:
    lo = today - timedelta(days=days)
    pts = sorted((d, v) for d, v in m.items() if lo <= d <= today)
    return [d for d, _ in pts], [v for _, v in pts]


# ------------------------------------------------------------------
# Rendering
# ------------------------------------------------------------------


def _set_date_axis(ax, days: int) -> None:
    """Pick a clean tick interval for the window so labels don't collide."""
    if days <= 7:
        loc = mdates.DayLocator(interval=1)
    elif days <= 31:
        loc = mdates.DayLocator(interval=7)
    else:
        loc = mdates.MonthLocator()
    ax.xaxis.set_major_locator(loc)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))


def _plot(
    ax,
    kind: str,
    color: str,
    xs: list[date],
    ys: list[float],
    today: date,
    days: int,
    *,
    ylabel: str | None = None,
    title: str | None = None,
    target: float | None = None,
    width: float = 0.8,
) -> None:
    if xs:
        if kind == "line":
            ax.plot(xs, ys, marker="o", ms=3, lw=1.6, color=color)
        else:
            ax.bar(xs, ys, width=width, color=color, alpha=0.85)
        if target:
            ax.axhline(target, ls="--", lw=1, color=_TARGET_COLOR, alpha=0.7)
        # Span the full window so the three columns are visually distinct and
        # sparse data reads in its true temporal context (not stretched to fill).
        ax.set_xlim(today - timedelta(days=days), today + timedelta(days=1))
        _set_date_axis(ax, days)
        ax.tick_params(axis="both", labelsize=7)
        ax.grid(True, axis="y", ls=":", alpha=0.4)
    else:
        ax.text(0.5, 0.5, "no data", ha="center", va="center",
                transform=ax.transAxes, color="#999999", fontsize=11)
        ax.set_xticks([])
        ax.set_yticks([])
    if title:
        ax.set_title(title, fontsize=10)
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=9)


async def generate_trends_png(user_id: int) -> bytes:
    """Fetch weight/calorie/sleep data and render the composite trends PNG."""
    today = date.today()
    start = today - timedelta(days=_MAX_WINDOW_DAYS)

    profile = memory.profile_summary(await memory.load_profile(user_id))
    unit = (profile.get("weight_unit") or "lbs").lower()
    cal_target = (profile.get("targets") or {}).get("calories")
    name = profile.get("name")

    weight, sleep, calories = await asyncio.gather(
        _fetch_weight(unit, start, today),
        _fetch_sleep(start, today),
        _fetch_calories(today),
    )

    rows = [
        ("weight", "line", _WEIGHT_COLOR, weight, f"Weight ({unit})", None),
        ("calories", "bar", _CALORIE_COLOR, calories, "Calories (kcal)", cal_target),
        ("sleep", "bar", _SLEEP_COLOR, sleep, "Sleep (hrs)", None),
    ]

    fig, axes = plt.subplots(3, 2, figsize=(9, 9))
    for r, (metric, kind, color, data, ylabel, target) in enumerate(rows):
        for c, (wlabel, days) in enumerate(WINDOWS):
            xs, ys = _window(data, today, days)
            _plot(
                axes[r][c], kind, color, xs, ys, today, days,
                ylabel=ylabel if c == 0 else None,
                title=wlabel if r == 0 else None,
                target=target,
                width=0.8,
            )

    who = f"{name}'s" if name else "Your"
    fig.suptitle(f"{who} trends · {today:%b %d, %Y}", fontsize=14, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.96))

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120)
    plt.close(fig)
    return buf.getvalue()
