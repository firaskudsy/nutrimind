"""Authentication & authorization: Google sign-in + admin approval.

Flow: the web app sends a Google ID token -> we verify it with Google -> upsert
a User (the ADMIN_EMAIL is auto-approved as admin, everyone else is 'pending')
-> issue our own signed session JWT. Every API call carries that JWT as a Bearer
token; dependencies gate on approval/role.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, Header, HTTPException, status
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from sqlalchemy import select

from agents.memory import ensure_db
from app.config import get_settings
from db import models
from db.base import get_sessionmaker


def _secret() -> bytes:
    """A stable 32-byte HMAC key derived from the configured secret.

    Hashing lets any-length secret work (and avoids PyJWT's short-key rejection).
    Set SESSION_SECRET to a long random string in production.
    """
    s = get_settings()
    raw = s.session_secret or s.api_bearer_token or "nutrimind-dev-secret"
    return hashlib.sha256(raw.encode()).digest()


# ------------------------------------------------------------------
# Google ID token verification (patched in tests)
# ------------------------------------------------------------------


def verify_google_token(credential: str) -> dict:
    """Verify a Google ID token and return {email, name, picture, sub}."""
    settings = get_settings()
    info = google_id_token.verify_oauth2_token(
        credential,
        google_requests.Request(),
        settings.google_client_id or None,
    )
    if not info.get("email_verified", True):
        raise ValueError("email not verified")
    return {
        "email": info["email"],
        "name": info.get("name"),
        "picture": info.get("picture"),
        "sub": info.get("sub"),
    }


# ------------------------------------------------------------------
# Session JWTs
# ------------------------------------------------------------------


def create_session(user: models.User) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),  # RFC 7519: sub must be a string
        "email": user.email,
        "role": user.role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=settings.session_ttl_hours)).timestamp()),
    }
    return jwt.encode(payload, _secret(), algorithm="HS256")


def decode_session(token: str) -> dict:
    return jwt.decode(token, _secret(), algorithms=["HS256"])


# ------------------------------------------------------------------
# User store
# ------------------------------------------------------------------


async def upsert_from_google(info: dict) -> models.User:
    settings = get_settings()
    email = info["email"].strip().lower()
    is_admin = bool(settings.admin_email) and email == settings.admin_email.strip().lower()

    await ensure_db()
    async with get_sessionmaker()() as session:
        user = (
            await session.execute(select(models.User).where(models.User.email == email))
        ).scalar_one_or_none()
        if user is None:
            user = models.User(
                email=email,
                name=info.get("name"),
                picture=info.get("picture"),
                google_sub=info.get("sub"),
                role="admin" if is_admin else "user",
                status="approved" if is_admin else "pending",
            )
            session.add(user)
        else:
            user.name = info.get("name") or user.name
            user.picture = info.get("picture") or user.picture
            if is_admin:  # keep the admin promoted even if created earlier
                user.role = "admin"
                user.status = "approved"
        await session.commit()
        await session.refresh(user)
        return user


async def ensure_admin_user() -> models.User:
    """Get/create the admin user for the password (owner) login path."""
    settings = get_settings()
    email = (settings.admin_email or "admin@nutrimind.local").strip().lower()
    await ensure_db()
    async with get_sessionmaker()() as session:
        user = (
            await session.execute(select(models.User).where(models.User.email == email))
        ).scalar_one_or_none()
        if user is None:
            user = models.User(email=email, name="Admin", role="admin", status="approved")
            session.add(user)
        else:
            user.role = "admin"
            user.status = "approved"
        await session.commit()
        await session.refresh(user)
        return user


async def list_users() -> list[models.User]:
    await ensure_db()
    async with get_sessionmaker()() as session:
        rows = await session.execute(select(models.User).order_by(models.User.created_at))
        return list(rows.scalars())


async def set_status(user_id: int, new_status: str) -> models.User | None:
    await ensure_db()
    async with get_sessionmaker()() as session:
        user = await session.get(models.User, user_id)
        if user is None:
            return None
        user.status = new_status
        await session.commit()
        await session.refresh(user)
        return user


def user_public(u: models.User) -> dict:
    return {
        "id": u.id,
        "email": u.email,
        "name": u.name,
        "picture": u.picture,
        "role": u.role,
        "status": u.status,
    }


# ------------------------------------------------------------------
# FastAPI dependencies
# ------------------------------------------------------------------


def _unauth() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(authorization: str | None = Header(default=None)) -> models.User:
    if not authorization or not authorization.startswith("Bearer "):
        raise _unauth()
    try:
        payload = decode_session(authorization.removeprefix("Bearer ").strip())
    except jwt.PyJWTError as exc:
        raise _unauth() from exc
    try:
        user_id = int(payload.get("sub"))
    except (TypeError, ValueError) as exc:
        raise _unauth() from exc
    await ensure_db()
    async with get_sessionmaker()() as session:
        user = await session.get(models.User, user_id)
    if user is None:
        raise _unauth()
    return user


def require_approved(user: models.User = Depends(get_current_user)) -> models.User:
    if user.status != "approved":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account pending approval")
    return user


def require_admin(user: models.User = Depends(get_current_user)) -> models.User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    return user
