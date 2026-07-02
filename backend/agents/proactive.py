"""Proactive check-in prompts, routed through the agent so they use live data.

Each check asks the agent to either produce a short user-facing message or, when
no nudge is warranted, reply with the NO_NUDGE sentinel — which the scheduler
suppresses. This keeps decisions (did I log lunch? is a nudge useful?) with the
model and its Cronometer/Fitbit tools rather than hard-coded parsing.

`diet_plan` (the /plan command) follows the same "instruction through run_turn"
pattern, but pre-computes its calorie/protein anchors in Python (Mifflin-St Jeor
+ standard deficit-tier math) rather than trusting the LLM to do that arithmetic
-- these are safety-relevant numbers, so the model is told to use them as given
and layer qualitative, condition-aware judgment (blood markers, injuries) on top.
"""

from datetime import date, timedelta

from agents import memory
from agents.nutrition_agent import run_turn
from agents.trends import _fetch_weight

NO_NUDGE = "NO_NUDGE"

WEIGHT_PROMPT = (
    "It's morning. Send the user one short, friendly line asking them to reply with "
    "today's body weight so you can log it to Cronometer. Output only that message."
)

WEEKLY_REVIEW = (
    "Produce the user's weekly health review. Use Cronometer for the last 7 days of "
    "nutrition (calories/protein consistency) and weight history, and Google Health for "
    "sleep, steps, and activity. Summarize concisely: diet consistency, weight trend, "
    "sleep and activity, then 2-3 specific, encouraging suggestions for next week. "
    "Friendly and tight. If some data is unavailable, work with what you have."
)


def meal_check(meal: str) -> str:
    """Instruction to nudge only if the given meal isn't logged yet today."""
    return (
        f"It's a check-in time. Use get_food_log to read TODAY's Cronometer diary. "
        f"If the user has not logged any {meal} yet today, reply with one short, friendly "
        f"line nudging them to log their {meal} (or tell you what they had). "
        f"If they have already logged {meal}, reply with exactly this and nothing else: "
        f"{NO_NUDGE}"
    )


async def proactive_message(
    instruction: str, user_id: int, source: str = "proactive"
) -> str | None:
    """Run a proactive instruction; return the message to send, or None to suppress."""
    reply = (await run_turn(instruction, user_id=user_id, source=source)).strip()
    if not reply or reply.upper().startswith(NO_NUDGE):
        return None
    return reply


# ------------------------------------------------------------------
# /plan -- personalized calorie/macro framework
# ------------------------------------------------------------------


def _bmr_kcal(weight_kg: float, height_cm: float, age: int, sex: str) -> float:
    """Mifflin-St Jeor BMR -- the modern standard formula, more accurate than Harris-Benedict."""
    base = 10 * weight_kg + 6.25 * height_cm - 5 * age
    return base - 161 if sex.strip().lower().startswith("f") else base + 5


def _calorie_tiers(bmr: float) -> dict[str, int]:
    """Sedentary-anchored maintenance + standard deficit tiers (3,500 kcal/lb rule).

    Sedentary (BMR x 1.2) is used as the maintenance anchor rather than a higher
    activity multiplier -- a safer default than assuming activity the agent can't
    verify, and appropriate given this command is often used by people managing a
    mobility-limiting condition. The agent is told it may note real activity data
    from Google Health as a qualitative caveat without changing these anchors.
    A 1,200 kcal/day floor guards against recommending an unsafe deficit for a
    lighter person.
    """
    maintenance = bmr * 1.2
    return {
        "maintenance": round(maintenance),
        "moderate_low": round(maintenance - 500),
        "moderate_high": round(maintenance - 250),
        "aggressive_low": round(max(maintenance - 750, 1200)),
        "aggressive_high": round(max(maintenance - 500, 1200)),
    }


def _protein_target_g(weight_kg: float) -> tuple[int, int]:
    """~1 g protein per kg body weight, the standard simplified cut-preservation rule.

    The center is clamped to [100, 190] *before* the +-10g band is applied, so the
    low/high bounds stay within [90, 200] AND low <= high always holds -- clamping
    each bound independently (as an earlier version of this did) can invert the
    range for an extreme weight (e.g. produce a 240-200 "range").
    """
    center = min(max(weight_kg * 1.0, 100), 190)
    return round(center - 10), round(center + 10)


