"""SQLAlchemy ORM models — the source of truth for NutriMind.

Single-user system. Postgres in prod (SQLite for local dev/tests). JSON columns
use the portable `JSON` type so the same models run on both backends.
"""

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UserProfile(Base):
    """Single-row profile injected into the agent's cached system prompt."""

    __tablename__ = "user_profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    weight_unit: Mapped[str] = mapped_column(String(8), default="lbs")
    goals: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    allergies: Mapped[list[str]] = mapped_column(JSON, default=list)
    preferences: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    targets: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class Meal(Base):
    """A planned/analyzed/logged meal."""

    __tablename__ = "meals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
    planned_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    description: Mapped[str] = mapped_column(Text)
    photo_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    meal_group: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # proposed -> approved -> logged (or rejected)
    status: Mapped[str] = mapped_column(String(16), default="proposed", index=True)
    advice: Mapped[str | None] = mapped_column(Text, nullable=True)
    nutrition: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    cronometer_logged: Mapped[bool] = mapped_column(Boolean, default=False)


class Weight(Base):
    """A body-weight measurement (mirrored to Cronometer)."""

    __tablename__ = "weights"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(8), default="lbs")
    source: Mapped[str] = mapped_column(String(32), default="user")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


class Metric(Base):
    """A health metric point from an external source (e.g. Fitbit)."""

    __tablename__ = "metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    source: Mapped[str] = mapped_column(String(32), index=True)  # e.g. fitbit
    type: Mapped[str] = mapped_column(String(32), index=True)  # sleep|steps|hr|activity
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(16), nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


class Goal(Base):
    """A user goal (e.g. weight target, protein floor)."""

    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    target: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


class ChatMessage(Base):
    """Conversation history (user/assistant/system)."""

    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    role: Mapped[str] = mapped_column(String(16), index=True)
    content: Mapped[str] = mapped_column(Text)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )


class UsageRecord(Base):
    """One LLM API call's token usage and cost (for the /usage report)."""

    __tablename__ = "usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
    model: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(16), default="chat")  # chat|proactive|review
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
