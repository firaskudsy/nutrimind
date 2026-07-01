"""NutriMind FastAPI backend.

Foundation layer: DB-backed CRUD for meals/weights/metrics/chat, an MCP-aware
health endpoint, and single-user bearer auth. The agent + Telegram layers plug
in on top of this in the next phase.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_token
from app.config import get_settings
from app.schemas import (
    ChatMessageIn,
    ChatMessageOut,
    HealthOut,
    MealCreate,
    MealOut,
    MetricOut,
    WeightCreate,
    WeightOut,
)
from db import models
from db.base import create_all, get_session, init_engine
from mcp_clients import registry

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    init_engine(settings.database_url)
    await create_all()
    logger.info("NutriMind backend started (db=%s)", settings.database_url.split("://")[0])
    yield


app = FastAPI(title="NutriMind Backend", version="0.1.0", lifespan=lifespan)


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


def run() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        log_level=settings.log_level.lower(),
    )
