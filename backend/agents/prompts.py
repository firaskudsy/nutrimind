"""System prompt construction for the NutriMind assistant."""

from agents import prompts_store
from db import models


async def build_system_prompt(
    profile: models.UserProfile | None,
    pantry: list[models.PantryItem] | None = None,
) -> str:
    """Assemble the system prompt with the user's profile + pantry (stable → cacheable)."""
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
    if pantry:
        lines = [
            "\n\nAVAILABLE FOODS (at home / can buy) -- this is the user's first source for "
            "meal plans and suggestions. When they ask what to eat, or you're building a "
            "plan, prefer items from this list. If you need to suggest something not on it, "
            "say so explicitly (e.g. \"this isn't on your available list\") so they know it's "
            "not something they said they have on hand. This does not apply retroactively -- "
            "analyzing or logging a food they already ate is not constrained by this list.",
        ]
        for item in pantry:
            line = f"- {item.name}"
            if item.notes:
                line += f" ({item.notes})"
            lines.append(line)
        parts.append("\n".join(lines))
    return "".join(parts)
