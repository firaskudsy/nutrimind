"""Backend smoke test: DB models + CRUD routes over an in-process SQLite DB.

MCP reachability is stubbed so the test never spawns external servers.
"""

import os
import tempfile

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def client(monkeypatch):
    # Point at a throwaway SQLite file BEFORE settings are built.
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp.name}")
    monkeypatch.setenv("API_BEARER_TOKEN", "")  # auth disabled for the test

    from app.config import get_settings

    get_settings.cache_clear()
    settings = get_settings()

    from db.base import create_all, init_engine

    init_engine(settings.database_url)
    await create_all()

    # Don't hit real MCP servers in /health.
    from mcp_clients import registry

    async def _fake_health():
        return {"cronometer": False, "google_health": False}

    monkeypatch.setattr(registry, "health_check", _fake_health)

    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    os.unlink(tmp.name)


async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["db"] is True
    assert "cronometer" in body["mcp"]


async def test_meal_crud(client):
    r = await client.post("/meals", json={"description": "2 eggs and toast"})
    assert r.status_code == 200
    meal = r.json()
    assert meal["status"] == "proposed"
    assert meal["description"] == "2 eggs and toast"

    r = await client.get("/meals")
    assert r.status_code == 200
    assert any(m["id"] == meal["id"] for m in r.json())


async def test_weight_and_chat(client):
    r = await client.post("/weights", json={"value": 199.0, "unit": "lbs"})
    assert r.status_code == 200
    assert r.json()["value"] == 199.0

    r = await client.post("/chat", json={"content": "what should I eat?"})
    assert r.status_code == 200
    assert r.json()["role"] == "user"

    r = await client.get("/chat")
    assert r.status_code == 200
    assert len(r.json()) >= 1
