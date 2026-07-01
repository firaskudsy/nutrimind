"""Minimal single-user auth: a static bearer token."""

import secrets

from fastapi import Depends, Header, HTTPException, status

from app.config import Settings, get_settings


async def require_token(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    """Validate `Authorization: Bearer <token>` against the configured token.

    If no token is configured (local dev), auth is disabled.
    """
    expected = settings.api_bearer_token
    if not expected:
        return  # auth disabled for local dev
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    presented = authorization.removeprefix("Bearer ").strip()
    if not secrets.compare_digest(presented, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
