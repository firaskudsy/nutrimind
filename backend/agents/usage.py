"""Token-usage and cost tracking for the /usage report.

Each LLM call's tokens + cost are recorded to the `usage` table. Cost comes from
LiteLLM when it knows the model, otherwise from a small fallback price table so
figures stay meaningful for newer models.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import litellm
from sqlalchemy import func, select

from agents.memory import ensure_db
from db import models
from db.base import get_sessionmaker

logger = logging.getLogger(__name__)

# (input $/1M, output $/1M) — fallback when LiteLLM has no price for the model.
_FALLBACK_PRICES = {
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-4-8": (5.0, 25.0),
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-3.1-flash-lite": (0.25, 1.50),
    "gpt-4o-mini": (0.15, 0.60),
}


def _fallback_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    for key, (in_price, out_price) in _FALLBACK_PRICES.items():
        if key in model:
            return prompt_tokens / 1e6 * in_price + completion_tokens / 1e6 * out_price
    return 0.0


def _extract(resp: Any, model: str) -> tuple[int, int, int, float]:
    usage = getattr(resp, "usage", None)
    pt = int(getattr(usage, "prompt_tokens", 0) or 0)
    ct = int(getattr(usage, "completion_tokens", 0) or 0)
    tt = int(getattr(usage, "total_tokens", 0) or (pt + ct))

    cost = 0.0
    hidden = getattr(resp, "_hidden_params", None)
    if isinstance(hidden, dict) and hidden.get("response_cost"):
        cost = float(hidden["response_cost"])
    if not cost:
        try:
            cost = float(litellm.completion_cost(completion_response=resp) or 0.0)
        except Exception:  # noqa: BLE001 - pricing lookup is best-effort
            cost = 0.0
    if not cost:
        cost = _fallback_cost(model, pt, ct)
    return pt, ct, tt, cost


async def record_from_response(resp: Any, model: str, source: str, user_id: int) -> None:
    """Persist one call's usage. Never raises (usage tracking must not break a turn)."""
    try:
        pt, ct, tt, cost = _extract(resp, model)
        await ensure_db()
        async with get_sessionmaker()() as session:
            session.add(
                models.UsageRecord(
                    user_id=user_id,
                    model=model,
                    source=source,
                    prompt_tokens=pt,
                    completion_tokens=ct,
                    total_tokens=tt,
                    cost_usd=cost,
                )
            )
            await session.commit()
    except Exception:  # noqa: BLE001 - best-effort accounting
        logger.exception("failed to record usage")


async def _totals_since(session, since: datetime, user_id: int) -> dict:
    row = await session.execute(
        select(
            func.count(models.UsageRecord.id),
            func.coalesce(func.sum(models.UsageRecord.prompt_tokens), 0),
            func.coalesce(func.sum(models.UsageRecord.completion_tokens), 0),
            func.coalesce(func.sum(models.UsageRecord.total_tokens), 0),
            func.coalesce(func.sum(models.UsageRecord.cost_usd), 0.0),
        ).where(
            models.UsageRecord.created_at >= since,
            models.UsageRecord.user_id == user_id,
        )
    )
    calls, pt, ct, tt, cost = row.one()
    return {
        "calls": int(calls),
        "prompt": int(pt),
        "completion": int(ct),
        "total": int(tt),
        "cost": float(cost),
    }


async def usage_summary(user_id: int) -> dict:
    """One user's totals for today (local midnight), last 7 days, last 30 days."""
    await ensure_db()
    now = datetime.now(timezone.utc)
    local_midnight = (
        datetime.now()
        .astimezone()
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .astimezone(timezone.utc)
    )
    windows = {
        "today": local_midnight,
        "week": now - timedelta(days=7),
        "month": now - timedelta(days=30),
    }
    async with get_sessionmaker()() as session:
        return {
            label: await _totals_since(session, since, user_id)
            for label, since in windows.items()
        }
