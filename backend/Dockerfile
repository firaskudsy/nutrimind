FROM python:3.12-slim

# Node.js 20 + the Google Health MCP (spawned via npx by the agent). Installing
# the package globally means npx finds it locally instead of downloading per call.
# build-essential is needed to compile its native dep (better-sqlite3), which has
# no prebuilt ARM binary; kept in the image so the compiled module loads at runtime.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates gnupg build-essential \
 && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && npm install -g google-health-mcp-unofficial@0.5.1 \
 && apt-get purge -y --auto-remove gnupg \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
COPY pyproject.toml README.md ./
COPY app ./app
COPY db ./db
COPY agents ./agents
COPY mcp_clients ./mcp_clients

RUN uv pip install --system --no-cache .

# Default command runs the FastAPI backend; docker-compose's `bot` service
# overrides this to run the Telegram bot.
EXPOSE 8000
CMD ["nutrimind-backend"]
