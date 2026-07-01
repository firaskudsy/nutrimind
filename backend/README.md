# NutriMind Backend

FastAPI + Postgres foundation for the health assistant. Owns the source-of-truth DB
(meals, weights, metrics, goals, chat) and the MCP-client wiring; the agent + Telegram
layers plug in on top next.

## Layout

```
app/          FastAPI app, config, auth, schemas
db/           SQLAlchemy async engine + models
mcp_clients/  MCP client registry (cronometer HTTP, google_health stdio)
agents/       Claude Agent SDK agents (next phase)
tests/        smoke tests (SQLite)
```

## Run locally

```bash
cd backend
uv sync
# SQLite (no Postgres needed) — good for a quick start:
DATABASE_URL="sqlite+aiosqlite:///./nutrimind.db" uv run nutrimind-backend
# or with Postgres from docker-compose (uses repo-root .env DATABASE_URL):
uv run nutrimind-backend
```

Then: `curl localhost:8000/health` → reports DB + MCP-server reachability.

## Endpoints (v0)

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/health` | none | liveness + DB + MCP status |
| POST/GET | `/meals` | bearer | create/list meals |
| POST/GET | `/weights` | bearer | log/list weights |
| GET | `/metrics` | bearer | Fitbit/MyAir metric points |
| POST/GET | `/chat` | bearer | persist/list chat history |

Auth: set `API_BEARER_TOKEN` in repo-root `.env`. If empty, auth is disabled (local dev).

## The agent + Telegram bot (Phase 1 usable core)

The assistant runs on **LiteLLM**, so the model/provider is one config string (`AGENT_MODEL`).
It connects to our MCP servers, converts their tools (+ local memory tools) to the universal
OpenAI function-schema format, drives a provider-agnostic tool loop, analyzes meals (text +
**food photos** via vision), and logs to Cronometer.

**Switch models by editing `AGENT_MODEL` in `.env`** (and set the matching provider key):

```
AGENT_MODEL=anthropic/claude-haiku-4-5     # default, cheapest Claude   (ANTHROPIC_API_KEY)
AGENT_MODEL=anthropic/claude-sonnet-4-6    # more reasoning             (ANTHROPIC_API_KEY)
AGENT_MODEL=gemini/gemini-2.5-flash-lite   # very cheap                 (GEMINI_API_KEY)
AGENT_MODEL=gpt-4o-mini                     # cheap                      (OPENAI_API_KEY)
```

- `agents/nutrition_agent.py` — core `run_turn()` (MCP tools + vision + prompt caching)
- `agents/prompts.py` — system prompt (+ user profile, cacheable)
- `agents/cli.py` — terminal REPL to test the brain without Telegram
- `agents/proactive.py` — proactive check-in prompts (routed through the agent)
- `app/scheduler.py` — APScheduler jobs, delivered via the bot
- `app/telegram_bot.py` — Telegram chat surface (allowlisted)

### Proactive scheduler (24/7 nudges)

Starts automatically with the bot (`PROACTIVE_ENABLED=true`, default). Local-time jobs:

| Job | When (default) | What |
|---|---|---|
| Weight prompt | daily 08:00 | asks you to reply with today's weight |
| Lunch check | daily 14:00 | nudges only if no lunch is logged in Cronometer |
| Dinner check | daily 20:30 | nudges only if no dinner is logged |
| Weekly review | Sunday 18:00 | diet + weight + Fitbit sleep/activity summary |

Times are configurable in `.env` (`WEIGHT_PROMPT_HOUR`, `LUNCH_CHECK_HOUR`, `DINNER_CHECK_HOUR`,
`WEEKLY_REVIEW_HOUR`). Nudges push to `TELEGRAM_ALLOWED_USER_IDS`, so that must be set (your
numeric ID). Test the review any time with the **`/review`** command in the bot.

### Prereqs in repo-root `.env`

```
ANTHROPIC_API_KEY=sk-ant-...
CRONOMETER_USERNAME=... / CRONOMETER_PASSWORD=...     # for the Cronometer MCP
# Google Health is optional — the agent skips it if unreachable
```

### Test the brain (CLI) — needs the Cronometer MCP running

In one terminal, start the Cronometer MCP over HTTP:

```bash
cd ../mcp/cronometer
MCP_TRANSPORT=streamable-http PORT=8001 uv run cronometer-mcp
```

In another, talk to the agent:

```bash
cd backend
uv run python -m agents.cli                       # interactive REPL
uv run python -m agents.cli "I'm about to eat 3 eggs and 2 toast at 8am — ok?"
uv run python -m agents.cli --image plate.jpg "is this a good lunch?"
```

Verify it reads your Cronometer diary, advises, and (on agreement) logs the food.

### Telegram bot

1. **Create the bot:** in Telegram, message **@BotFather** → `/newbot` → pick a name and a
   username ending in `bot`. It replies with a **token** like `123456:ABC-...`.
2. **Get your user ID:** message **@userinfobot** (or **@RawDataBot**); note the numeric `id`.
3. Put both in repo-root `.env`:
   ```
   TELEGRAM_BOT_TOKEN=123456:ABC-...
   TELEGRAM_ALLOWED_USER_IDS=<your numeric id>   # comma-separated for more than one
   ```
4. Run it (keep the Cronometer MCP running too):
   ```bash
   uv run python -m app.telegram_bot
   ```
5. Open your bot in Telegram, `/start`, then chat / send meal photos / report weight.

> History is in-memory per chat for now (resets on restart); DB-backed history + proactive
> nudges land next.

## Test

```bash
uv run pytest -q
```
