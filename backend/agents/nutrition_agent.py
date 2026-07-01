"""The NutriMind agent: LiteLLM + a provider-agnostic MCP tool loop.

Uses LiteLLM so the model/provider is a single config string (AGENT_MODEL), e.g.
anthropic/claude-haiku-4-5, gemini/gemini-2.5-flash-lite, gpt-4o-mini. MCP tools
(Cronometer, Google Health) and local memory tools are exposed to the model in
the universal OpenAI function-schema format; we run the tool loop ourselves.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

import litellm

from agents import memory, usage
from agents.prompts import build_system_prompt
from app.config import get_settings
from db import models
from mcp_clients import registry

logger = logging.getLogger(__name__)

# Let LiteLLM silently drop params a given provider doesn't accept (e.g. Anthropic
# Opus rejects temperature) so the same call works across providers.
litellm.drop_params = True

MAX_TOKENS = 8192
MAX_TOOL_ITERATIONS = 8


@dataclass
class ImageInput:
    data: bytes
    media_type: str = "image/jpeg"


def _user_content(text: str, image: ImageInput | None) -> Any:
    """OpenAI-format user content: text, plus an image_url block if provided."""
    if image is None:
        return text
    b64 = base64.standard_b64encode(image.data).decode("utf-8")
    return [
        {
            "type": "image_url",
            "image_url": {"url": f"data:{image.media_type};base64,{b64}"},
        },
        {"type": "text", "text": text or "Here's a photo of what I'm considering."},
    ]


def _when_text() -> str:
    now = datetime.now().astimezone()
    return (
        f"Current date and time: {now:%A, %Y-%m-%d %H:%M %Z}.\n"
        f"Today's date is {now:%Y-%m-%d}. When the user refers to a day "
        "('today'/'yesterday'/'this morning') or a clock time, compute the ACTUAL "
        "calendar date (YYYY-MM-DD) and 24-hour time and pass them to the tools "
        "(add_food_entry date/time, log_weight date). Never guess the date."
    )


def _system_content(profile: models.UserProfile | None, model: str) -> Any:
    """Build the system message.

    For Anthropic models, return two blocks so the stable core+profile is
    prompt-cached (cache_control) while the volatile date/time — which changes
    every minute — sits in a separate uncached block. Other providers get a
    plain concatenated string.
    """
    core = build_system_prompt(profile)
    when = _when_text()
    if model.startswith("anthropic/"):
        return [
            {"type": "text", "text": core, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": when},
        ]
    return f"{core}\n\n{when}"


def _mcp_to_openai(tool: Any) -> dict:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": tool.inputSchema or {"type": "object", "properties": {}},
        },
    }


def _result_text(result: Any) -> str:
    """Stringify an MCP CallToolResult into text for the model."""
    if getattr(result, "structuredContent", None):
        return json.dumps(result.structuredContent)
    parts = [
        c.text for c in getattr(result, "content", []) if getattr(c, "type", None) == "text"
    ]
    return "\n".join(parts) if parts else "(no output)"


def _mcp_caller(session: Any, name: str) -> Callable:
    async def call(args: dict) -> str:
        return _result_text(await session.call_tool(name, args))

    return call


async def _gather_tools(
    stack: contextlib.AsyncExitStack, settings
) -> tuple[list[dict], dict[str, Callable]]:
    """Assemble OpenAI tool specs + a name->callable dispatch from memory + MCP."""
    specs: list[dict] = list(memory.MEMORY_TOOL_SPECS)
    dispatch: dict[str, Callable] = dict(memory.MEMORY_DISPATCH)
    for ref in registry.server_refs(settings):
        # Retry once — smooths over transient blips (e.g. a container restart).
        for attempt in range(2):
            try:
                session = await stack.enter_async_context(registry.open_session(ref))
                listed = await session.list_tools()
                loaded = 0
                for t in listed.tools:
                    if ref.tool_allowlist and t.name not in ref.tool_allowlist:
                        continue
                    specs.append(_mcp_to_openai(t))
                    dispatch[t.name] = _mcp_caller(session, t.name)
                    loaded += 1
                logger.info("Loaded %d tools from MCP %s", loaded, ref.name)
                break
            except Exception as exc:  # noqa: BLE001 - degrade if a server is down
                if attempt == 0:
                    await asyncio.sleep(0.6)
                    continue
                logger.warning("MCP %s unavailable, skipping: %s", ref.name, exc)
    return specs, dispatch


def _assistant_dict(msg: Any) -> dict:
    """Convert a LiteLLM response message into a messages[] entry.

    Content is None (not "") when empty — the OpenAI-correct shape when tool_calls
    are present, and what keeps Gemini's function-calling loop well-formed.
    """
    out: dict = {"role": "assistant", "content": msg.content or None}
    if getattr(msg, "tool_calls", None):
        out["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in msg.tool_calls
        ]
    return out


async def _execute_tool_calls(
    tool_calls: list, dispatch: dict[str, Callable], messages: list[dict]
) -> None:
    """Run each tool call and append its result as a tool message."""
    for tc in tool_calls:
        try:
            args = json.loads(tc.function.arguments or "{}")
        except json.JSONDecodeError:
            args = {}
        fn = dispatch.get(tc.function.name)
        try:
            result = await fn(args) if fn else f"Error: unknown tool {tc.function.name}"
        except Exception as exc:  # noqa: BLE001 - report tool failure to the model
            logger.exception("tool %s failed", tc.function.name)
            result = f"Error running {tc.function.name}: {exc}"
        messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})


async def run_turn(
    user_text: str,
    *,
    image: ImageInput | None = None,
    history: list[dict] | None = None,
    profile: models.UserProfile | None = None,
    source: str = "chat",
) -> str:
    """Run one assistant turn and return the final text response."""
    settings = get_settings()
    if profile is None:
        profile = await memory.load_profile()

    messages: list[dict] = [
        {"role": "system", "content": _system_content(profile, settings.agent_model)}
    ]
    messages.extend(history or [])
    messages.append({"role": "user", "content": _user_content(user_text, image)})

    async with contextlib.AsyncExitStack() as stack:
        tools, dispatch = await _gather_tools(stack, settings)

        for _ in range(MAX_TOOL_ITERATIONS):
            resp = await litellm.acompletion(
                model=settings.agent_model,
                messages=messages,
                tools=tools or None,
                max_tokens=MAX_TOKENS,
            )
            await usage.record_from_response(resp, settings.agent_model, source)
            msg = resp.choices[0].message
            messages.append(_assistant_dict(msg))

            tool_calls = getattr(msg, "tool_calls", None)
            if not tool_calls:
                return (msg.content or "").strip()
            await _execute_tool_calls(tool_calls, dispatch, messages)

    return "I wasn't able to finish that — try again?"
