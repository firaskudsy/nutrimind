"""NutriMind FastAPI backend.

Foundation layer: DB-backed CRUD for meals/weights/metrics/chat, an MCP-aware
health endpoint, and single-user bearer auth. The agent + Telegram layers plug
in on top of this in the next phase.
"""

import base64
import logging
import time
from contextlib import asynccontextmanager

from dotenv import find_dotenv, load_dotenv
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agents import macros, memory, proactive, prompts_store, trends, usage
from agents.nutrition_agent import ImageInput, run_turn
from app import authz, settings_store
from app.config import get_settings
from app.schemas import (
    GoogleLoginIn,
    HealthOut,
    LoginIn,
    LoginOut,
    ProfileUpdate,
    PromptsUpdate,
    SettingsUpdate,
    WebChatIn,
    WebChatOut,
)
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


@app.get("/api/prompts", dependencies=[Depends(authz.require_admin)])
async def get_prompts() -> dict:
    """The editable prompt templates (system prompt, /plan, /analyze, etc)."""
    return {"prompts": await prompts_store.public_view()}


@app.put("/api/prompts", dependencies=[Depends(authz.require_admin)])
async def put_prompts(payload: PromptsUpdate) -> dict:
    """Overrides apply to every user -- prompts are global, not per-user."""
    await prompts_store.set_many(payload.values)
    return {"prompts": await prompts_store.public_view()}


@app.get("/api/profile")
async def get_profile(user=Depends(authz.require_approved)) -> dict:
    """Everything the assistant remembers about the signed-in user."""
    return {
        "profile": memory.profile_summary(await memory.load_profile(user.id)),
        "labs": await memory.latest_health_markers(user.id),
    }


@app.put("/api/profile")
async def put_profile(payload: ProfileUpdate, user=Depends(authz.require_approved)) -> dict:
    fields = payload.model_dump(exclude_unset=True)
    return {"profile": await memory.replace_profile_fields(user.id, fields)}


WEB_HELP_TEXT = (
    "I'm NutriMind — your nutrition & health assistant. You can:\n\n"
    "• Tell me what you plan to eat (and when) — I'll analyze it and log it to Cronometer\n"
    "• Send a photo of a meal or a nutrition label — I'll identify and log it\n"
    "• Report your weight — I'll log it\n"
    "• Ask about today's calories/nutrition, your weight trend, or your Fitbit sleep/steps\n"
    "• Tell me your goals, allergies, and preferences — I'll remember them\n\n"
    "Commands:\n"
    "/plan — your personalized calorie & protein plan\n"
    "/analyze — rate today's eating 1-10 vs. your plan, with fixes\n"
    "/macros — today's net carbs, fiber & protein by food item\n"
    "/trends — charts of your weight, calories & sleep (week / month)\n"
    "/review — weekly review (diet + weight + Fitbit)\n"
    "/usage — token usage & cost (today / 7d / 30d)\n"
    "/help — this message\n\n"
    "Wellness guidance, not medical advice."
)

# Same commands as the Telegram bot, available by typing them in the web chat.
_COMMANDS = {"/plan", "/analyze", "/macros", "/trends", "/review", "/usage", "/help"}


async def _run_command(cmd: str, user_id: int) -> tuple[str, bytes | None]:
    """Dispatch a slash command exactly like the Telegram bot; returns (text, png|None)."""
    if cmd == "/plan":
        return await proactive.diet_plan(user_id), None
    if cmd == "/analyze":
        return await proactive.analyze_day(user_id), None
    if cmd == "/macros":
        return await macros.todays_macros(), None
    if cmd == "/review":
        instruction = await proactive.weekly_review_instruction()
        msg = await proactive.proactive_message(instruction, user_id, source="review")
        return msg or "Not enough data yet for a review.", None
    if cmd == "/usage":
        data = await usage.usage_summary(user_id)
        model = await settings_store.agent_model(get_settings().agent_model)
        return usage.format_summary(data, model), None
    if cmd == "/help":
        return WEB_HELP_TEXT, None
    png = await trends.generate_trends_png(user_id)
    return "Your weight, calories & sleep — last week / month.", png


