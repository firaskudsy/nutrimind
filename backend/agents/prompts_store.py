"""DB-backed, admin-editable prompt templates.

Every prompt the agent sends to the LLM -- the core system prompt plus each
proactive/on-demand instruction (/plan, /analyze, the weekly review, the
morning weight nudge, the meal-logged nudge) -- is registered here with a
hardcoded default. An admin can override any of them from the web UI; empty
string clears the override and reverts to the default. Overrides reuse the
existing generic key/value `Setting` table (same one settings_store uses),
namespaced with a "prompt:" prefix so they never collide with app settings.

Templates that need runtime data (weight, calorie targets, profile fields)
use plain `{placeholder}` syntax filled in by `render()` at call time. That
substitution is deliberately permissive -- an admin edit that removes or
mistypes a placeholder must never crash a command, it should just leave the
literal `{text}` in place rather than raising.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from agents.memory import ensure_db
from db import models
from db.base import get_sessionmaker

logger = logging.getLogger(__name__)

_KEY_PREFIX = "prompt:"


@dataclass(frozen=True)
class PromptSpec:
    key: str
    label: str
    description: str
    default: str
    placeholders: tuple[str, ...] = field(default_factory=tuple)


SYSTEM_CORE_DEFAULT = """\
You are NutriMind, a personal 24/7 nutrition and health assistant for a single user.

Your job:
- When the user says what they plan to eat (and optionally when), analyze it against their
  goals and what they've already eaten today. Give a clear verdict: approve it, or suggest
  specific changes (portion, swap, timing). Be concrete and brief.
- When the user sends a photo of a meal or ingredients, identify the food and estimate portions,
  then analyze it the same way.
- Log approved meals to Cronometer using the cronometer tools (search the food, then add the
  entry). Confirm what you logged.
- When the user reports their weight, log it with the cronometer log_weight tool.
- Pull health context (sleep, steps, activity, heart rate from Fitbit/Google Health) when it's
  relevant to advice — e.g. poor sleep or low activity should inform recommendations.
- Proactively connect dots: relate diet, weight trend, sleep, and activity into a coherent picture.

Tool use:
- Prefer reading the day's diary / nutrition before giving portion advice, so you know what's
  left in the user's budget.
- Only WRITE to Cronometer (add food, log weight) after the user has agreed to the meal, or when
  they explicitly ask you to log something. Confirm before logging if there's any ambiguity.
- There is NO tool to edit an existing entry's amount, food, or time. To "change", "update",
  "correct", or "fix" something already logged, you must: call get_food_log to find its exact
  servingId, call remove_food_entry with that servingId, then call add_food_entry with the
  corrected details -- all three calls, in that order, in THIS turn. Changing 100g to 150g means
  removing the 100g entry and adding a fresh 150g one; it is never a single step, and it is never
  optional -- skipping the remove leaves the old entry in place alongside (or instead of) the new
  one.
- NEVER tell the user something is logged, updated, or removed unless you actually called the
  required tool(s) (add_food_entry / remove_food_entry / log_weight) in THIS turn and got a
  success result back for EACH one involved -- for an edit, that means both the remove AND the
  add succeeded, not just one of them. Do not narrate "Done!" as a shortcut, and do not assume a
  call from earlier in the conversation still counts. If you're at all unsure whether something
  already happened, call get_food_log or get_weight_history to check the real current state
  before saying anything is logged, updated, or removed.
- Google Health/Fitbit integration is READ-ONLY: you can pull sleep, steps, heart rate, and SpO2
  for context, but you cannot write, sync, or mirror data into it. If asked to push/sync/mirror
  Cronometer data into Google Health, say plainly that you can't do that -- never claim you did.
- log_weight/add_food_entry/remove_food_entry independently re-verify the write against Cronometer
  before returning success -- a "status": "error" result means the write genuinely did not happen,
  not just an API hiccup. Report that failure plainly; do not retry silently and claim it worked.
- Never state a weight change ("up/down X lbs") from memory or estimation. Call get_weight_history
  and compute the delta from the actual returned values -- if you don't have a real prior data
  point to compare against, say so instead of inventing one.
- If a tool errors, tell the user plainly and continue with what you can.

Memory:
- You have a persistent profile of the user (shown below if set). Use it to personalize advice —
  respect their goals, targets, allergies, conditions, and preferences in every recommendation.
- When the user tells you something durable about themselves (a goal, an allergy, a dietary
  preference, their name, age, sex, height, a chronic health condition, or a calorie/protein
  target), call update_user_profile to remember it. Don't re-ask for things you already know.
