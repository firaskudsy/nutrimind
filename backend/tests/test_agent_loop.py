"""LiteLLM tool-loop test with a mocked model (no real API calls).

Verifies that run_turn drives the tool loop: when the model returns a tool call,
we dispatch it (here a real memory tool writing to the DB), feed the result back,
and return the model's final text.
"""

import tempfile
from types import SimpleNamespace

import pytest


def _tool_call(name: str, arguments: str = "{}", call_id: str = "call_1"):
    return SimpleNamespace(
        id=call_id,
        type="function",
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _response(content=None, tool_calls=None):
    msg = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


@pytest.fixture
async def agent_env(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp.name}")

    from app.config import get_settings

    get_settings.cache_clear()

    from agents import memory, nutrition_agent

    memory._db_ready = False
    # No MCP servers in this test — keep it hermetic (don't spawn npx/http).
    monkeypatch.setattr(nutrition_agent.registry, "server_refs", lambda *_: [])
    yield nutrition_agent, memory
    memory._db_ready = False


async def test_tool_loop_executes_and_returns_final(agent_env, monkeypatch):
    nutrition_agent, memory = agent_env

    # Turn 1: model asks to save the profile. Turn 2: model gives a final answer.
    responses = iter(
        [
            _response(
                tool_calls=[
                    _tool_call(
                        "update_user_profile",
                        '{"name": "Alex", "daily_protein_target_g": 150}',
                    )
                ]
            ),
            _response(content="Got it — saved your protein target."),
        ]
    )

    async def fake_acompletion(**_kwargs):
        return next(responses)

    monkeypatch.setattr(nutrition_agent.litellm, "acompletion", fake_acompletion)

    reply = await nutrition_agent.run_turn("remember I want 150g protein a day")
    assert reply == "Got it — saved your protein target."

    # The memory tool actually ran and persisted to the DB.
    profile = await memory.load_profile()
    assert profile.name == "Alex"
    assert profile.targets["protein_g"] == 150


async def test_plain_answer_no_tools(agent_env, monkeypatch):
    nutrition_agent, _ = agent_env

    async def fake_acompletion(**_kwargs):
        return _response(content="Hello! How can I help?")

    monkeypatch.setattr(nutrition_agent.litellm, "acompletion", fake_acompletion)
    reply = await nutrition_agent.run_turn("hi")
    assert reply == "Hello! How can I help?"
