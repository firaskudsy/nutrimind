"""Settings store (DB overrides env; secrets masked) + settings API."""

import tempfile

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def env(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp.name}")
    monkeypatch.setenv("API_BEARER_TOKEN", "")  # open for the test
    monkeypatch.setenv("AGENT_MODEL", "anthropic/claude-haiku-4-5")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key-123")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    from app.config import get_settings

    get_settings.cache_clear()
    from agents import memory

    memory._db_ready = False
    await memory.ensure_db()
    yield
    memory._db_ready = False


async def test_effective_and_override(env):
    from app import settings_store

    # Falls back to env when not overridden.
    assert await settings_store.get_effective("agent_model") == "anthropic/claude-haiku-4-5"
    assert await settings_store.provider_api_key("anthropic/claude-haiku-4-5") == "env-key-123"

    # DB override wins.
    await settings_store.set_many({"agent_model": "gemini/gemini-2.5-flash-lite", "gemini_api_key": "gem-key"})
    assert await settings_store.get_effective("agent_model") == "gemini/gemini-2.5-flash-lite"
    assert await settings_store.provider_api_key("gemini/gemini-2.5-flash-lite") == "gem-key"


async def test_secret_masking_and_no_clobber(env):
    from app import settings_store

    await settings_store.set_many({"anthropic_api_key": "real-secret"})
    view = {s["key"]: s for s in await settings_store.public_view()}
    assert view["anthropic_api_key"]["value"] == settings_store.MASK
    assert view["anthropic_api_key"]["configured"] is True

    # Submitting the mask back must NOT overwrite the stored secret.
    await settings_store.set_many({"anthropic_api_key": settings_store.MASK})
    assert await settings_store.get_effective("anthropic_api_key") == "real-secret"


async def test_settings_api(env):
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # API_BEARER_TOKEN is empty in this fixture → owner login is open.
        login = await c.post("/api/auth/login", json={"password": ""})
        headers = {"Authorization": f"Bearer {login.json()['token']}"}

        r = await c.get("/api/settings", headers=headers)
        assert r.status_code == 200
        body = r.json()
        assert any(s["key"] == "agent_model" for s in body["settings"])
        assert len(body["models"]) >= 3

        r = await c.put("/api/settings", json={"values": {"agent_model": "gpt-4o-mini"}}, headers=headers)
        assert r.status_code == 200

    from app import settings_store

    assert await settings_store.get_effective("agent_model") == "gpt-4o-mini"
