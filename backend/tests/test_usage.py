"""Usage tracking + summary over a throwaway SQLite DB."""

import tempfile
from types import SimpleNamespace

import pytest


def _fake_response(prompt=1000, completion=200, cost=0.0012):
    return SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens=prompt, completion_tokens=completion, total_tokens=prompt + completion
        ),
        _hidden_params={"response_cost": cost},
    )


@pytest.fixture
async def usage_mod(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp.name}")

    from app.config import get_settings

    get_settings.cache_clear()

    from agents import memory, usage

    memory._db_ready = False
    await memory.ensure_db()
    yield usage
    memory._db_ready = False


async def test_record_and_summary(usage_mod):
    usage = usage_mod
    await usage.record_from_response(_fake_response(1000, 200, 0.0012), "anthropic/claude-haiku-4-5", "chat", 1)
    await usage.record_from_response(_fake_response(500, 100, 0.0006), "anthropic/claude-haiku-4-5", "proactive", 1)
    # A different user's usage must not bleed into user 1's totals.
    await usage.record_from_response(_fake_response(9999, 9999, 9.99), "anthropic/claude-haiku-4-5", "chat", 2)

    summary = await usage.usage_summary(1)
    today = summary["today"]
    assert today["calls"] == 2
    assert today["prompt"] == 1500
    assert today["completion"] == 300
    assert today["total"] == 1800
    assert abs(today["cost"] - 0.0018) < 1e-9
    # Rolling windows include today's records too.
    assert summary["week"]["calls"] == 2
    assert summary["month"]["calls"] == 2


async def test_fallback_pricing_when_no_cost(usage_mod):
    usage = usage_mod
    # No response_cost + LiteLLM won't price a fake response → fallback table used.
    resp = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=1_000_000, completion_tokens=0, total_tokens=1_000_000),
        _hidden_params={},
    )
    await usage.record_from_response(resp, "anthropic/claude-haiku-4-5", "chat", 1)
    summary = await usage.usage_summary(1)
    # Haiku input is $1 / 1M tokens → 1M prompt tokens ≈ $1.00.
    assert abs(summary["today"]["cost"] - 1.0) < 1e-6
