"""NutriMind FastAPI backend.

Foundation layer: DB-backed CRUD for meals/weights/metrics/chat, an MCP-aware
health endpoint, and single-user bearer auth. The agent + Telegram layers plug
in on top of this in the next phase.
"""

import base64
import json
import logging
from contextlib import asynccontextmanager

from dotenv import find_dotenv, load_dotenv
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from agents import memory, usage
from agents.nutrition_agent import ImageInput, run_turn
from app import authz, settings_store
from app.auth import require_token
from app.config import get_settings
from app.schemas import (
    ChatMessageIn,
    ChatMessageOut,
    GoogleLoginIn,
    HealthOut,
    LoginIn,
    LoginOut,
    MealCreate,
    MealOut,
    MetricOut,
    SettingsUpdate,
    WebChatIn,
    WebChatOut,
    WeightCreate,
    WeightOut,
)
from db import models
from db.base import create_all, get_session, init_engine
from mcp_clients import registry

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load .env into the environment (settings_store reads provider keys from it).
    load_dotenv(find_dotenv(usecwd=True), override=False)
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    init_engine(settings.database_url)
    await create_all()
    logger.info("NutriMind backend started (db=%s)", settings.database_url.split("://")[0])
    yield


app = FastAPI(title="NutriMind Backend", version="0.1.0", lifespan=lifespan)

# The web frontend is served from a different origin in dev.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthOut)
async def health(session: AsyncSession = Depends(get_session)) -> HealthOut:
    """Liveness + DB + MCP reachability (unauthenticated)."""
    db_ok = True
    try:
        await session.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        db_ok = False
    mcp_status = await registry.health_check()
    overall = "ok" if db_ok else "degraded"
    return HealthOut(status=overall, db=db_ok, mcp=mcp_status)


# ---- Meals ----
@app.post("/meals", response_model=MealOut, dependencies=[Depends(require_token)])
async def create_meal(
    payload: MealCreate, session: AsyncSession = Depends(get_session)
) -> MealOut:
    meal = models.Meal(**payload.model_dump(exclude_none=True))
    session.add(meal)
    await session.commit()
    await session.refresh(meal)
    return MealOut.model_validate(meal)


@app.get("/meals", response_model=list[MealOut], dependencies=[Depends(require_token)])
async def list_meals(
    limit: int = 50, session: AsyncSession = Depends(get_session)
) -> list[MealOut]:
    rows = await session.execute(
        select(models.Meal).order_by(models.Meal.created_at.desc()).limit(limit)
    )
    return [MealOut.model_validate(m) for m in rows.scalars()]


# ---- Weights ----
@app.post("/weights", response_model=WeightOut, dependencies=[Depends(require_token)])
async def create_weight(
    payload: WeightCreate, session: AsyncSession = Depends(get_session)
) -> WeightOut:
    from datetime import date as _date

    data = payload.model_dump(exclude_none=True)
    data.setdefault("day", _date.today())
    weight = models.Weight(**data)
    session.add(weight)
    await session.commit()
    await session.refresh(weight)
    return WeightOut.model_validate(weight)


@app.get("/weights", response_model=list[WeightOut], dependencies=[Depends(require_token)])
async def list_weights(
    limit: int = 90, session: AsyncSession = Depends(get_session)
) -> list[WeightOut]:
    rows = await session.execute(
        select(models.Weight).order_by(models.Weight.day.desc()).limit(limit)
    )
    return [WeightOut.model_validate(w) for w in rows.scalars()]


# ---- Metrics ----
@app.get("/metrics", response_model=list[MetricOut], dependencies=[Depends(require_token)])
async def list_metrics(
    limit: int = 200, session: AsyncSession = Depends(get_session)
) -> list[MetricOut]:
    rows = await session.execute(
        select(models.Metric).order_by(models.Metric.day.desc()).limit(limit)
    )
    return [MetricOut.model_validate(m) for m in rows.scalars()]


# ---- Chat history ----
@app.post("/chat", response_model=ChatMessageOut, dependencies=[Depends(require_token)])
async def post_chat(
    payload: ChatMessageIn, session: AsyncSession = Depends(get_session)
) -> ChatMessageOut:
    """Persist a user message. (Agent response wiring lands in the next phase.)"""
    msg = models.ChatMessage(role="user", content=payload.content)
    session.add(msg)
    await session.commit()
    await session.refresh(msg)
    return ChatMessageOut.model_validate(msg)


@app.get("/chat", response_model=list[ChatMessageOut], dependencies=[Depends(require_token)])
async def list_chat(
    limit: int = 50, session: AsyncSession = Depends(get_session)
) -> list[ChatMessageOut]:
    rows = await session.execute(
        select(models.ChatMessage)
        .order_by(models.ChatMessage.created_at.desc())
        .limit(limit)
    )
    return [ChatMessageOut.model_validate(m) for m in rows.scalars()]


