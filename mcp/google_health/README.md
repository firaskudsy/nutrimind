# Google Health MCP (Fitbit / Pixel via Google Health API v4)

This is a **reused, pinned external MCP server**, not vendored code. We run
[`google-health-mcp-unofficial`](https://github.com/davidmosiah/google-health-mcp) (MIT, v0.5.1)
via `npx`. It's local-first: your Google OAuth tokens are stored on your machine at
`~/.google-health-mcp/tokens.json` and never leave it. Our agents connect to it as an MCP client.

> **Why reuse, not rebuild:** it's a mature TypeScript server with OAuth, token store, caching,
> retries, and privacy hardening around the Google Health API v4. Rebuilding in Python would add
> risk for no gain. We pin the version (`@0.5.1`) for supply-chain safety and bump deliberately.

> Google Health API v4 is the cloud successor to the Fitbit Web API (which turns down Sept 2026).
> It aggregates **Fitbit + Pixel Watch + partners**: sleep, activity/steps, heart rate, weight.

## Data / tools we care about

- `google_health_connection_status` — is auth working
- `google_health_data_inventory` — what data types your account exposes
- `google_health_daily_summary` / `google_health_weekly_summary` — rollups
- `google_health_list_data_points` / `google_health_rollup` — sleep, steps, heart rate, weight
- `google_health_privacy_audit` — what the server can see

Read-only scopes: `sleep.readonly`, `activity_and_fitness.readonly`,
`health_metrics_and_measurements.readonly` (and optionally `profile`, `settings`, `nutrition`).

## One-time setup (you do this)

1. **Google Cloud** → create a project → **enable the Google Health API**.
2. Create an **OAuth 2.0 Client ID** of type **Web application**.
3. Add the redirect URI: `http://127.0.0.1:3000/callback`.
4. Put the client id/secret where the tool expects them (it prompts during `setup`); we also mirror
   them into the repo-root `.env` (`GOOGLE_HEALTH_CLIENT_ID`, `GOOGLE_HEALTH_CLIENT_SECRET`,
   `GOOGLE_HEALTH_REDIRECT_URI`) for reference.
5. Ensure a **Fitbit or Pixel Watch** is linked to that Google account (that's the data source).

Then authenticate (run these yourself — they download/execute the pinned npm package):

```bash
npx -y google-health-mcp-unofficial@0.5.1 setup --scope-preset full
npx -y google-health-mcp-unofficial@0.5.1 auth
npx -y google-health-mcp-unofficial@0.5.1 doctor --live
```

`doctor --live` confirms the token works and can read your data. If it passes, we're done — the
agent can query it. Or use the helper: `./run.sh setup|auth|doctor`.

## How our agents connect

The backend registers this as an MCP server over stdio (see `mcp.json`). Because tokens live in
`~/.google-health-mcp`, run the agent backend as the same OS user that ran `auth` (or mount that
dir if containerized).

## Notes / risks

- **Beta + unofficial.** Not affiliated with Google/Fitbit. Google Health API v4 is still evolving;
  data types can change. Read-only by default.
- **Access.** The Google Health API must be enabled for your Cloud project; testing with your own
  account works before app verification. Public/production use needs OAuth verification.
- **Supply chain.** Pinned to `@0.5.1`. Review the diff before bumping.
