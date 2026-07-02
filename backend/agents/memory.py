"""Persistence & memory for the assistant.

Backs the agent's long-term memory (the user's goals, allergies, conditions,
preferences, targets, and dated lab/health markers) and chat history with the
app database. Exposes local tools the agent can call to read/update the
profile and log lab results, plus helpers the bot uses for DB-backed
conversation history.

Everything is per-user (keyed by user_id). Free-text fields (goals/allergies/
conditions/preferences) are stored as strings in the JSON columns; targets is
a small dict. Lab markers (e.g. LDL-C) reuse the shared Metric table
(source="labs") so a marker's history is tracked the same way Fitbit data is.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from functools import partial

from sqlalchemy import select

from app.config import get_settings
from db import models
from db.base import create_all, get_sessionmaker, init_engine

logger = logging.getLogger(__name__)

_db_ready = False


async def ensure_db() -> None:
    """Initialize the engine and tables once (idempotent)."""
    global _db_ready
    if _db_ready:
        return
    init_engine(get_settings().database_url)
    await create_all()
    _db_ready = True


async def load_profile(user_id: int) -> models.UserProfile | None:
    await ensure_db()
    async with get_sessionmaker()() as session:
        rows = await session.execute(
            select(models.UserProfile).where(models.UserProfile.user_id == user_id)
        )
        return rows.scalar_one_or_none()


def profile_summary(p: models.UserProfile | None) -> dict:
    if p is None:
        return {}
    return {
        "name": p.name,
        "weight_unit": p.weight_unit,
        "age": p.age,
        "sex": p.sex,
        "height_cm": p.height_cm,
        "goals": p.goals or None,
        "allergies": p.allergies or None,
        "conditions": p.conditions or None,
        "preferences": p.preferences or None,
        "targets": p.targets or None,
    }


# ------------------------------------------------------------------
# Chat history
# ------------------------------------------------------------------


async def recent_history(user_id: int, limit: int = 40) -> list[dict]:
    """Return the user's last `limit` chat messages as role/content dicts."""
    await ensure_db()
    async with get_sessionmaker()() as session:
        rows = await session.execute(
            select(models.ChatMessage)
            .where(models.ChatMessage.user_id == user_id)
            .order_by(models.ChatMessage.created_at.desc())
            .limit(limit)
        )
        msgs = list(rows.scalars())
    msgs.reverse()  # chronological
    return [{"role": m.role, "content": m.content} for m in msgs]


async def save_message(user_id: int, role: str, content: str) -> None:
    await ensure_db()
    async with get_sessionmaker()() as session:
        session.add(models.ChatMessage(user_id=user_id, role=role, content=content))
        await session.commit()


# ------------------------------------------------------------------
# Memory tools (called by the agent)
# ------------------------------------------------------------------


async def apply_profile_update(
    user_id: int,
    *,
    name: str = "",
    weight_unit: str = "",
    age: int = 0,
    sex: str = "",
    height_cm: float = 0.0,
    goals: str = "",
    allergies: str = "",
    conditions: str = "",
    preferences: str = "",
    daily_calorie_target: int = 0,
    daily_protein_target_g: int = 0,
) -> dict:
    """Upsert the user's profile with any provided fields; return its summary."""
    await ensure_db()
    async with get_sessionmaker()() as session:
        rows = await session.execute(
            select(models.UserProfile).where(models.UserProfile.user_id == user_id)
        )
        p = rows.scalar_one_or_none()
        if p is None:
            p = models.UserProfile(user_id=user_id)
            session.add(p)
        if name:
            p.name = name
        if weight_unit:
            p.weight_unit = weight_unit.lower()
        if age:
            p.age = age
        if sex:
            p.sex = sex.lower()
        if height_cm:
            p.height_cm = height_cm
        if goals:
            p.goals = goals
        if allergies:
            p.allergies = allergies
        if conditions:
            p.conditions = conditions
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


_EDITABLE_PROFILE_FIELDS = {
    "name",
    "weight_unit",
    "age",
    "sex",
    "height_cm",
    "goals",
    "allergies",
    "conditions",
    "preferences",
}


async def replace_profile_fields(user_id: int, fields: dict) -> dict:
    """Overwrite exactly the given profile fields; used by the settings UI's edit
    form. Unlike `apply_profile_update` -- which the agent calls incrementally and
    ignores blanks so it never erases a fact by omission -- this applies whatever
    was submitted, including clearing a field to empty.
    """
    await ensure_db()
    async with get_sessionmaker()() as session:
        rows = await session.execute(
            select(models.UserProfile).where(models.UserProfile.user_id == user_id)
        )
        p = rows.scalar_one_or_none()
        if p is None:
            p = models.UserProfile(user_id=user_id)
            session.add(p)
        for key in _EDITABLE_PROFILE_FIELDS & fields.keys():
            value = fields[key]
            if key in ("weight_unit", "sex") and value:
                value = value.lower()
            setattr(p, key, value)
        if "daily_calorie_target" in fields or "daily_protein_target_g" in fields:
            targets = dict(p.targets or {})
            if "daily_calorie_target" in fields:
                if fields["daily_calorie_target"]:
                    targets["calories"] = fields["daily_calorie_target"]
                else:
                    targets.pop("calories", None)
            if "daily_protein_target_g" in fields:
                if fields["daily_protein_target_g"]:
                    targets["protein_g"] = fields["daily_protein_target_g"]
                else:
                    targets.pop("protein_g", None)
            p.targets = targets
        await session.commit()
        return profile_summary(p)


