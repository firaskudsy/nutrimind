"""Persistence & memory tests over a throwaway SQLite DB."""

import tempfile

import pytest


@pytest.fixture
async def _db(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp.name}")

    from app.config import get_settings

    get_settings.cache_clear()

    from agents import memory

    memory._db_ready = False  # force re-init against the temp DB
    await memory.ensure_db()
    yield memory
    memory._db_ready = False


async def test_profile_upsert_and_load(_db):
    memory = _db
    saved = await memory.apply_profile_update(
        name="Alex",
        weight_unit="lbs",
        goals="lose 10 lbs, build muscle",
        allergies="peanuts",
        daily_protein_target_g=160,
    )
    assert saved["name"] == "Alex"
    assert saved["targets"]["protein_g"] == 160

    # Partial update preserves prior fields.
    await memory.apply_profile_update(preferences="vegetarian")
    p = await memory.load_profile()
    assert p.name == "Alex"
    assert p.allergies == "peanuts"
    assert p.preferences == "vegetarian"
    assert p.targets["protein_g"] == 160


async def test_chat_history_roundtrip(_db):
    memory = _db
    await memory.save_message("user", "hi")
    await memory.save_message("assistant", "hello!")
    await memory.save_message("user", "log 2 eggs")
    hist = await memory.recent_history(limit=10)
    assert [m["role"] for m in hist] == ["user", "assistant", "user"]
    assert hist[0]["content"] == "hi"  # chronological order
    assert hist[-1]["content"] == "log 2 eggs"


def test_memory_tools_registered(_db):
    from agents import memory

    assert len(memory.MEMORY_TOOL_SPECS) == 2
    assert set(memory.MEMORY_DISPATCH) == {"update_user_profile", "get_user_profile"}
    # OpenAI function-schema shape
    assert memory.MEMORY_TOOL_SPECS[0]["type"] == "function"
    assert "name" in memory.MEMORY_TOOL_SPECS[0]["function"]
