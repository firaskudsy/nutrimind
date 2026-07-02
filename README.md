# NutriMind

[![CI](https://github.com/firaskudsy/nutrimind/actions/workflows/ci.yml/badge.svg)](https://github.com/firaskudsy/nutrimind/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

**A self-hosted, AI-powered 24/7 nutrition & health assistant you chat with on Telegram or a web app.**

Tell it what you're eating (in text or a photo) and it analyzes the meal against your goals,
logs it to your **Cronometer** account, tracks your **weight**, and pulls your **Fitbit** sleep,
steps, and activity for a full picture. It remembers your goals, allergies, and preferences,
proactively nudges you (missed meals, morning weigh-in, a Sunday weekly review), and reports its
own token usage and cost. Any LLM works — Claude, Gemini, or GPT — swappable with one config line
via **LiteLLM**, over a clean **multi-MCP** tool architecture. Use it from **Telegram** or the
built-in **web app**, and share it with **family** — members sign in with Google and you approve
them.

> ⚕️ Wellness guidance, not medical advice.

---

## Demo

<!-- Add your Telegram screenshots/GIF to docs/screenshots/ and reference them below.
     e.g. ![Logging a meal](docs/screenshots/log-meal.png) -->

_Screenshots coming soon — chatting, logging a meal from a photo, the weekly review, and `/usage`._

---

## Features

- 💬 **Chat on Telegram or the web app** — text or **food/label photos** (vision)
- 📱 **Web dashboard** — chat, weight/macro/cost charts, and settings, with a light/dark theme
- 👨‍👩‍👧 **Multi-user / family** — members sign in with **Google**; the admin approves access
- 🍽️ **Meal analysis + logging to Cronometer** — with the correct date & time you state
- ⚖️ **Weight tracking** — logged to Cronometer
- 😴 **Fitbit / Google Health** — sleep, steps, activity, heart rate feed the advice
- 🧠 **Memory** — remembers goals, allergies, targets, preferences (persists across restarts)
- ⏰ **Proactive 24/7 nudges** — weigh-in prompt, missed-meal checks, weekly review
- 📈 **`/trends`** — an image of weight, calorie & sleep charts for the last week / month
- 📊 **`/usage`** — tokens & cost for today / 7 days / 30 days
- 🔀 **Any LLM** via LiteLLM — `AGENT_MODEL=anthropic/claude-haiku-4-5` (or Gemini / GPT)
- 🐳 **One-command Docker** deployment

## Architecture

```
Telegram  ─►  Bot ───┐
                     ├─► LiteLLM agent + scheduler ─► MCP servers ─► Cronometer (mobile API)
Web app  ─► Backend ─┘         │                                   └► Google Health (Fitbit)
(nginx :3000)  (FastAPI :8000) └► Postgres (users, profile, chat, usage)
```

Runs as five services via Docker Compose: **Postgres**, the **Cronometer MCP**, the **bot**
(Telegram + proactive scheduler), the **backend** (FastAPI, serves `/api` on :8000), and the
**web** app (nginx on :3000, proxies `/api` to the backend). Bot and backend share the same DB
and agent. Layout: `backend/` (agent, tools, db, auth), `mcp/` (`cronometer`, `google_health`,
`myair`), `web/` (React dashboard), `app/` (Flutter app — planned Phase 2).

---

## Prerequisites

- **Docker** (Docker Desktop or engine + compose), or Python 3.11+ with [uv](https://docs.astral.sh/uv/) for local dev
- A **Cronometer** account (free tier works)
- An **LLM provider API key** — [Anthropic](https://console.anthropic.com) (recommended) / Google Gemini / OpenAI
- A **Telegram** account
- *(optional)* A **Fitbit or Pixel Watch** linked to a Google account, for sleep/activity data

---

## Setup

```bash
cp .env.example .env      # then fill in the values below
```

### 1. LLM provider key

Get an API key from your provider and set it in `.env`, plus which model to use:

```ini
ANTHROPIC_API_KEY=sk-ant-...
AGENT_MODEL=anthropic/claude-haiku-4-5   # cheap + reliable. Or: gemini/gemini-2.5-flash-lite, gpt-4o-mini
```

> Small models (e.g. Gemini Flash-Lite) are cheaper but weaker at multi-tool reasoning; Claude
> Haiku 4.5 is the recommended default for reliable tool use at low cost.

### 2. Cronometer

Your login (used by the unofficial mobile API — see [Notes](#notes--limitations)):

```ini
CRONOMETER_USERNAME=you@example.com
CRONOMETER_PASSWORD=your-password
```

### 3. Create & integrate the Telegram bot

1. In Telegram, open a chat with **[@BotFather](https://t.me/BotFather)**.
2. Send **`/newbot`**. Choose a **display name** (e.g. `NutriMind`) and a **username** that must
   end in `bot` (e.g. `my_nutrimind_bot`).
3. BotFather replies with an **HTTP API token** like `123456789:AAExxxx...`. Copy it into `.env`:
   ```ini
   TELEGRAM_BOT_TOKEN=123456789:AAExxxx...
   ```
4. **Get your numeric user ID** (the bot is locked to just you). Two ways:
   - Start the bot (below), open it in Telegram, and send **`/whoami`** — it replies with your ID; **or**
   - Message **[@userinfobot](https://t.me/userinfobot)**, which replies with your `Id`.
5. Put that number in `.env` (comma-separated for multiple people):
   ```ini
   TELEGRAM_ALLOWED_USER_IDS=123456789
   ```
   > 🔒 The bot is **fail-closed**: until a valid numeric ID is set here, it responds to no one
   > (except `/whoami` and `/help`, so you can complete setup). This stops strangers from using
   > your bot and your accounts.
6. *(Optional)* In BotFather, `/setcommands` for your bot and paste:
   ```
   help - What I can do
   trends - Weight, calories & sleep charts
   review - Weekly health review
   usage - Token usage & cost
   whoami - Your Telegram ID
   ```

### 4. Google Health API (Fitbit / Pixel) — optional but recommended

This gives the assistant your sleep, steps, activity, and heart rate. It uses the official
**Google Health API v4** (the successor to the Fitbit Web API). Requires Node.js if you run the
one-time auth on your host (the Docker image already has it).

**a. Create a Google Cloud project & enable the API**
1. Go to the [Google Cloud Console](https://console.cloud.google.com/) → create or select a project.
2. **APIs & Services → Library** → search **“Google Health API”** → **Enable**.

**b. Configure the OAuth consent screen**
3. **APIs & Services → OAuth consent screen** → User type **External** → fill the basics.
4. Publishing status **Testing** is fine for personal use. Under **Test users**, **add your own
   Google account** (the one linked to your Fitbit). No app verification is needed for testing.

**c. Create the OAuth client & set the redirect URI**
5. **APIs & Services → Credentials → Create credentials → OAuth client ID**.
6. Application type: **Web application**.
7. Under **Authorized redirect URIs**, click **Add URI** and enter **exactly**:
   ```
   http://127.0.0.1:3000/callback
   ```
8. **Create**, then copy the **Client ID** and **Client secret**.

**d. Authenticate the connector (one time, on your host)**
9. Make sure a **Fitbit or Pixel Watch is linked** to that Google account.
10. Run the connector setup — it stores tokens in `~/.google-health-mcp` (which Docker mounts):
    ```bash
    cd mcp/google_health
    ./run.sh setup     # paste the Client ID & Client secret when prompted
    ./run.sh auth      # opens a browser → approve the read-only scopes
    ./run.sh doctor    # should print "Status: READY ✓"
    ```
11. *(reference)* mirror the same values into `.env` if you like:
    ```ini
    GOOGLE_HEALTH_CLIENT_ID=...
    GOOGLE_HEALTH_CLIENT_SECRET=...
    GOOGLE_HEALTH_REDIRECT_URI=http://127.0.0.1:3000/callback
    ```

> If you skip this, the assistant simply runs without Fitbit data (it degrades gracefully).

### 5. Web app sign-in (owner + family)

The web app has two ways in: an **owner password** (you, the admin) and **Google sign-in** (family
members, who you then approve).

**a. Owner password + session secret** — always required for the web app:

```ini
API_BEARER_TOKEN=a-long-random-password   # the "Sign in as owner" password (also the API token)
SESSION_SECRET=another-long-random-string # signs login sessions — set a real random value in prod
```

**b. Google sign-in for family** — optional; enables the "Continue with Google" button:

1. In the [Google Cloud Console](https://console.cloud.google.com/) → **APIs & Services →
   Credentials → Create credentials → OAuth client ID** → Application type **Web application**.
   (You can reuse the same project as Google Health; it must still be its own Web client.)
2. Under **Authorized JavaScript origins**, add the exact origin(s) you open the app from —
   e.g. `http://localhost:3000` (and any LAN IP or real domain). No redirect URI is needed for
   this browser sign-in flow.
3. **Create**, copy the **Client ID**, and set it plus your admin email in `.env`:
   ```ini
   ADMIN_EMAIL=you@gmail.com    # this Google account is auto-approved as the admin
   GOOGLE_CLIENT_ID=xxxx.apps.googleusercontent.com
   ```
4. While the **OAuth consent screen** is in **Testing**, add each family member's Google email
   under **Test users** — otherwise Google blocks their sign-in before they ever reach the app.

**How family access works:** a member opens the app, clicks **Continue with Google**, and lands on
a "waiting for approval" screen. You sign in (owner password or your `ADMIN_EMAIL` Google account),
open **Members**, and **Approve** them. Everyone's meals, chat, and usage are scoped to their own
account.

> `GOOGLE_CLIENT_ID` (browser sign-in) is **separate** from `GOOGLE_HEALTH_CLIENT_ID` (the Fitbit
> connector) — different OAuth clients, even if in the same Google Cloud project.

---

## Run

### Docker (recommended — everything at once)

```bash
docker compose up --build     # Postgres + Cronometer MCP + bot + backend + web
docker compose logs -f bot    # watch it; on startup you'll see "Proactive scheduler started"
docker compose down           # stop
```

The bot polls Telegram — open your bot and send `/start`. The web app is at
**http://localhost:3000**.

> After editing `.env`, recreate the affected service so it reloads: `docker compose up -d
> --force-recreate backend` (a plain restart won't pick up `env_file` changes). If you recreate
> `backend`, also `docker compose restart web` — nginx caches the backend's address at startup
> and otherwise returns **502** on `/api` until it re-resolves.

### Local (two terminals, for development)

```bash
# Terminal 1 — Cronometer MCP
cd mcp/cronometer && uv sync && MCP_TRANSPORT=streamable-http PORT=8001 uv run cronometer-mcp
# Terminal 2 — bot
cd backend && uv sync && uv run python -m app.telegram_bot
```

See `backend/README.md` for the CLI test harness, model switching, and scheduler details.

### Web app

A React dashboard (chat, charts, and settings — with a light/dark theme) lives in `web/`.

- **Docker:** it's part of `docker compose up` → open **http://localhost:3000**
- **Dev:** run the backend (`cd backend && uv run nutrimind-backend`, needs the Cronometer MCP too),
  then `cd web && npm install && npm run dev` → **http://localhost:5173**

Sign in as the **owner** with your `API_BEARER_TOKEN` password, or (if you set up Google sign-in
in [Setup §5](#5-web-app-sign-in-owner--family)) let **family members** sign in with Google and
approve them from **Members**. From the app you can chat, see weight/macro/cost charts, manage
integrations, and pick the LLM in **Settings**.

---

## Using it

Just talk to it — on Telegram or in the web app's chat:

- *“About to eat 3 eggs and 2 toast at 8am — good?”* → analyzes & logs it
- Send a **photo** of a meal or nutrition label → identifies & logs it
- *“My weight is 82.5 kg”* → logs it
- *“How many calories have I logged today?”* / *“How did I sleep this week?”*
- *“I’m vegetarian, allergic to peanuts, aiming for 160g protein”* → it remembers

Commands: `/help`, `/trends` (weight, calories & sleep charts — last week / month),
`/review` (weekly review), `/usage` (tokens & cost), `/whoami`.

---

## Notes & limitations

- **Cronometer** has no official personal API; this uses the **unofficial mobile API**. It works
  without a paid tier but can break on Cronometer app updates, and automated access is outside
  their ToS — **personal use only**.
- **Google Health** connector is community/unofficial and in beta.
- **Keep your repo private** — it’s wired to personal health accounts and credentials live in
  `.env` (which is git-ignored, along with the local database and OAuth tokens).
- **Multi-user, shared integrations:** each member has their own login, profile, chat, and usage,
  but the **Cronometer** and **Google Health** connectors use the single shared account configured
  in `.env` — everyone's meals/weight log to that one account. Best for a household, not strangers.
- Docker uses **Postgres**; local runs use **SQLite** — profile/history don’t carry between them.

> ⚕️ NutriMind provides general wellness and nutrition guidance, not medical advice. For medical
> concerns, consult a healthcare professional.