_ALLOWED_FIELDS = {
    "name",
    "weight_unit",
    "age",
    "sex",
    "height_cm",
    "goals",
    "allergies",
    "conditions",
    "preferences",
    "daily_calorie_target",
    "daily_protein_target_g",
}


async def _tool_update_user_profile(user_id: int, args: dict) -> str:
    fields = {k: v for k, v in args.items() if k in _ALLOWED_FIELDS and v not in ("", None)}
    saved = await apply_profile_update(user_id, **fields)
    return f"Saved. Current profile: {saved}"


async def _tool_get_user_profile(user_id: int, args: dict) -> str:
    summary = profile_summary(await load_profile(user_id))
    markers = await latest_health_markers(user_id)
    if markers:
        summary["recent_labs"] = markers
    return str(summary) if summary else "No profile saved yet."


# ------------------------------------------------------------------
# Health markers (labs) -- dated points in the shared Metric table,
# source="labs", so a marker's history (e.g. LDL over successive
# checkups) is tracked the same way Fitbit/Google Health metrics are.
# ------------------------------------------------------------------

_LABS_SOURCE = "labs"


async def save_health_marker(
    user_id: int, marker: str, value: float, unit: str = "", day: date | None = None
) -> None:
    await ensure_db()
    async with get_sessionmaker()() as session:
        session.add(
            models.Metric(
                user_id=user_id,
                day=day or datetime.now().astimezone().date(),
                source=_LABS_SOURCE,
                type=marker.strip().lower(),
                value=value,
                unit=unit or None,
            )
        )
        await session.commit()


async def latest_health_markers(user_id: int) -> dict[str, dict]:
    """Return the most recent value per marker type, e.g. {"ldl_c": {"value": 4.06, ...}}."""
    await ensure_db()
    async with get_sessionmaker()() as session:
        rows = await session.execute(
            select(models.Metric)
            .where(models.Metric.user_id == user_id, models.Metric.source == _LABS_SOURCE)
            .order_by(models.Metric.day.desc(), models.Metric.created_at.desc())
        )
        latest: dict[str, dict] = {}
        for m in rows.scalars():
            latest.setdefault(
                m.type, {"value": m.value, "unit": m.unit, "date": m.day.isoformat()}
            )
    return latest


async def _tool_log_health_marker(user_id: int, args: dict) -> str:
    marker = str(args.get("marker") or "").strip()
    value = args.get("value")
    if not marker or value is None:
        return "Error: marker and value are required."
    day = None
    if args.get("date"):
        try:
            day = date.fromisoformat(args["date"])
        except ValueError:
            pass
    await save_health_marker(user_id, marker, float(value), str(args.get("unit") or ""), day)
    return f"Saved {marker} = {value} {args.get('unit') or ''}".strip() + "."


# OpenAI-format tool schemas (LiteLLM passes these to any provider).
MEMORY_TOOL_SPECS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "update_user_profile",
            "description": (
                "Save or update durable facts about the user so you remember them next "
                "time: a health/diet goal, an allergy or food to avoid, a dietary "
                "preference (e.g. vegetarian), their name, preferred weight unit, age, "
                "sex, height, a chronic health condition (e.g. sleep apnea, a back "
                "condition), or a calorie/protein target. Only pass the fields you're "
                "changing. Conditions/allergies/goals/preferences are free text -- "
                "include everything the user told you, even across multiple messages."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "weight_unit": {"type": "string", "enum": ["lbs", "kg"]},
                    "age": {"type": "integer", "description": "Age in years."},
                    "sex": {"type": "string", "description": "e.g. male, female."},
                    "height_cm": {"type": "number", "description": "Height in centimeters."},
                    "goals": {"type": "string"},
                    "allergies": {"type": "string"},
                    "conditions": {
                        "type": "string",
                        "description": (
                            "Chronic health conditions relevant to diet/exercise safety, "
                            "e.g. 'sleep apnea, DDD in upper/mid/lower back, chronic pain "
                            "between right shoulder blade and spine'."
                        ),
                    },
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
                "allergies, conditions, preferences, targets, name, age, sex, height, "
                "weight unit, and their most recent lab/blood-test values)."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "log_health_marker",
            "description": (
                "Save a dated blood-test/lab value the user reports (e.g. LDL-C, "
                "HDL-C, triglycerides, A1C, blood pressure). Call once per marker. "
                "Keeps a history, so log a new value even if one already exists -- "
                "don't overwrite, this tracks change over time."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "marker": {
                        "type": "string",
                        "description": "Marker name, e.g. 'LDL-C', 'HDL-C', 'triglycerides'.",
                    },
                    "value": {"type": "number"},
                    "unit": {
                        "type": "string",
                        "description": "e.g. mmol/L or mg/dL, as the user stated it.",
                    },
                    "date": {
                        "type": "string",
                        "description": "Test date as YYYY-MM-DD, if known. Defaults to today.",
                    },
                },
                "required": ["marker", "value"],
            },
        },
    },
]

def memory_dispatch(user_id: int) -> dict:
    """name -> async callable(args) -> str, bound to a specific user."""
    return {
        "update_user_profile": partial(_tool_update_user_profile, user_id),
        "get_user_profile": partial(_tool_get_user_profile, user_id),
        "log_health_marker": partial(_tool_log_health_marker, user_id),
    }
