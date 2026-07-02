"""Google auth + admin-approval gate."""

import tempfile

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def env(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp.name}")
    monkeypatch.setenv("API_BEARER_TOKEN", "owner-pw")
    monkeypatch.setenv("ADMIN_EMAIL", "boss@example.com")
    monkeypatch.setenv("SESSION_SECRET", "test-secret")

    from app.config import get_settings

    get_settings.cache_clear()
    from agents import memory

    memory._db_ready = False
    await memory.ensure_db()
    yield
    memory._db_ready = False


async def test_admin_auto_approved_and_session(env):
    from app import authz

    user = await authz.upsert_from_google({"email": "BOSS@example.com", "name": "Boss"})
    assert user.role == "admin"
    assert user.status == "approved"

    token = authz.create_session(user)
    payload = authz.decode_session(token)
    assert payload["email"] == "boss@example.com"
    assert payload["role"] == "admin"


async def test_new_user_is_pending(env):
    from app import authz

    user = await authz.upsert_from_google({"email": "cousin@example.com", "name": "Cuz"})
    assert user.role == "user"
    assert user.status == "pending"


async def test_approval_flow_and_gating(env, monkeypatch):
    from app import authz
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # Owner logs in with the password → admin session.
        r = await c.post("/api/auth/login", json={"password": "owner-pw"})
        assert r.status_code == 200
        admin_token = r.json()["token"]
        assert r.json()["user"]["role"] == "admin"
        admin_h = {"Authorization": f"Bearer {admin_token}"}

        # A family member signs in with Google (mocked) → pending.
        monkeypatch.setattr(
            authz, "verify_google_token", lambda cred: {"email": "cousin@example.com", "name": "Cuz"}
        )
        r = await c.post("/api/auth/google", json={"credential": "fake"})
        assert r.status_code == 200
        cousin_token = r.json()["token"]
        assert r.json()["user"]["status"] == "pending"
        cousin_h = {"Authorization": f"Bearer {cousin_token}"}

        # Pending user is blocked from app endpoints (403), but /api/me works.
        assert (await c.get("/api/settings", headers=cousin_h)).status_code == 403
        assert (await c.get("/api/me", headers=cousin_h)).status_code == 200

        # A stranger with no token is 401.
        assert (await c.get("/api/settings")).status_code == 401

        # Admin sees the pending user and approves them.
        users = (await c.get("/api/admin/users", headers=admin_h)).json()["users"]
        cousin = next(u for u in users if u["email"] == "cousin@example.com")
        r = await c.post(f"/api/admin/users/{cousin['id']}/approve", headers=admin_h)
        assert r.status_code == 200 and r.json()["user"]["status"] == "approved"

        # Now the family member can use the app.
        assert (await c.get("/api/settings", headers=cousin_h)).status_code == 200

        # Non-admin cannot reach admin endpoints.
        assert (await c.get("/api/admin/users", headers=cousin_h)).status_code == 403
