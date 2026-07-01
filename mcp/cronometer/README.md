# Cronometer MCP (mobile REST API)

MCP server exposing Cronometer food logging, diary, nutrition, and body-weight tracking to the
NutriMind agents. Talks to the **unofficial** `mobile.cronometer.com` REST API (the same one the
Android/Flutter app uses), so it works without the paid Pro tier.

> Vendored and adapted from [`rwestergren/cronometer-api-mcp`](https://github.com/rwestergren/cronometer-api-mcp)
> (MIT — see `LICENSE.upstream`). Added: `log_weight` / `get_weight_history` (biometrics), a
> Python-version relax, and a bug fix in session caching.

## Tools

| Tool | Kind | Notes |
|---|---|---|
| `search_foods` | read | Search the food database. |
| `get_food_details` | read | Measures + nutrients for a food. |
| `add_food_entry` | write | Log a serving to the diary. |
| `remove_food_entry` | write | Delete diary entries (v3 API). |
| `get_food_log` | read | Diary + energy/nutrition summary for a day. |
| `get_daily_nutrition` | read | Consumed macros + tracked micronutrients. |
| `get_nutrition_scores` | read | Category scores + per-nutrient confidence. |
| `add_custom_food` | write | Create a custom food. |
| `copy_day` / `mark_day_complete` | write | Diary management. |
| `get_macro_targets` | read | Weekly schedule + templates. |
| `get_fasting_history` / `get_fasting_stats` | read | Fasting data. |
| `log_weight` | write | Logs body weight (metricId 1; lbs/kg). Verified live. |
| `get_weight_history` | read | Weight history over a date range. Verified live. |

All tools are verified against a live account via `smoke_test.py`. The biometric schema
(`type="Biometric"`, `metricId=1` = body weight, `unitId=2` = lbs) was reverse-engineered from
the account's own diary stream. Biometric *delete* is not yet wired (correct mistaken entries in
the app for now).

## Configuration

Set in the repo-root `.env` (see `.env.example`):

```
CRONOMETER_USERNAME=you@example.com
CRONOMETER_PASSWORD=...
```

The session token is cached under `~/.cache/cronometer-mcp/session.json` to avoid re-login
rate limits.

## Run

```bash
cd mcp/cronometer
uv sync
# stdio (for a local MCP client):
uv run cronometer-mcp
# HTTP (for the backend to connect over the network):
MCP_TRANSPORT=streamable-http PORT=8001 uv run cronometer-mcp
```

## Validate against your account

```bash
uv run python smoke_test.py            # read-only checks (login, search, diary)
uv run python smoke_test.py --write    # also logs + removes a test food entry, logs a weight
```

## ⚠️ Terms of use

This uses an unofficial, reverse-engineered API. It can break on Cronometer app updates and is
against Cronometer's ToS for automated access. Personal use only; throttle requests.
