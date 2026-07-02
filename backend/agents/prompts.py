"""System prompt construction for the NutriMind assistant."""

from agents import prompts_store
from db import models


async def build_system_prompt(profile: models.UserProfile | None) -> str:
    """Assemble the system prompt with the user's profile (stable → cacheable)."""
    parts = [await prompts_store.get_effective("system_core")]
    if profile is not None:
        lines = ["\n\nUSER PROFILE:"]
        if profile.name:
            lines.append(f"- Name: {profile.name}")
        lines.append(f"- Weight unit: {profile.weight_unit}")
        if profile.age:
            lines.append(f"- Age: {profile.age}")
        if profile.sex:
            lines.append(f"- Sex: {profile.sex}")
        if profile.height_cm:
            lines.append(f"- Height: {profile.height_cm} cm")
        if profile.goals:
            lines.append(f"- Goals: {profile.goals}")
        if profile.targets:
            lines.append(f"- Targets: {profile.targets}")
        if profile.allergies:
            lines.append(f"- Allergies/avoid: {profile.allergies}")
        if profile.conditions:
            lines.append(f"- Health conditions: {profile.conditions}")
        if profile.preferences:
            lines.append(f"- Preferences: {profile.preferences}")
        parts.append("\n".join(lines))
    return "".join(parts)