# ==================================================================
# Web app API (/api/*)
# ==================================================================


@app.get("/api/config")
async def public_config() -> dict:
    """Public bootstrap config for the web app (no secrets)."""
    s = get_settings()
    return {
        "google_client_id": s.google_client_id,
        "google_enabled": bool(s.google_client_id),
        "password_login": bool(s.api_bearer_token),
    }


@app.post("/api/auth/login", response_model=LoginOut)
async def login(payload: LoginIn) -> LoginOut:
    """Owner (password) login → an admin session. Password is API_BEARER_TOKEN."""
    token = get_settings().api_bearer_token
    if token and payload.password != token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Wrong password")
    user = await authz.ensure_admin_user()
    return LoginOut(token=authz.create_session(user), user=authz.user_public(user))


@app.post("/api/auth/google", response_model=LoginOut)
async def google_login(payload: GoogleLoginIn) -> LoginOut:
    """Google sign-in → session. New users land as 'pending' until an admin approves."""
    try:
        info = authz.verify_google_token(payload.credential)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=401, detail="Invalid Google token") from exc
    user = await authz.upsert_from_google(info)
    return LoginOut(token=authz.create_session(user), user=authz.user_public(user))


@app.get("/api/me")
async def me(user=Depends(authz.get_current_user)) -> dict:
    return {"user": authz.user_public(user)}


# ---- Admin ----
@app.get("/api/admin/users")
async def admin_list_users(_admin=Depends(authz.require_admin)) -> dict:
    return {"users": [authz.user_public(u) for u in await authz.list_users()]}


@app.post("/api/admin/users/{user_id}/{action}")
async def admin_set_status(user_id: int, action: str, _admin=Depends(authz.require_admin)) -> dict:
    mapping = {"approve": "approved", "reject": "rejected", "pending": "pending"}
    if action not in mapping:
        raise HTTPException(status_code=400, detail="Unknown action")
    user = await authz.set_status(user_id, mapping[action])
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return {"user": authz.user_public(user)}


@app.get("/api/settings", dependencies=[Depends(authz.require_approved)])
async def get_settings_view() -> dict:
    return {"settings": await settings_store.public_view(), "models": settings_store.MODEL_CHOICES}


@app.put("/api/settings", dependencies=[Depends(authz.require_approved)])
async def put_settings(payload: SettingsUpdate) -> dict:
    await settings_store.set_many(payload.values)
    return {"settings": await settings_store.public_view()}


@app.post("/api/chat", response_model=WebChatOut, dependencies=[Depends(authz.require_approved)])
async def web_chat(payload: WebChatIn) -> WebChatOut:
    """One agent turn from the web UI (persists to shared chat history)."""
    image = None
    if payload.image_b64:
        try:
            image = ImageInput(
                data=base64.b64decode(payload.image_b64),
                media_type=payload.image_media_type,
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"Bad image: {exc}") from exc

    history = await memory.recent_history(limit=40)
    reply = (await run_turn(payload.message, image=image, history=history, source="web")).strip()
    await memory.save_message("user", payload.message or "(photo)")
    if reply:
        await memory.save_message("assistant", reply)
    return WebChatOut(reply=reply or "(no reply)")


@app.get("/api/chat/history", dependencies=[Depends(authz.require_approved)])
async def web_chat_history() -> dict:
    return {"messages": await memory.recent_history(limit=100)}


async def _cronometer_tool(tool: str, args: dict) -> dict | None:
    """Best-effort call to a Cronometer MCP tool; returns parsed JSON or None."""
    ref = next((r for r in registry.server_refs() if r.name == "cronometer"), None)
    if ref is None:
        return None
    try:
        result = await registry.call_tool(ref, tool, args)
        text_out = result[0] if isinstance(result, list) and result else result
        return json.loads(text_out) if isinstance(text_out, str) else text_out
    except Exception as exc:  # noqa: BLE001 - dashboard degrades gracefully
        logger.warning("cronometer %s failed: %s", tool, exc)
        return None


@app.get("/api/dashboard", dependencies=[Depends(authz.require_approved)])
async def dashboard() -> dict:
    """Aggregate data for the dashboard: cost, profile, nutrition, weight trend."""
    profile = memory.profile_summary(await memory.load_profile())
    return {
        "usage": await usage.usage_summary(),
        "profile": profile,
        "nutrition_today": await _cronometer_tool("get_daily_nutrition", {}),
        "weights": await _cronometer_tool("get_weight_history", {"unit": profile.get("weight_unit") or "lbs"}),
    }


def run() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        log_level=settings.log_level.lower(),
    )
