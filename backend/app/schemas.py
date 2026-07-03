"""Pydantic request/response models for the API."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- Meals ----
class MealCreate(BaseModel):
    description: str
    planned_time: datetime | None = None
    meal_group: str | None = None
    photo_path: str | None = None


class MealOut(ORMModel):
    id: int
    created_at: datetime
    planned_time: datetime | None
    description: str
    photo_path: str | None
    meal_group: str | None
    status: str
    advice: str | None
    nutrition: dict
    cronometer_logged: bool


# ---- Weights ----
class WeightCreate(BaseModel):
    value: float
    unit: str = "lbs"
    day: date | None = None
    source: str = "user"


class WeightOut(ORMModel):
    id: int
    day: date
    value: float
    unit: str
    source: str
    created_at: datetime


# ---- Metrics ----
class MetricOut(ORMModel):
    id: int
    day: date
    source: str
    type: str
    value: float | None
    unit: str | None
    meta: dict
    created_at: datetime


# ---- Profile / memory ----
class ProfileUpdate(BaseModel):
    name: str | None = None
    weight_unit: str | None = None
    age: int | None = None
    sex: str | None = None
    height_cm: float | None = None
    goals: str | None = None
    allergies: str | None = None
    conditions: str | None = None
    preferences: str | None = None
    daily_calorie_target: int | None = None
    daily_protein_target_g: int | None = None


# ---- Pantry (available-at-home foods) ----
class PantryItemCreate(BaseModel):
    name: str
    notes: str | None = None


class PantryItemUpdate(BaseModel):
    name: str | None = None
    notes: str | None = None


class PantryItemOut(ORMModel):
    id: int
    name: str
    notes: str | None
    created_at: datetime


# ---- Chat ----
class ChatMessageIn(BaseModel):
    content: str


class ChatMessageOut(ORMModel):
    id: int
    role: str
    content: str
    meta: dict
    created_at: datetime


# ---- Health / status ----
class HealthOut(BaseModel):
    status: str
    db: bool
    mcp: dict[str, bool]


# ---- Web app ----
class LoginIn(BaseModel):
    password: str


class GoogleLoginIn(BaseModel):
    credential: str  # Google ID token from the Sign-In button


class LoginOut(BaseModel):
    token: str
    user: dict


class WebChatIn(BaseModel):
    message: str = ""
    image_b64: str | None = None
    image_media_type: str = "image/jpeg"


class WebChatOut(BaseModel):
    reply: str
    image_b64: str | None = None
    elapsed_seconds: float | None = None


class SettingsUpdate(BaseModel):
    values: dict[str, str]


class PromptsUpdate(BaseModel):
    values: dict[str, str]
