#!/usr/bin/env bash
# Convenience wrapper for the pinned Google Health MCP connector.
# Usage: ./run.sh {setup|auth|doctor|server}
set -euo pipefail

PKG="google-health-mcp-unofficial@0.5.1"
SCOPE_PRESET="${SCOPE_PRESET:-full}"

cmd="${1:-doctor}"
case "$cmd" in
  setup)  exec npx -y "$PKG" setup --scope-preset "$SCOPE_PRESET" ;;
  auth)   exec npx -y "$PKG" auth ;;
  doctor) exec npx -y "$PKG" doctor --live ;;
  server) exec npx -y "$PKG" ;;   # stdio MCP server (what the agent spawns)
  *) echo "Usage: $0 {setup|auth|doctor|server}" >&2; exit 1 ;;
esac
