"""Backend smoke test: app boots, /health and /api/config respond.

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
    monkeypatch.setenv("API_BEARER_TOKEN", "")

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


async def test_public_config(client):
    r = await client.get("/api/config")
    assert r.status_code == 200
    body = r.json()
    assert "google_enabled" in body
    assert "password_login" in body


async def test_protected_endpoints_require_auth(client):
    # No token → 401 (fail-closed).
    assert (await client.get("/api/dashboard")).status_code == 401
    assert (await client.get("/api/settings")).status_code == 401
