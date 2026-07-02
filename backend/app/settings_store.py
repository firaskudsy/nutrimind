"""DB-backed runtime settings, editable from the web UI.

Each setting falls back to its .env value when not overridden in the DB. LLM
settings apply immediately (the agent reads them per turn); credentials used by
the separate Cronometer/Telegram processes are flagged restart-required.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from agents.memory import ensure_db
from db import models
from db.base import get_sessionmaker


@dataclass(frozen=True)
class SettingSpec:
    key: str
    env: str
    label: str
    group: str
    secret: bool = False
    live: bool = True  # applies without a restart


# The settings surfaced in the web UI, in display order.
SETTINGS_SCHEMA: list[SettingSpec] = [
    SettingSpec("agent_model", "AGENT_MODEL", "LLM model", "LLM"),
    SettingSpec("anthropic_api_key", "ANTHROPIC_API_KEY", "Anthropic API key", "LLM", secret=True),
    SettingSpec("gemini_api_key", "GEMINI_API_KEY", "Gemini API key", "LLM", secret=True),
    SettingSpec("openai_api_key", "OPENAI_API_KEY", "OpenAI API key", "LLM", secret=True),
    SettingSpec("cronometer_username", "CRONOMETER_USERNAME", "Cronometer email", "Cronometer", live=False),
    SettingSpec("cronometer_password", "CRONOMETER_PASSWORD", "Cronometer password", "Cronometer", secret=True, live=False),
    SettingSpec("telegram_bot_token", "TELEGRAM_BOT_TOKEN", "Telegram bot token", "Telegram", secret=True, live=False),
    SettingSpec("telegram_allowed_user_ids", "TELEGRAM_ALLOWED_USER_IDS", "Allowed Telegram user IDs", "Telegram", live=False),
]

_SPEC_BY_KEY = {s.key: s for s in SETTINGS_SCHEMA}

# Suggested models for the UI dropdown (label -> value).
MODEL_CHOICES = [
    {"value": "anthropic/claude-haiku-4-5", "label": "Claude Haiku 4.5 (cheap, reliable)"},
    {"value": "anthropic/claude-sonnet-4-6", "label": "Claude Sonnet 4.6 (balanced)"},
    {"value": "anthropic/claude-opus-4-8", "label": "Claude Opus 4.8 (best)"},
    {"value": "gemini/gemini-2.5-flash-lite", "label": "Gemini 2.5 Flash-Lite (cheapest)"},
    {"value": "gpt-4o-mini", "label": "GPT-4o mini"},
]


async def get_effective(key: str) -> str:
    """DB override if set, else the .env value, else empty string."""
    spec = _SPEC_BY_KEY.get(key)
    env_name = spec.env if spec else key.upper()
    await ensure_db()
    async with get_sessionmaker()() as session:
        row = await session.get(models.Setting, key)
    if row and row.value:
        return row.value
    return os.getenv(env_name, "")


async def set_many(values: dict[str, str]) -> None:
    """Upsert settings. Empty string clears the override (falls back to .env).

    A secret submitted as the mask sentinel ('********') is ignored (unchanged).
    """
    await ensure_db()
    async with get_sessionmaker()() as session:
        for key, value in values.items():
            if key not in _SPEC_BY_KEY:
                continue
            if _SPEC_BY_KEY[key].secret and value == MASK:
                continue
            row = await session.get(models.Setting, key)
            if row is None:
                session.add(models.Setting(key=key, value=value))
            else:
                row.value = value
        await session.commit()


MASK = "********"


async def public_view() -> list[dict]:
    """All settings for the UI: secrets masked, with metadata."""
    out = []
    for spec in SETTINGS_SCHEMA:
        value = await get_effective(spec.key)
        out.append(
            {
                "key": spec.key,
                "label": spec.label,
                "group": spec.group,
                "secret": spec.secret,
                "live": spec.live,
                "value": (MASK if (spec.secret and value) else value),
                "configured": bool(value),
            }
        )
    return out


async def provider_api_key(model: str) -> str | None:
    """The API key for the provider implied by a LiteLLM model string."""
    if model.startswith("anthropic/"):
        return (await get_effective("anthropic_api_key")) or None
    if model.startswith("gemini/"):
        return (await get_effective("gemini_api_key")) or None
    if model.startswith(("gpt", "openai/")):
        return (await get_effective("openai_api_key")) or None
    return None


async def agent_model(default: str) -> str:
    return (await get_effective("agent_model")) or default
