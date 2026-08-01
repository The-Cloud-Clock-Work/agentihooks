"""Tests for caller-session resolution in the hooks-utils MCP tools.

The precedence here is what makes the tools correct under a shared network
server: an explicit argument is the only identity a daemon serving many
sessions from one process can trust.
"""

import pytest

from hooks.mcp._session import resolve_session_id, set_env_fallback_allowed

pytestmark = pytest.mark.unit

_ENV_VARS = ("CLAUDE_CODE_SESSION_ID", "CLAUDE_SESSION_ID")


@pytest.fixture(autouse=True)
def _clear_session_env(monkeypatch):
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    set_env_fallback_allowed(True)
    yield
    set_env_fallback_allowed(True)


class TestResolveSessionId:
    def test_explicit_wins_over_both_env_vars(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "from-env")
        monkeypatch.setenv("CLAUDE_SESSION_ID", "legacy-env")

        assert resolve_session_id("explicit-id") == "explicit-id"

    def test_falls_back_to_claude_code_session_id(self, monkeypatch):
        """This is the var Claude Code actually injects into a stdio MCP subprocess."""
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "from-env")

        assert resolve_session_id() == "from-env"

    def test_claude_code_session_id_beats_legacy_name(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "real")
        monkeypatch.setenv("CLAUDE_SESSION_ID", "legacy")

        assert resolve_session_id() == "real"

    def test_legacy_name_still_honoured_when_alone(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_SESSION_ID", "legacy")

        assert resolve_session_id() == "legacy"

    def test_returns_empty_when_nothing_resolves(self):
        assert resolve_session_id() == ""

    def test_empty_explicit_is_not_treated_as_an_answer(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "from-env")

        assert resolve_session_id("") == "from-env"


class TestEnvFallbackDisabled:
    """What a network daemon must do.

    A daemon inherits CLAUDE_CODE_SESSION_ID from whatever shell started it. If
    the env fallback stayed on, an omitted argument would not fail — it would
    resolve to that shell's session and write another agent's state. Observed
    for real before this guard existed.
    """

    def test_env_is_ignored_when_fallback_disabled(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "the-launching-shells-session")
        set_env_fallback_allowed(False)

        assert resolve_session_id() == ""

    def test_explicit_still_resolves_when_fallback_disabled(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "the-launching-shells-session")
        set_env_fallback_allowed(False)

        assert resolve_session_id("real-caller") == "real-caller"


class TestNoSecondaryEnvFallback:
    """The guard must hold all the way down, not just at the MCP wrapper.

    Regression: ``hooks.context.agent_pool.call_agent`` used to do its own
    ``os.getenv`` fallback when handed an empty caller. That silently re-opened
    the hole the wrapper had just closed — under a daemon it attributed the
    message to whatever session the process had inherited. The earlier
    event-loop test monkeypatched this function out, so it never caught it.
    """

    def test_context_call_agent_refuses_empty_caller_despite_env(self, monkeypatch):
        from hooks.context import agent_pool

        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "daemons-inherited-session")
        monkeypatch.setattr(agent_pool, "AGENT_POOL_ENABLED", True)

        result = agent_pool.call_agent("some-peer", "hello", caller_session_id="")

        assert result["success"] is False
        assert "caller_session_id" in result["error"]

    def test_mcp_call_agent_refuses_when_nothing_resolves(self, monkeypatch):
        import json

        from hooks.mcp import build_server

        monkeypatch.setenv("MCP_TRANSPORT", "streamable-http")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "daemons-inherited-session")
        server = build_server()
        call_agent = server._tool_manager._tools["call_agent"].fn

        def _explode(*args, **kwargs):
            raise AssertionError("must not reach the pool with an unattributable caller")

        monkeypatch.setattr("hooks.context.agent_pool.call_agent", _explode)

        import anyio

        result = json.loads(anyio.run(lambda: call_agent("peer", "hi")))

        assert result["success"] is False
        assert "session_id" in result["error"]


class TestBuildServerSetsFallbackPolicy:
    """build_server decides the policy once, so tool bodies never branch."""

    def test_stdio_keeps_env_fallback(self, monkeypatch):
        from hooks.mcp import build_server

        monkeypatch.delenv("MCP_TRANSPORT", raising=False)
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "stdio-session")
        build_server()

        assert resolve_session_id() == "stdio-session"

    @pytest.mark.parametrize("transport", ["sse", "streamable-http"])
    def test_network_transports_disable_env_fallback(self, monkeypatch, transport):
        from hooks.mcp import build_server

        monkeypatch.setenv("MCP_TRANSPORT", transport)
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "inherited-from-shell")
        build_server()

        assert resolve_session_id() == ""
