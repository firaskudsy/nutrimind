"""APScheduler-driven proactive check-ins, delivered via the Telegram bot.

Runs inside the bot's asyncio loop (started from the Application post_init). Jobs
route through the agent (agents.proactive) and push any resulting message to the
allowlisted user(s).
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram.ext import Application

from agents import proactive
from app.config import get_settings

logger = logging.getLogger(__name__)


async def _send(app: Application, text: str) -> None:
    for uid in get_settings().telegram_allowed_ids:
        try:
            await app.bot.send_message(chat_id=uid, text=text)
        except Exception:  # noqa: BLE001 - one bad target shouldn't kill the job
            logger.exception("Failed to push proactive message to %s", uid)


async def run_weight_prompt(app: Application, user_id: int) -> None:
    msg = await proactive.proactive_message(await proactive.weight_prompt_instruction(), user_id)
    if msg:
        await _send(app, msg)


async def run_meal_check(app: Application, meal: str, user_id: int) -> None:
    msg = await proactive.proactive_message(await proactive.meal_check(meal), user_id)
    if msg:
        await _send(app, msg)


async def run_weekly_review(app: Application, user_id: int) -> None:
    instruction = await proactive.weekly_review_instruction()
    msg = await proactive.proactive_message(instruction, user_id, source="review")
    if msg:
        await _send(app, f"📊 Your weekly review\n\n{msg}")


def setup_scheduler(app: Application, user_id: int) -> AsyncIOScheduler:
    """Create, populate, and start the proactive scheduler (local timezone)."""
    settings = get_settings()
    sched = AsyncIOScheduler()

    if not settings.telegram_allowed_ids:
        logger.warning(
            "Proactive scheduler: no TELEGRAM_ALLOWED_USER_IDS set — nowhere to push. "
            "Set your numeric Telegram ID to enable nudges."
        )
        return sched

    sched.add_job(
        run_weight_prompt,
        CronTrigger(hour=settings.weight_prompt_hour, minute=0),
        args=[app, user_id],
        id="weight_prompt",
    )
    sched.add_job(
        run_meal_check,
        CronTrigger(hour=settings.lunch_check_hour, minute=0),
        args=[app, "lunch", user_id],
        id="lunch_check",
    )
    sched.add_job(
        run_meal_check,
        CronTrigger(hour=settings.dinner_check_hour, minute=30),
        args=[app, "dinner", user_id],
        id="dinner_check",
    )
    sched.add_job(
        run_weekly_review,
        CronTrigger(day_of_week="sun", hour=settings.weekly_review_hour, minute=0),
        args=[app, user_id],
        id="weekly_review",
    )
    sched.start()
    logger.info("Proactive scheduler started with %d jobs.", len(sched.get_jobs()))
    return sched
