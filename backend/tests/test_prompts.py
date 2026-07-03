"""System prompt assembly -- especially that the pantry list actually lands in it,
since that's the entire mechanism behind "use my available foods for meal plans"."""

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

    memory._db_ready = False
    await memory.ensure_db()
    yield memory
    memory._db_ready = False


async def test_pantry_appears_in_system_prompt_with_notes(_db):
    from agents.prompts import build_system_prompt

    memory = _db
    await memory.add_pantry_item(1, "Chicken breast", "always frozen")
    await memory.add_pantry_item(1, "Quinoa")
    pantry = await memory.load_pantry(1)

    prompt = await build_system_prompt(None, pantry)
    assert "AVAILABLE FOODS" in prompt
    assert "- Chicken breast (always frozen)" in prompt
    assert "- Quinoa" in prompt
    # The instruction to prefer these for meal plans, not just list them, must survive.
    assert "first source for meal plans" in prompt
    assert "not something they said they have" in prompt


async def test_no_pantry_section_when_list_is_empty(_db):
    from agents.prompts import build_system_prompt

    prompt = await build_system_prompt(None, [])
    assert "AVAILABLE FOODS" not in prompt
