"""Tests for the hook-runtime target layer (hooks/targets/).

Covers target detection, the Codex payload normalizer, the per-(target,
event) capability map, and the buffer-then-flush emitter contract (Codex
parses hook stdout as ONE JSON object).
"""

import json

import pytest

from hooks.targets import current_target, is_codex
from hooks.targets.capabilities import allowed_permission_decisions, can_inject_context
from hooks.targets.emitter import buffer_context, flush, has_buffered
from hooks.targets.normalizer import normalize_payload


@pytest.fixture
def codex(monkeypatch):
    monkeypatch.setenv("AGENTIHOOKS_TARGET", "codex")


@pytest.fixture
def claude(monkeypatch):
    monkeypatch.delenv("AGENTIHOOKS_TARGET", raising=False)


class TestDetection:
    def test_default_is_claude(self, claude):
        assert current_target() == "claude"
        assert not is_codex()

    def test_env_marker_selects_codex(self, codex):
        assert current_target() == "codex"
        assert is_codex()


class TestNormalizer:
    def test_claude_payload_untouched(self, claude):
        payload = {"hook_event_name": "PostToolUse", "tool_response": {"out": 1}}
        assert normalize_payload(dict(payload)) == payload

    def test_codex_fills_output_aliases(self, codex):
        payload = normalize_payload(
            {"hook_event_name": "PostToolUse", "tool_name": "shell", "tool_response": {"out": 1}}
        )
        assert payload["tool_output"] == {"out": 1}
        assert payload["tool_result"] == {"out": 1}

    def test_codex_does_not_clobber_existing_aliases(self, codex):
        payload = normalize_payload({"tool_response": "new", "tool_output": "old"})
        assert payload["tool_output"] == "old"


class TestCapabilities:
    def test_codex_pretooluse_has_no_context_channel(self):
        assert can_inject_context("PreToolUse", target="codex") is False

    def test_codex_other_events_inject(self):
        for event in ("SessionStart", "UserPromptSubmit", "PostToolUse", "Stop"):
            assert can_inject_context(event, target="codex") is True

    def test_claude_injects_everywhere(self):
        assert can_inject_context("PreToolUse", target="claude") is True

    def test_codex_permission_decisions_deny_only(self):
        assert allowed_permission_decisions("codex") == frozenset({"deny"})
        assert "allow" not in allowed_permission_decisions("codex")

    def test_claude_permission_decisions_full(self):
        assert allowed_permission_decisions("claude") == frozenset({"allow", "deny", "ask"})


class TestEmitter:
    def test_flush_empty_is_silent(self, codex, capsys):
        flush("PostToolUse")
        assert capsys.readouterr().out == ""

    def test_codex_flush_single_envelope(self, codex, capsys):
        buffer_context("first block")
        buffer_context("second block")
        flush("PostToolUse")
        out = capsys.readouterr().out.strip().splitlines()
        assert len(out) == 1, "codex must receive exactly one JSON line"
        doc = json.loads(out[0])
        ctx = doc["hookSpecificOutput"]["additionalContext"]
        assert "first block" in ctx and "second block" in ctx
        assert doc["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
        assert not has_buffered(), "flush must clear the buffer"

    def test_codex_pretooluse_flush_drops(self, codex, capsys):
        buffer_context("advisory note")
        flush("PreToolUse")
        assert capsys.readouterr().out == ""
        assert not has_buffered()

    def test_inject_context_buffers_on_codex(self, codex, capsys):
        from hooks.common import inject_context

        inject_context("hello codex", also_log=False, skip_compression=True)
        assert capsys.readouterr().out == ""
        assert has_buffered()
        flush("SessionStart")
        doc = json.loads(capsys.readouterr().out)
        assert "hello codex" in doc["hookSpecificOutput"]["additionalContext"]

    def test_inject_context_prints_on_claude(self, claude, capsys):
        from hooks.common import inject_context

        inject_context("hello claude", also_log=False, skip_compression=True)
        out = capsys.readouterr().out
        assert "=== CONTEXT INJECTION ===" in out
        assert "hello claude" in out
        assert not has_buffered()