async def diet_plan(user_id: int) -> str:
    """Generate the /plan calorie & macro framework from profile + weight + labs.

    Two pieces of load-bearing arithmetic (calorie tiers, protein range) are
    computed here deterministically and handed to the agent as fixed anchors --
    everything qualitative (which tier to recommend, how blood markers and
    physical conditions should shape the framing, the required wellness
    disclaimer) is left to the model, consistent with how the rest of the app
    treats LLM judgment vs. hard numbers.
    """
    profile = await memory.load_profile(user_id)
    summary = memory.profile_summary(profile)
    missing = [
        field
        for field, label in (("age", "age"), ("sex", "sex"), ("height_cm", "height"))
        if not summary.get(field)
    ]
    if missing:
        return (
            "I need a bit more info before I can build your plan: "
            f"{', '.join(missing)}. Tell me and I'll remember it, then run /plan again."
        )

    unit = summary.get("weight_unit") or "lbs"
    today = date.today()
    weights = await _fetch_weight(unit, today - timedelta(days=30), today)
    if not weights:
        return (
            "I don't have a recent weight on file. Log your current weight, "
            "then run /plan again."
        )
    latest_day = max(weights)
    weight_native = weights[latest_day]
    weight_kg = weight_native * 0.45359237 if unit == "lbs" else weight_native

    bmr = _bmr_kcal(weight_kg, summary["height_cm"], summary["age"], summary["sex"])
    tiers = _calorie_tiers(bmr)
    protein_lo, protein_hi = _protein_target_g(weight_kg)

    markers = await memory.latest_health_markers(user_id)
    labs_text = (
        "; ".join(f"{k}: {v['value']} {v['unit'] or ''}".strip() for k, v in markers.items())
        or "none recorded"
    )
    conditions_text = summary.get("conditions") or "none recorded"

    instruction = (
        "Produce the user's personalized weight-loss/diet plan as calorie and protein "
        "targets. Use EXACTLY these precomputed numbers -- do not recompute or alter them:\n"
        f"- Current weight: {weight_native} {unit} (as of {latest_day.isoformat()})\n"
        f"- Maintenance: ~{tiers['maintenance']} calories/day\n"
        f"- Moderate loss (0.5-1 lb/week): ~{tiers['moderate_low']}-{tiers['moderate_high']} "
        "calories/day\n"
        "- Aggressive loss (1-1.5 lbs/week, max safe deficit): "
        f"~{tiers['aggressive_low']}-{tiers['aggressive_high']} calories/day\n"
        f"- Protein target: {protein_lo}-{protein_hi}g daily\n\n"
        f"Health conditions on file: {conditions_text}\n"
        f"Recent lab/blood-test values on file: {labs_text}\n\n"
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
    reply = (await run_turn(instruction, user_id=user_id, source="plan")).strip()
    return reply or "Sorry -- couldn't build your plan this time. Try again in a moment."


# ------------------------------------------------------------------
# /analyze -- rate today's eating against conditions/goals/targets
# ------------------------------------------------------------------


async def analyze_day(user_id: int) -> str:
    """Generate the /analyze command's rating of today's logged meals.

    Reuses /plan's calorie/protein anchor as the target to rate against when the
    user hasn't set an explicit one (same BMR + weight math, moderate-deficit
    tier) -- otherwise this command would have nothing concrete to score against.
    Everything else (which items hurt the score, alternatives, how meal timing
    across the day factors in) is left to the model, which pulls today's actual
    diary via get_food_log rather than trusting anything precomputed here.
    """
    profile = await memory.load_profile(user_id)
    summary = memory.profile_summary(profile)

    targets = summary.get("targets") or {}
    calorie_target = targets.get("calories")
    protein_target = targets.get("protein_g")

    if calorie_target is None and all(summary.get(f) for f in ("age", "sex", "height_cm")):
        unit = summary.get("weight_unit") or "lbs"
        today = date.today()
        weights = await _fetch_weight(unit, today - timedelta(days=30), today)
        if weights:
            weight_native = weights[max(weights)]
            weight_kg = weight_native * 0.45359237 if unit == "lbs" else weight_native
            bmr = _bmr_kcal(weight_kg, summary["height_cm"], summary["age"], summary["sex"])
            calorie_target = _calorie_tiers(bmr)["moderate_low"]
            if protein_target is None:
                protein_target = _protein_target_g(weight_kg)[0]

    target_text = f"~{calorie_target} kcal" if calorie_target else "none on file"
    if protein_target:
        target_text += f", ~{protein_target}g protein"

    instruction = (
        "Analyze what the user has eaten TODAY. Call get_food_log once for today's "
        "Cronometer diary (foods, amounts, meal groups, energy_summary, nutrition_summary) "
        "-- use its real data, don't guess.\n\n"
        f"Calorie/protein target: {target_text}\n"
        f"Weight-loss goal: {summary.get('goals') or 'none recorded'}\n"
        f"Health conditions: {summary.get('conditions') or 'none recorded'}\n"
        f"Allergies/avoid: {summary.get('allergies') or 'none recorded'}\n\n"
        "If nothing is logged yet today, say so plainly and stop -- don't invent a score. "
        "Otherwise reply in plain text (no markdown):\n"
        "1. A score out of 10 for today's eating so far, weighing the calorie/protein "
        "target, the weight-loss goal, and the health conditions/allergies above -- also "
        "weigh how meals are spaced across the day (long gaps, everything back-loaded "
        "late at night, a skipped meal), not just the totals.\n"
        "2. The specific items that hurt the score, each with a one-line reason (over "
        "target, conflicts with a condition or allergy, poor timing, etc).\n"
        "3. One concrete swap/alternative for each flagged item.\n"
        "4. A one-line total: calories/protein consumed vs. target, and calories "
        "remaining.\n"
        "End with the standard wellness disclaimer: general guidance, not medical advice."
    )
    reply = (await run_turn(instruction, user_id=user_id, source="analyze")).strip()
    return reply or "Sorry -- couldn't analyze today's meals right now. Try again in a moment."
