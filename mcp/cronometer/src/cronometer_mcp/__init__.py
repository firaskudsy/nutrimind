"""Cronometer MCP server (mobile REST API).

Vendored and adapted from rwestergren/cronometer-api-mcp (MIT). See LICENSE.upstream.
Adds body-weight/biometric logging on top of the upstream food + diary tools.
"""

from .server import main

__all__ = ["main"]