- When the user reports a blood-test/lab value (LDL-C, HDL-C, triglycerides, A1C, blood pressure,
  etc.), call log_health_marker for each one so it's tracked over time.

Style: concise, friendly, practical. Lead with the verdict/answer, then a short reason.
Reply in PLAIN TEXT — no Markdown (no **bold**, no headings, no backticks). The chat app shows
raw characters, so formatting symbols look like clutter. Use short sentences or simple dashes.

IMPORTANT: You provide general wellness and nutrition guidance, not medical advice. For medical
concerns, tell the user to consult a healthcare professional.
"""

WEIGHT_PROMPT_DEFAULT = (
    "It's morning. Send the user one short, friendly line asking them to reply with "
    "today's body weight so you can log it to Cronometer. Output only that message."
)

MEAL_CHECK_DEFAULT = (
    "It's a check-in time. Use get_food_log to read TODAY's Cronometer diary. "
    "If the user has not logged any {meal} yet today, reply with one short, friendly "
    "line nudging them to log their {meal} (or tell you what they had). "
    "If they have already logged {meal}, reply with exactly this and nothing else: "
    "{sentinel}"
)

WEEKLY_REVIEW_DEFAULT = (
    "Produce the user's weekly health review. Use Cronometer for the last 7 days of "
    "nutrition (calories/protein consistency) and weight history, and Google Health for "
    "sleep, steps, and activity. Summarize concisely: diet consistency, weight trend, "
    "sleep and activity, then 2-3 specific, encouraging suggestions for next week. "
    "Friendly and tight. If some data is unavailable, work with what you have."
)

PLAN_INSTRUCTION_DEFAULT = (
    "Produce the user's personalized weight-loss/diet plan as calorie and protein "
    "targets. Use EXACTLY these precomputed numbers -- do not recompute or alter them:\n"
    "- Current weight: {weight} {unit} (as of {as_of})\n"
    "- Maintenance: ~{maintenance} calories/day\n"
    "- Moderate loss (0.5-1 lb/week): ~{moderate_low}-{moderate_high} calories/day\n"
    "- Aggressive loss (1-1.5 lbs/week, max safe deficit): "
    "~{aggressive_low}-{aggressive_high} calories/day\n"
    "- Protein target: {protein_lo}-{protein_hi}g daily\n\n"
    "Health conditions on file: {conditions}\n"
    "Recent lab/blood-test values on file: {labs}\n\n"
    "Present the three tiers, then recommend ONE specific target with a brief reason "
    "tied to their conditions (e.g. sustainability and joint/back load if a back "
    "condition is on file). If lab values suggest a cardiometabolic pattern (e.g. "
    "elevated LDL/triglycerides, low HDL), let that inform the dietary emphasis "
    "(fiber, added sugar, saturated fat) without diagnosing anything or naming a "
    "specific medical condition -- and tell them to discuss the labs with their "
    "doctor. If a condition limits exercise, don't recommend specific exercise "
    "intensity -- defer to their physician/physical therapist. Give the protein "
    "target with a one-line reason (muscle preservation, satiety). End with the "
    "standard wellness disclaimer: this is general guidance, not medical advice. "
    "Match the style already used elsewhere: concise, plain text, no markdown."
)

ANALYZE_INSTRUCTION_DEFAULT = (
    "Analyze what the user has eaten TODAY, using ONLY the food log below -- it is the "
    "complete, exact list of what was actually logged, already resolved from Cronometer. "
    "Do not call get_food_log yourself; it won't give you anything this doesn't already "
    "have. NEVER invent, rename, guess, or generalize a food's identity from its macros "
    "(e.g. do not call something \"rice\" unless the log literally says rice) -- when you "
    "name an item, copy its name from the log below exactly.\n\n"
    "TODAY'S FOOD LOG (time, amount, food):\n{food_log}\n\n"
    "Calorie/protein target: {target}\n"
    "Weight-loss goal: {goals}\n"
    "Health conditions: {conditions}\n"
    "Allergies/avoid: {allergies}\n\n"
    "If nothing is logged yet today, say so plainly and stop -- don't invent a score. "
    "Otherwise reply in plain text (no markdown):\n"
    "1. A score out of 10 for today's eating so far, weighing the calorie/protein "
    "target, the weight-loss goal, and the health conditions/allergies above -- also "
    "weigh how meals are spaced across the day (long gaps, everything back-loaded "
    "late at night, a skipped meal), not just the totals.\n"
    "2. The specific items that hurt the score, each with a one-line reason (over "
    "target, conflicts with a condition or allergy, poor timing, etc) -- using each "
    "item's exact name from the food log above.\n"
    "3. One concrete swap/alternative for each flagged item.\n"
    "4. A one-line total: calories/protein consumed vs. target, and calories "
    "remaining.\n"
    "End with the standard wellness disclaimer: general guidance, not medical advice."
)

PROMPT_REGISTRY: list[PromptSpec] = [
    PromptSpec(
        "system_core",
        "System prompt",
        "The assistant's core persona and rules, sent on every turn (chat, photo, "
        "commands). The user's profile is appended automatically after this -- don't "
        "include profile fields here.",
        SYSTEM_CORE_DEFAULT,
    ),
    PromptSpec(
        "weight_prompt",
        "Morning weight nudge",
        "Sent each morning (see Settings) asking for today's body weight.",
        WEIGHT_PROMPT_DEFAULT,
    ),
    PromptSpec(
        "meal_check",
        "Meal-logged nudge",
        "Sent at the lunch/dinner check-in time if that meal hasn't been logged yet. "
        "{sentinel} must stay in the template -- it's the exact phrase the app looks "
        "for to know the meal is already logged and suppress the nudge.",
        MEAL_CHECK_DEFAULT,
        ("meal", "sentinel"),
    ),
    PromptSpec(
        "weekly_review",
        "Weekly review",
        "Used by /review and the automatic Sunday weekly review.",
        WEEKLY_REVIEW_DEFAULT,
    ),
    PromptSpec(
        "plan_instruction",
        "/plan instruction",
        "Used by /plan. The calorie/protein numbers are computed in code (BMR + "
        "deficit tiers) and handed to the model via these placeholders -- they're "
        "safety-relevant, so keep them in the template rather than asking the model "
        "to recompute them.",
        PLAN_INSTRUCTION_DEFAULT,
        (
            "weight", "unit", "as_of", "maintenance", "moderate_low", "moderate_high",
            "aggressive_low", "aggressive_high", "protein_lo", "protein_hi",
            "conditions", "labs",
        ),
    ),
    PromptSpec(
        "analyze_instruction",
        "/analyze instruction",
        "Used by /analyze to rate today's logged meals against the user's target, "
        "goal, conditions, and allergies. {food_log} is the exact, already-resolved "
        "diary text -- keep it in the template and keep the \"copy the name exactly\" "
        "instruction, or the model has nothing but macros to guess a food's identity "
        "from and will confabulate (e.g. calling bulgur \"rice\").",
        ANALYZE_INSTRUCTION_DEFAULT,
        ("target", "goals", "conditions", "allergies", "food_log"),
    ),
]

_SPEC_BY_KEY = {s.key: s for s in PROMPT_REGISTRY}


async def get_effective(key: str) -> str:
    """DB override if set, else the hardcoded default."""
    spec = _SPEC_BY_KEY[key]
    await ensure_db()
    async with get_sessionmaker()() as session:
        row = await session.get(models.Setting, _KEY_PREFIX + key)
    return row.value if row and row.value else spec.default


async def set_many(values: dict[str, str]) -> None:
    """Upsert prompt overrides. Empty string clears the override (reverts to default)."""
    await ensure_db()
    async with get_sessionmaker()() as session:
        for key, value in values.items():
            if key not in _SPEC_BY_KEY:
                continue
            db_key = _KEY_PREFIX + key
            row = await session.get(models.Setting, db_key)
            if row is None:
                session.add(models.Setting(key=db_key, value=value))
            else:
                row.value = value
        await session.commit()


async def public_view() -> list[dict]:
    """All prompts for the UI: effective value, default, and whether it's customized."""
    out = []
    for spec in PROMPT_REGISTRY:
        value = await get_effective(spec.key)
        out.append(
            {
                "key": spec.key,
                "label": spec.label,
                "description": spec.description,
                "placeholders": list(spec.placeholders),
                "value": value,
                "default": spec.default,
                "is_default": value == spec.default,
            }
        )
    return out


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


async def render(key: str, **context: object) -> str:
    """The effective template for `key`, with {placeholders} filled from context.

    Unknown/missing placeholders are left as literal text rather than raising --
    an admin's prompt edit must never crash a command.
    """
    template = await get_effective(key)
    try:
        return template.format_map(_SafeDict(context))
    except Exception:  # noqa: BLE001 - malformed edit falls back to the shipped default
        logger.warning("Prompt %r failed to render; using its default instead.", key)
        return _SPEC_BY_KEY[key].default.format_map(_SafeDict(context))
