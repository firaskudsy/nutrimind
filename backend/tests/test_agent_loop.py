"""LiteLLM tool-loop test with a mocked model (no real API calls).

Verifies that run_turn drives the tool loop: when the model returns a tool call,
we dispatch it (here a real memory tool writing to the DB), feed the result back,
and return the model's final text.
"""

import contextlib
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

    reply = await nutrition_agent.run_turn("remember I want 150g protein a day", user_id=1)
    assert reply == "Got it — saved your protein target."

    # The memory tool actually ran and persisted to the DB (for user 1).
    profile = await memory.load_profile(1)
    assert profile.name == "Alex"
    assert profile.targets["protein_g"] == 150


async def test_plain_answer_no_tools(agent_env, monkeypatch):
    nutrition_agent, _ = agent_env

    async def fake_acompletion(**_kwargs):
        return _response(content="Hello! How can I help?")

    monkeypatch.setattr(nutrition_agent.litellm, "acompletion", fake_acompletion)
    reply = await nutrition_agent.run_turn("hi", user_id=1)
    assert reply == "Hello! How can I help?"


async def test_write_tool_call_is_recorded_in_action_log(agent_env, monkeypatch):
    """A Cronometer write tool's own verified result -- not the model's narration
    -- must land in the action log, so a false "logged!" claim is auditable."""
    nutrition_agent, memory = agent_env

    fake_tool = SimpleNamespace(
        name="log_weight",
        description="Log weight",
        inputSchema={"type": "object", "properties": {}},
    )

    class FakeSession:
        async def list_tools(self):
            return SimpleNamespace(tools=[fake_tool])

        async def call_tool(self, name, args):
            return SimpleNamespace(structuredContent={"status": "success", "logged": args})

    @contextlib.asynccontextmanager
    async def fake_open_session(_ref):
        yield FakeSession()

    ref = nutrition_agent.registry.ServerRef("cronometer", "http", url="http://fake")
    monkeypatch.setattr(nutrition_agent.registry, "server_refs", lambda *_a, **_k: [ref])
    monkeypatch.setattr(nutrition_agent.registry, "open_session", fake_open_session)

    responses = iter(
        [
            _response(tool_calls=[_tool_call("log_weight", '{"value": 322.4, "unit": "lbs"}')]),
            _response(content="Logged 322.4 lbs."),
        ]
    )

    async def fake_acompletion(**_kwargs):
        return next(responses)

    monkeypatch.setattr(nutrition_agent.litellm, "acompletion", fake_acompletion)

    reply = await nutrition_agent.run_turn("322.4", user_id=1, source="chat")
    assert reply == "Logged 322.4 lbs."

    actions = await memory.recent_actions(1)
    assert len(actions) == 1
    assert actions[0].tool_name == "log_weight"
    assert actions[0].success is True
    assert actions[0].source == "chat"


def test_claims_unverified_write_detection():
    from agents.nutrition_agent import _claims_unverified_write

    assert _claims_unverified_write("Done. Logged 322.4 lbs for today.")
    assert _claims_unverified_write("Removed the old entry and added the new one.")
    assert not _claims_unverified_write("I'll log that once you confirm the portion.")
    assert not _claims_unverified_write("I wasn't able to log that -- try again?")
    assert not _claims_unverified_write("That meal fits your calorie budget nicely.")


async def test_unlogged_claim_triggers_correction_then_flags_if_repeated(agent_env, monkeypatch):
    """The model claims a write with no tool call -- give it one corrective
    retry; if it still won't call the tool or walk back the claim, flag it in
    the action log so the mismatch is auditable even when auto-correction fails."""
    nutrition_agent, memory = agent_env

    responses = iter(
        [
            _response(content="Done. Logged 321.9 lbs for today."),
            _response(content="Confirmed, logged 321.9 lbs -- all set."),
        ]
    )

    async def fake_acompletion(**_kwargs):
        return next(responses)

    monkeypatch.setattr(nutrition_agent.litellm, "acompletion", fake_acompletion)

    reply = await nutrition_agent.run_turn("log 321.9 lbs", user_id=1, source="chat")
    assert reply == "Confirmed, logged 321.9 lbs -- all set."

    actions = await memory.recent_actions(1)
    assert len(actions) == 1
    assert actions[0].tool_name == "unverified_claim"
    assert actions[0].success is False


async def test_unlogged_claim_correction_succeeds_when_model_fixes_itself(agent_env, monkeypatch):
    """If the model walks back its claim on the corrective retry, no flag is
    recorded -- the backstop only fires once, and a clean correction is fine."""
    nutrition_agent, memory = agent_env

    responses = iter(
        [
            _response(content="Done. Logged 321.9 lbs for today."),
            _response(content="Sorry, I actually didn't log that yet -- want me to now?"),
        ]
    )

    async def fake_acompletion(**_kwargs):
        return next(responses)

    monkeypatch.setattr(nutrition_agent.litellm, "acompletion", fake_acompletion)

    reply = await nutrition_agent.run_turn("log 321.9 lbs", user_id=1, source="chat")
    assert "didn't log" in reply

    assert await memory.recent_actions(1) == []


async def test_out_of_credits_raises_a_clean_agent_error(agent_env, monkeypatch):
    """A raw provider exception must never reach the caller -- only AgentError with
    a message safe to show a user (this is what turns a bare 500 into a real
    "you're out of credits" message on the web/Telegram surfaces)."""
    nutrition_agent, _ = agent_env

    async def fake_acompletion(**_kwargs):
        raise RuntimeError(
            'litellm.BadRequestError: AnthropicException - {"type":"error","error":'
            '{"type":"invalid_request_error","message":"Your credit balance is too low '
            'to access the Anthropic API. Please go to Plans & Billing to upgrade or '
            'purchase credits."}}'
        )

    monkeypatch.setattr(nutrition_agent.litellm, "acompletion", fake_acompletion)
    with pytest.raises(nutrition_agent.AgentError) as excinfo:
        await nutrition_agent.run_turn("hi", user_id=1)
    assert "out of credits" in str(excinfo.value)
    assert "Settings" in str(excinfo.value)
    assert "BadRequestError" not in str(excinfo.value)  # raw dump must not leak through
