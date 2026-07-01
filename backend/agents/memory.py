"""Persistence & memory for the assistant.

Backs the agent's long-term memory (the user's goals, allergies, preferences,
targets) and chat history with the app database. Exposes two local tools the
agent can call to read/update the profile, plus helpers the bot uses for
DB-backed conversation history.

The profile is a single row (id=1). Free-text fields (goals/allergies/
preferences) are stored as strings in the JSON columns; targets is a small dict.
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from app.config import get_settings
from db import models
from db.base import create_all, get_sessionmaker, init_engine

logger = logging.getLogger(__name__)

_PROFILE_ID = 1
_db_ready = False


async def ensure_db() -> None:
    """Initialize the engine and tables once (idempotent)."""
    global _db_ready
    if _db_ready:
        return
    init_engine(get_settings().database_url)
    await create_all()
    _db_ready = True


async def load_profile() -> models.UserProfile | None:
    await ensure_db()
    async with get_sessionmaker()() as session:
        return await session.get(models.UserProfile, _PROFILE_ID)


def profile_summary(p: models.UserProfile | None) -> dict:
    if p is None:
        return {}
    return {
        "name": p.name,
        "weight_unit": p.weight_unit,
        "goals": p.goals or None,
        "allergies": p.allergies or None,
        "preferences": p.preferences or None,
        "targets": p.targets or None,
    }


# ------------------------------------------------------------------
# Chat history
# ------------------------------------------------------------------


async def recent_history(limit: int = 40) -> list[dict]:
    """Return the last `limit` chat messages as Anthropic role/content dicts."""
    await ensure_db()
    async with get_sessionmaker()() as session:
        rows = await session.execute(
            select(models.ChatMessage)
            .order_by(models.ChatMessage.created_at.desc())
            .limit(limit)
        )
        msgs = list(rows.scalars())
    msgs.reverse()  # chronological
    return [{"role": m.role, "content": m.content} for m in msgs]


async def save_message(role: str, content: str) -> None:
    await ensure_db()
    async with get_sessionmaker()() as session:
        session.add(models.ChatMessage(role=role, content=content))
        await session.commit()


# ------------------------------------------------------------------
# Memory tools (called by the agent)
# ------------------------------------------------------------------


async def apply_profile_update(
    *,
    name: str = "",
    weight_unit: str = "",
    goals: str = "",
    allergies: str = "",
    preferences: str = "",
    daily_calorie_target: int = 0,
    daily_protein_target_g: int = 0,
) -> dict:
    """Upsert the singleton profile with any provided fields; return its summary."""
    await ensure_db()
    async with get_sessionmaker()() as session:
        p = await session.get(models.UserProfile, _PROFILE_ID)
        if p is None:
            p = models.UserProfile(id=_PROFILE_ID)
            session.add(p)
        if name:
            p.name = name
        if weight_unit:
            p.weight_unit = weight_unit.lower()
        if goals:
            p.goals = goals
        if allergies:
            p.allergies = allergies
        if preferences:
            p.preferences = preferences
        if daily_calorie_target or daily_protein_target_g:
            targets = dict(p.targets or {})
            if daily_calorie_target:
                targets["calories"] = daily_calorie_target
            if daily_protein_target_g:
                targets["protein_g"] = daily_protein_target_g
            p.targets = targets
        await session.commit()
        saved = profile_summary(p)
    logger.info("Updated user profile: %s", saved)
    return saved


_ALLOWED_FIELDS = {
    "name",
    "weight_unit",
    "goals",
    "allergies",
    "preferences",
    "daily_calorie_target",
    "daily_protein_target_g",
}


async def _tool_update_user_profile(args: dict) -> str:
    fields = {k: v for k, v in args.items() if k in _ALLOWED_FIELDS and v not in ("", None)}
    saved = await apply_profile_update(**fields)
    return f"Saved. Current profile: {saved}"


async def _tool_get_user_profile(args: dict) -> str:
    summary = profile_summary(await load_profile())
    return str(summary) if summary else "No profile saved yet."


# OpenAI-format tool schemas (LiteLLM passes these to any provider).
MEMORY_TOOL_SPECS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "update_user_profile",
            "description": (
                "Save or update durable facts about the user so you remember them next "
                "time: a health/diet goal, an allergy or food to avoid, a dietary "
                "preference (e.g. vegetarian), their name, preferred weight unit, or a "
                "calorie/protein target. Only pass the fields you're changing."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "weight_unit": {"type": "string", "enum": ["lbs", "kg"]},
                    "goals": {"type": "string"},
                    "allergies": {"type": "string"},
                    "preferences": {"type": "string"},
                    "daily_calorie_target": {"type": "integer"},
                    "daily_protein_target_g": {"type": "integer"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_user_profile",
            "description": (
                "Return everything you currently remember about the user (goals, "
                "allergies, preferences, targets, name, weight unit)."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

# name -> async callable(args_dict) -> result string
MEMORY_DISPATCH = {
    "update_user_profile": _tool_update_user_profile,
    "get_user_profile": _tool_get_user_profile,
}
