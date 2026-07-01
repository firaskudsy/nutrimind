FROM python:3.12-slim

# uv for fast, reproducible installs
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src

RUN uv pip install --system --no-cache .

# Streamable HTTP transport for the agent backend to connect over the network.
ENV MCP_TRANSPORT=streamable-http \
    FASTMCP_HOST=0.0.0.0 \
    PORT=8001

EXPOSE 8001
CMD ["cronometer-mcp"]