@app.post("/api/chat", response_model=WebChatOut)
async def web_chat(payload: WebChatIn, user=Depends(authz.require_approved)) -> WebChatOut:
    """One agent turn from the web UI (scoped to the signed-in user)."""
    cmd = payload.message.strip().split()[0].lower() if payload.message.strip() else ""
    if cmd in _COMMANDS and not payload.image_b64:
        start = time.monotonic()
        try:
            reply, png = await _run_command(cmd, user.id)
        except Exception as exc:  # noqa: BLE001 - surface failures to the user
            logger.exception("web command %s failed", cmd)
            reply, png = f"Sorry — {cmd} failed: {exc}", None
        elapsed = time.monotonic() - start
        await memory.save_message(user.id, "user", payload.message)
        if reply:
            await memory.save_message(user.id, "assistant", reply)
        image_b64 = base64.standard_b64encode(png).decode("utf-8") if png else None
        return WebChatOut(reply=reply or "(no reply)", image_b64=image_b64, elapsed_seconds=elapsed)

    image = None
    if payload.image_b64:
        try:
            image = ImageInput(
                data=base64.b64decode(payload.image_b64),
                media_type=payload.image_media_type,
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"Bad image: {exc}") from exc

    history = await memory.recent_history(user.id, limit=40)
    start = time.monotonic()
    reply = (
        await run_turn(payload.message, user_id=user.id, image=image, history=history, source="web")
    ).strip()
    elapsed = time.monotonic() - start
    await memory.save_message(user.id, "user", payload.message or "(photo)")
    if reply:
        await memory.save_message(user.id, "assistant", reply)
    return WebChatOut(reply=reply or "(no reply)", elapsed_seconds=elapsed)


@app.get("/api/chat/history")
async def web_chat_history(user=Depends(authz.require_approved)) -> dict:
    return {"messages": await memory.recent_history(user.id, limit=100)}


async def _cronometer_tool(tool: str, args: dict) -> dict | None:
    """Best-effort call to a Cronometer MCP tool; returns parsed JSON or None."""
    ref = next((r for r in registry.server_refs() if r.name == "cronometer"), None)
    if ref is None:
        return None
    try:
        result = trends._unwrap(await registry.call_tool(ref, tool, args))
    except Exception as exc:  # noqa: BLE001 - dashboard degrades gracefully
        logger.warning("cronometer %s failed: %s", tool, exc)
        return None
    return result if isinstance(result, dict) else None


def _latest_weight(weights: dict | None) -> float | None:
    rows = ((weights or {}).get("history") or {}).get("data") or []
    return max(rows, key=lambda r: r["day"])["value"] if rows else None


@app.get("/api/dashboard")
async def dashboard(user=Depends(authz.require_approved)) -> dict:
    """Aggregate data for the dashboard: cost, profile, nutrition, weight trend."""
    profile = memory.profile_summary(await memory.load_profile(user.id))
    unit = profile.get("weight_unit") or "lbs"
    weights = await _cronometer_tool("get_weight_history", {"unit": unit})

    macro_targets = None
    latest_weight = _latest_weight(weights)
    if latest_weight is not None and all(profile.get(f) for f in ("age", "sex", "height_cm")):
        weight_kg = latest_weight * 0.45359237 if unit == "lbs" else latest_weight
        calorie_target = (profile.get("targets") or {}).get("calories")
        macro_targets = proactive.macro_targets_g(
            weight_kg, profile["height_cm"], profile["age"], profile["sex"], calorie_target
        )

    return {
        "usage": await usage.usage_summary(user.id),
        "profile": profile,
        "nutrition_today": await _cronometer_tool("get_daily_nutrition", {}),
        "weights": weights,
        "macro_targets": macro_targets,
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
