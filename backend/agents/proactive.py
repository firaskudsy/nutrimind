"""Proactive check-in prompts, routed through the agent so they use live data.

Each check asks the agent to either produce a short user-facing message or, when
no nudge is warranted, reply with the NO_NUDGE sentinel — which the scheduler
suppresses. This keeps decisions (did I log lunch? is a nudge useful?) with the
model and its Cronometer/Fitbit tools rather than hard-coded parsing.
"""

from agents.nutrition_agent import run_turn

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
