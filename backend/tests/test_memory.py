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
        1,
        name="Alex",
        weight_unit="lbs",
        goals="lose 10 lbs, build muscle",
        allergies="peanuts",
        daily_protein_target_g=160,
    )
    assert saved["name"] == "Alex"
    assert saved["targets"]["protein_g"] == 160

    # Partial update preserves prior fields.
    await memory.apply_profile_update(1, preferences="vegetarian")
    p = await memory.load_profile(1)
    assert p.name == "Alex"
    assert p.allergies == "peanuts"
    assert p.preferences == "vegetarian"
    assert p.targets["protein_g"] == 160

    # A different user has a separate, empty profile.
    assert await memory.load_profile(2) is None


async def test_profile_health_fields(_db):
    memory = _db
    saved = await memory.apply_profile_update(
        1, age=51, sex="Male", height_cm=171, conditions="sleep apnea, DDD in lower back"
    )
    assert saved["age"] == 51
    assert saved["sex"] == "male"  # lowercased for consistent BMR-formula matching
    assert saved["height_cm"] == 171
    assert saved["conditions"] == "sleep apnea, DDD in lower back"


async def test_replace_profile_fields_overwrites_including_blanks(_db):
    memory = _db
    await memory.apply_profile_update(
        1, name="Alex", goals="lose weight", allergies="peanuts", daily_protein_target_g=160
    )

    # The UI edit form can clear a field outright, unlike the agent's tool.
    saved = await memory.replace_profile_fields(
        1, {"name": "Alexis", "allergies": "", "daily_calorie_target": 2200}
    )
    assert saved["name"] == "Alexis"
    assert saved["allergies"] is None  # cleared
    assert saved["goals"] == "lose weight"  # untouched field preserved
    assert saved["targets"] == {"protein_g": 160, "calories": 2200}

    # Clearing a target removes it rather than storing a zero.
    saved = await memory.replace_profile_fields(1, {"daily_protein_target_g": 0})
    assert saved["targets"] == {"calories": 2200}

    # Creates a profile from scratch for a user with none yet.
    saved = await memory.replace_profile_fields(2, {"name": "Sam"})
    assert saved["name"] == "Sam"


async def test_health_markers_track_history_and_return_latest(_db):
    from datetime import date

    memory = _db
    await memory.save_health_marker(1, "LDL-C", 4.06, "mmol/L", day=date(2026, 1, 1))
    await memory.save_health_marker(1, "ldl-c", 3.80, "mmol/L", day=date(2026, 6, 1))
    await memory.save_health_marker(2, "LDL-C", 9.99, "mmol/L", day=date(2026, 1, 1))

    latest = await memory.latest_health_markers(1)
    assert set(latest) == {"ldl-c"}
    assert latest["ldl-c"]["value"] == 3.80  # the June reading, not the January one

    other = await memory.latest_health_markers(2)
    assert other["ldl-c"]["value"] == 9.99  # user 2 isolated from user 1's history


async def test_chat_history_is_per_user(_db):
    memory = _db
    await memory.save_message(1, "user", "hi")
    await memory.save_message(1, "assistant", "hello!")
    await memory.save_message(2, "user", "not yours")
    await memory.save_message(1, "user", "log 2 eggs")
    hist = await memory.recent_history(1, limit=10)
    assert [m["role"] for m in hist] == ["user", "assistant", "user"]
    assert hist[0]["content"] == "hi"  # chronological order
    assert hist[-1]["content"] == "log 2 eggs"
    assert all(m["content"] != "not yours" for m in hist)  # user 2 isolated


async def test_pantry_crud_and_per_user_isolation(_db):
    memory = _db
    chicken = await memory.add_pantry_item(1, "Chicken breast", "always frozen")
    await memory.add_pantry_item(1, "Quinoa")
    await memory.add_pantry_item(2, "Not yours")

    items = await memory.load_pantry(1)
    assert [i.name for i in items] == ["Chicken breast", "Quinoa"]  # alphabetical
    assert items[0].notes == "always frozen"

    other = await memory.load_pantry(2)
    assert [i.name for i in other] == ["Not yours"]  # user 2 isolated

    updated = await memory.update_pantry_item(1, chicken.id, name="Chicken thighs", notes="")
    assert updated.name == "Chicken thighs"
    assert updated.notes is None  # blank notes clears rather than storing ""

    # Can't update/delete another user's item by guessing its id.
    assert await memory.update_pantry_item(2, chicken.id, name="Hijacked") is None
    assert await memory.delete_pantry_item(2, chicken.id) is False
    assert (await memory.load_pantry(1))[0].name == "Chicken thighs"  # untouched

    assert await memory.delete_pantry_item(1, chicken.id) is True
    assert [i.name for i in await memory.load_pantry(1)] == ["Quinoa"]

    summary = memory.pantry_summary(await memory.load_pantry(1))
    assert summary == [{"id": summary[0]["id"], "name": "Quinoa", "notes": None,
                         "created_at": summary[0]["created_at"]}]


async def test_action_log_records_and_is_per_user(_db):
    memory = _db
    await memory.record_action(
        1, "chat", "log_weight", {"value": 322.4, "unit": "lbs"}, True, '{"status": "success"}'
    )
    await memory.record_action(
        1, "proactive", "log_weight", {"value": 322.4}, False, '{"status": "error", "message": "x"}'
    )
    await memory.record_action(2, "chat", "log_weight", {"value": 999}, True, "not yours")

    actions = await memory.recent_actions(1)
    assert len(actions) == 2
    assert actions[0].tool_name == "log_weight"
    # Newest first.
    assert actions[0].success is False
    assert actions[1].success is True

    summary = memory.action_log_summary(actions)
    assert summary[0]["arguments"] == {"value": 322.4}
    assert summary[0]["source"] == "proactive"

    other = await memory.recent_actions(2)
    assert len(other) == 1  # user 2 isolated from user 1's log


def test_memory_tools_registered(_db):
    from agents import memory

    assert len(memory.MEMORY_TOOL_SPECS) == 3
    assert set(memory.memory_dispatch(1)) == {
        "update_user_profile",
        "get_user_profile",
        "log_health_marker",
    }
    # OpenAI function-schema shape
    assert memory.MEMORY_TOOL_SPECS[0]["type"] == "function"
    assert "name" in memory.MEMORY_TOOL_SPECS[0]["function"]
