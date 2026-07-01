"""Telegram bot — the Phase-1 chat surface for NutriMind.

Text and food-photo messages are routed to the nutrition agent. Access is
restricted to an allowlist of Telegram user IDs. Conversation history is kept
in-memory per chat (persisted history lands with the DB-backed chat store).

Run:  uv run python -m app.telegram_bot
Needs TELEGRAM_BOT_TOKEN, TELEGRAM_ALLOWED_USER_IDS, ANTHROPIC_API_KEY in .env.
"""

import logging

from dotenv import find_dotenv, load_dotenv
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from agents import memory, proactive, usage
from agents.nutrition_agent import ImageInput, run_turn
from app.config import get_settings
from app.scheduler import setup_scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_MAX_TURNS = 20  # messages loaded as context per turn = _MAX_TURNS * 2


def _allowed(update: Update) -> bool:
    """Fail-closed: only allowlisted user IDs may use the LLM/data commands.

    An empty allowlist denies everyone (see _setup_mode for the first-run path).
    """
    allow = get_settings().telegram_allowed_ids
    user = update.effective_user
    return user is not None and user.id in allow


def _setup_mode() -> bool:
    """True when no allowlist is configured yet — first-run setup."""
    return not get_settings().telegram_allowed_ids


async def whoami(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply with the sender's numeric Telegram user ID (for the allowlist)."""
    user = update.effective_user
    if user is None or update.message is None:
        return
    await update.message.reply_text(
        f"Your Telegram user ID is: {user.id}\n"
        f"Put this in .env as TELEGRAM_ALLOWED_USER_IDS={user.id} and restart the bot."
    )


HELP_TEXT = (
    "I'm NutriMind — your nutrition & health assistant. You can:\n\n"
    "• Tell me what you plan to eat (and when) — I'll analyze it and log it to Cronometer\n"
    "• Send a photo of a meal or a nutrition label — I'll identify and log it\n"
    "• Report your weight — I'll log it\n"
    "• Ask about today's calories/nutrition, your weight trend, or your Fitbit sleep/steps\n"
    "• Tell me your goals, allergies, and preferences — I'll remember them\n\n"
    "Commands:\n"
    "/review — weekly review (diet + weight + Fitbit)\n"
    "/usage — token usage & cost (today / 7d / 30d)\n"
    "/whoami — your Telegram user ID\n"
    "/help — this message\n\n"
    "Wellness guidance, not medical advice."
)


async def help_cmd(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    # Info-only — safe without the allowlist so first-run setup works.
    if update.message is None:
        return
    await update.message.reply_text(HELP_TEXT)


async def start(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    # Info-only entry point (shows your ID for setup) — not gated.
    if update.message is None:
        return
    uid = update.effective_user.id if update.effective_user else "?"
    await update.message.reply_text(
        "Hi — I'm NutriMind. Tell me what you're planning to eat (and when), send a "
        "photo of a meal, or report your weight, and I'll analyze it and log it to "
        f"Cronometer.\n\n(Your Telegram user ID is {uid} — set TELEGRAM_ALLOWED_USER_IDS "
        "to it in .env to lock the bot to just you.)\n\nWellness guidance, not medical advice."
    )


def _fmt_period(label: str, d: dict) -> str:
    return (
        f"{label}: {d['calls']} calls · {d['total']:,} tokens "
        f"(in {d['prompt']:,} / out {d['completion']:,}) · ${d['cost']:.4f}"
    )


async def usage_cmd(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Token usage + cost for today, last 7 days, last 30 days."""
    if not _allowed(update) or update.message is None:
        return
    data = await usage.usage_summary()
    text = (
        "📊 Usage & cost\n\n"
        f"{_fmt_period('Today', data['today'])}\n"
        f"{_fmt_period('Last 7 days', data['week'])}\n"
        f"{_fmt_period('Last 30 days', data['month'])}\n\n"
        f"Model: {get_settings().agent_model}"
    )
    await update.message.reply_text(text)


async def review(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """On-demand weekly review (also runs automatically on Sundays)."""
    if not _allowed(update) or update.message is None:
        return
    await update.message.reply_text("Pulling your data for a review — one moment...")
    try:
        msg = await proactive.proactive_message(proactive.WEEKLY_REVIEW, source="review")
    except Exception as exc:  # noqa: BLE001
        logger.exception("weekly review failed")
        await update.message.reply_text(f"Sorry — review failed: {exc}")
        return
    await update.message.reply_text(msg or "Not enough data yet for a review.")


async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    if not _allowed(update):
        # In first-run setup, help the owner enable themselves; otherwise stay silent
        # (don't engage unknown users or leak that the bot is active).
        if _setup_mode() and update.effective_user:
            await update.message.reply_text(
                f"You're not on the allowlist yet. Your Telegram ID is "
                f"{update.effective_user.id} — add it to TELEGRAM_ALLOWED_USER_IDS "
                "in .env and restart to enable me."
            )
        return
    chat_id = update.effective_chat.id
    await ctx.bot.send_chat_action(chat_id, ChatAction.TYPING)

    image: ImageInput | None = None
    if update.message.photo:
        photo = update.message.photo[-1]  # largest size
        tg_file = await ctx.bot.get_file(photo.file_id)
        data = bytes(await tg_file.download_as_bytearray())
        image = ImageInput(data=data, media_type="image/jpeg")
    text = update.message.caption or update.message.text or ""

    hist = await memory.recent_history(limit=_MAX_TURNS * 2)
    try:
        reply = (await run_turn(text, image=image, history=hist)).strip()
    except Exception as exc:  # noqa: BLE001 - surface failures to the user
        logger.exception("agent turn failed")
        await update.message.reply_text(f"Sorry — something went wrong: {exc}")
        return

    await memory.save_message("user", text or "(photo)")
    if reply:
        await memory.save_message("assistant", reply)
    # Never send an empty message (Telegram rejects it).
    await update.message.reply_text(reply or "Hmm, I didn't get a reply — mind rephrasing?")


async def _post_init(app: Application) -> None:
    """Initialize the DB and start the proactive scheduler in the bot's loop."""
    await memory.ensure_db()
    if get_settings().proactive_enabled:
        app.bot_data["scheduler"] = setup_scheduler(app)


def build_application() -> Application:
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")
    app = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .post_init(_post_init)
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("whoami", whoami))
    app.add_handler(CommandHandler("review", review))
    app.add_handler(CommandHandler("usage", usage_cmd))
    app.add_handler(
        MessageHandler((filters.TEXT | filters.PHOTO) & ~filters.COMMAND, on_message)
    )
    return app


def main() -> None:
    load_dotenv(find_dotenv(usecwd=True), override=False)
    app = build_application()
    logger.info("NutriMind Telegram bot starting (polling)...")
    app.run_polling()


if __name__ == "__main__":
    main()
