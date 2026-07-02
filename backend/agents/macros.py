"""`/macros` — today's net carbs, fiber, and protein, broken down by food item.

Purely deterministic (no LLM), like /trends and /usage: the LLM adds nothing to
"which foods contributed how many grams of X," so this just fetches and formats.

Cronometer's diary entries carry only `foodId` + `grams` -- no name, no nutrient
breakdown. Each food's nutrients are stored per 100g in its food-database entry
(get_food_details), so a per-item contribution is `per_100g * grams / 100`.
Section *totals* use Cronometer's own server-computed day totals rather than a
sum of the per-item numbers, so a single failed food lookup can only ever thin
out that section's item list, never skew the headline total.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import date

from agents.trends import _ref, _unwrap
from mcp_clients import registry

logger = logging.getLogger(__name__)

_CONCURRENCY = 6  # gentle on the unofficial Cronometer API

# Stable Cronometer nutrient IDs (net carbs uses a synthetic negative ID; the
# rest match the food database's PRIMARY nutrient catalog).
_NUTRIENT_IDS = {"net_carbs": -1205, "fiber": 291, "protein": 203}
_SECTIONS = [("net_carbs", "NET CARBS"), ("fiber", "FIBER"), ("protein", "PROTEIN")]


async def _food_details(food_id: int, sem: asyncio.Semaphore) -> tuple[str, dict[int, float]] | None:
    """A food's name and its {nutrient_id: amount_per_100g} map, or None on failure."""
    ref = _ref("cronometer")
    if ref is None:
        return None
    async with sem:
        try:
            raw = _unwrap(
                await registry.call_tool(ref, "get_food_details", {"food_id": food_id})
            )
        except Exception as exc:  # noqa: BLE001 - one bad lookup shouldn't break the report
            logger.warning("macros: get_food_details(%s) failed: %s", food_id, exc)
            return None
    if not isinstance(raw, dict):
        return None
    name = raw.get("name") or f"food {food_id}"
    per_100g = {
        n["id"]: n.get("amount")
        for n in raw.get("nutrients", [])
        if isinstance(n, dict) and "id" in n
    }
    return name, per_100g


async def todays_macros(day: date | None = None) -> str:
    """NET CARBS / FIBER / PROTEIN for `day` (default today), each broken down by item."""
    ref = _ref("cronometer")
    if ref is None:
        return "Cronometer isn't connected right now."

    day = day or date.today()
    log = _unwrap(await registry.call_tool(ref, "get_food_log", {"date": day.isoformat()}))
    if not isinstance(log, dict):
        return "Couldn't read today's Cronometer diary."

    macros = ((log.get("nutrition_summary") or {}).get("macros")) or {}
    diary_entries = ((log.get("diary") or {}).get("diary")) or []
    servings = [e for e in diary_entries if e.get("type") == "Serving" and e.get("foodId")]
    if not servings:
        return "Nothing logged in Cronometer today yet."

    food_ids = list({e["foodId"] for e in servings})
    sem = asyncio.Semaphore(_CONCURRENCY)
    results = await asyncio.gather(*(_food_details(fid, sem) for fid in food_ids))
    food_data = {fid: r for fid, r in zip(food_ids, results, strict=True) if r is not None}

    # Per-item contribution to each macro, in grams; same-named items (e.g. two
    # servings of one dish) are combined into a single line.
    items: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for entry in servings:
        data = food_data.get(entry["foodId"])
        if data is None:
            continue
        name, per_100g = data
        grams = entry.get("grams") or 0
        for key, nutrient_id in _NUTRIENT_IDS.items():
            per_g = per_100g.get(nutrient_id)
            if per_g is not None:
                items[name][key] += per_g * grams / 100

    lines: list[str] = []
    for key, label in _SECTIONS:
        total = macros.get(key)
        lines.append(f"{label} ({total:.0f}g)" if total is not None else f"{label} (n/a)")
        ranked = sorted(items.items(), key=lambda kv: kv[1].get(key, 0), reverse=True)
        for name, vals in ranked:
            amount = vals.get(key, 0)
            if round(amount) > 0:  # a raw trace amount (e.g. 0.3g) must not print as "0g"
                lines.append(f"- {name} ({amount:.0f}g)")
        lines.append("")
    return "\n".join(lines).strip()
