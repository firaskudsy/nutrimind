"""Application settings, loaded from environment / repo-root .env."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root is two levels up from backend/app/config.py
_REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Core
    database_url: str = "sqlite+aiosqlite:///./nutrimind.db"
    api_bearer_token: str = ""
    log_level: str = "INFO"

    # Auth (Google sign-in + admin approval)
    admin_email: str = ""  # this Google account is auto-approved as admin
    google_client_id: str = ""  # OAuth Web client ID (audience for ID tokens)
    session_secret: str = ""  # HMAC secret for session JWTs (set in prod!)
    session_ttl_hours: int = 720  # 30 days

    # LLM (via LiteLLM). Provider keys are read from the environment by LiteLLM:
    # ANTHROPIC_API_KEY, GEMINI_API_KEY, OPENAI_API_KEY, etc.
    anthropic_api_key: str = ""
    # LiteLLM model string. Switch providers by changing this one value, e.g.:
    #   anthropic/claude-haiku-4-5 | anthropic/claude-sonnet-4-6 | anthropic/claude-opus-4-8
    #   gemini/gemini-2.5-flash-lite | gpt-4o-mini
    agent_model: str = "anthropic/claude-haiku-4-5"

    # MCP servers the agent connects to
    cronometer_mcp_url: str = "http://localhost:8001/mcp"
    google_health_mcp_cmd: str = "npx"
    google_health_mcp_args: str = "-y,google-health-mcp-unofficial@0.5.1"

    # Telegram (Phase 1 chat surface)
    telegram_bot_token: str = ""
    telegram_allowed_user_ids: str = ""

    # Proactive scheduler (24/7 nudges). Times are local (24h). Set enabled=false to disable.
    proactive_enabled: bool = True
    weight_prompt_hour: int = 8
    lunch_check_hour: int = 14
    dinner_check_hour: int = 20
    weekly_review_hour: int = 18  # fires on Sunday

    @property
    def google_health_args_list(self) -> list[str]:
        return [a for a in self.google_health_mcp_args.split(",") if a]

    @property
    def telegram_allowed_ids(self) -> set[int]:
        """Parse the allowlist, skipping any non-numeric entries.

        (A common mistake is pasting the bot @username here instead of your
        numeric Telegram user ID — those are ignored rather than crashing.)
        """
        ids: set[int] = set()
        for x in self.telegram_allowed_user_ids.split(","):
            x = x.strip()
            if x.isdigit():
                ids.add(int(x))
        return ids


@lru_cache
def get_settings() -> Settings:
    return Settings()
