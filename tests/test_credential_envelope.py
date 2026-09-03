"""Credential guard ↔ hook_manager integration: the rewrite envelope, the
fail-closed path, and the single-JSON invariant on claude PreToolUse."""

import json

import pytest

import hooks.hook_manager as hm
from hooks.hook_manager import BlockAction
from hooks.targets import emitter

pytestmark = pytest.mark.unit


def _payload(command, mode="bypassPermissions", cwd="/tmp"):
    return {
        "hook_event_name": "PreToolUse",
        "session_id": "sid-credential-envelope",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "permission_mode": mode,
        "cwd": cwd,
    }


def _single_json(out):
    out = out.strip()
    assert out.startswith("{") and out.endswith("}"), out
    assert out.count("\n") == 0, out
    return json.loads(out)


@pytest.fixture
def forced_claude(monkeypatch):
    monkeypatch.setenv("AGENTIHOOKS_TARGET", "claude")
    monkeypatch.setattr(emitter, "_forced", True)
    monkeypatch.setattr(emitter, "_buffer", [])


class TestRewriteEnvelope:
    def test_bypass_rewrites_recursive_grep(self, forced_claude, capsys, tmp_path):
        hm.on_pre_tool_use(_payload("grep -rn X .", cwd=str(tmp_path)))
        out = _single_json(capsys.readouterr().out)["hookSpecificOutput"]
        assert out["permissionDecision"] == "allow"
        assert out["updatedInput"]["command"].startswith("grep --exclude=.env ")
        assert out["updatedInput"]["command"].endswith(" -rn X .")

    def test_buffered_context_rides_the_same_envelope(self, forced_claude, capsys, tmp_path):
        from hooks.common import inject_context

        inject_context("probe context", also_log=False)
        hm.on_pre_tool_use(_payload("rg foo .", cwd=str(tmp_path)))
        out = _single_json(capsys.readouterr().out)["hookSpecificOutput"]
        assert "probe context" in out["additionalContext"]
        assert "-g '!.env'" in out["updatedInput"]["command"]

    def test_default_mode_never_rewrites(self, forced_claude, capsys, tmp_path):
        hm.on_pre_tool_use(_payload("grep -rn X .", mode="default", cwd=str(tmp_path)))
        assert "updatedInput" not in capsys.readouterr().out

    def test_codex_prints_nothing(self, monkeypatch, capsys, tmp_path):
        monkeypatch.setenv("AGENTIHOOKS_TARGET", "codex")
        monkeypatch.setattr(emitter, "_buffer", [])
        hm.on_pre_tool_use(_payload("grep -rn X .", cwd=str(tmp_path)))
        assert capsys.readouterr().out == ""

    def test_block_leaves_stdout_empty(self, forced_claude, capsys, tmp_path):
        with pytest.raises(BlockAction):
            hm.on_pre_tool_use(_payload("cat .env", cwd=str(tmp_path)))
        assert capsys.readouterr().out == ""


class TestFailClosed:
    def test_crash_near_credential_blocks(self, forced_claude, monkeypatch):
        import hooks.context.credential_guard as guard

        monkeypatch.setattr(guard, "evaluate", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        with pytest.raises(BlockAction, match="internal error near a credential path"):
            hm.on_pre_tool_use(_payload("cat .env"))

    def test_crash_elsewhere_warns_and_allows(self, forced_claude, monkeypatch, capsys):
        import hooks.context.credential_guard as guard

        monkeypatch.setattr(guard, "evaluate", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        hm.on_pre_tool_use(_payload("git status"))
        assert "WARNING: credential_guard check failed" in capsys.readouterr().err


class TestEmitPermissionDecision:
    def test_rewrite_dropped_when_target_cannot_mutate(self, monkeypatch, capsys):
        import hooks.targets.capabilities as caps

        monkeypatch.setenv("AGENTIHOOKS_TARGET", "claude")
        monkeypatch.setattr(caps, "supports_arg_mutation", lambda target=None: False)
        hm.emit_permission_decision("PreToolUse", "allow", "x", updated_input={"command": "y"})
        assert capsys.readouterr().out == ""

    def test_claude_field_is_updated_input(self, monkeypatch, capsys):
        monkeypatch.setenv("AGENTIHOOKS_TARGET", "claude")
        hm.emit_permission_decision(
            "PreToolUse", "allow", "why", updated_input={"command": "y"}, additional_context="ctx"
        )
        out = _single_json(capsys.readouterr().out)["hookSpecificOutput"]
        assert out == {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": "why",
            "updatedInput": {"command": "y"},
            "additionalContext": "ctx",
        }
