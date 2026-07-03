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

from agents import macros, memory, prompts_store
from agents.nutrition_agent import run_turn
from agents.trends import _fetch_weight

NO_NUDGE = "NO_NUDGE"


async def weight_prompt_instruction() -> str:
    return await prompts_store.get_effective("weight_prompt")


async def weekly_review_instruction() -> str:
    return await prompts_store.get_effective("weekly_review")


async def meal_check(meal: str) -> str:
    """Instruction to nudge only if the given meal isn't logged yet today."""
    return await prompts_store.render("meal_check", meal=meal, sentinel=NO_NUDGE)


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


def macro_targets_g(
    weight_kg: float,
    height_cm: float,
    age: int,
    sex: str,
    calorie_target: int | None = None,
) -> dict[str, int]:
    """Reference daily targets (grams) for the dashboard's macro chart.

    Protein reuses /plan's 1g/kg rule (midpoint of its range). Fat is the AMDR
    midpoint (30% of calories, 9 kcal/g) -- Dietary Guidelines for Americans
    puts fat at 20-35% of calories. Carbs take whatever calories are left, so
    the three always sum to the calorie target rather than being independently
    set percentages that could overshoot it. Fiber follows the standard
    14g-per-1000-kcal guideline (IOM / Dietary Guidelines for Americans).
    """
    if calorie_target is None:
        calorie_target = _calorie_tiers(_bmr_kcal(weight_kg, height_cm, age, sex))["moderate_low"]
    protein_lo, protein_hi = _protein_target_g(weight_kg)
    protein = (protein_lo + protein_hi) / 2
    fat = calorie_target * 0.30 / 9
    carbs = max(calorie_target - protein * 4 - fat * 9, 0) / 4
    fiber = calorie_target / 1000 * 14
    return {
        "calories": round(calorie_target),
        "protein": round(protein),
        "carbs": round(carbs),
        "fat": round(fat),
        "fiber": round(fiber),
    }


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

    instruction = await prompts_store.render(
        "plan_instruction",
        weight=weight_native,
        unit=unit,
        as_of=latest_day.isoformat(),
        maintenance=tiers["maintenance"],
        moderate_low=tiers["moderate_low"],
        moderate_high=tiers["moderate_high"],
        aggressive_low=tiers["aggressive_low"],
        aggressive_high=tiers["aggressive_high"],
        protein_lo=protein_lo,
        protein_hi=protein_hi,
        conditions=conditions_text,
        labs=labs_text,
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
    across the day factors in) is left to the model -- but WHICH foods those are
    is resolved here, in Python, via macros.todays_food_log_text(). get_food_log's
    diary entries carry only a numeric foodId, no name, so a model asked to call
    it and then name specific problem items has nothing but a macro profile to
    go on and will confabulate a plausible-sounding food (e.g. calling bulgur
    "rice") rather than admit it doesn't know.
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

    instruction = await prompts_store.render(
        "analyze_instruction",
        target=target_text,
        goals=summary.get("goals") or "none recorded",
        conditions=summary.get("conditions") or "none recorded",
        allergies=summary.get("allergies") or "none recorded",
        food_log=await macros.todays_food_log_text(),
    )
    reply = (await run_turn(instruction, user_id=user_id, source="analyze")).strip()
    return reply or "Sorry -- couldn't analyze today's meals right now. Try again in a moment."
