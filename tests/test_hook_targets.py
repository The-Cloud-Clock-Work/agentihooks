"""Tests for the hook-runtime target layer (hooks/targets/).

Covers target detection, the Codex payload normalizer, the per-(target,
event) capability map, and the buffer-then-flush emitter contract (Codex
parses hook stdout as ONE JSON object).
"""

import json

import pytest

from hooks.targets import current_target, is_codex
from hooks.targets.capabilities import allowed_permission_decisions, can_inject_context
from hooks.targets.emitter import buffer_context, drain, flush, has_buffered
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

    def test_drain_returns_joined_content_and_clears(self, codex, capsys):
        buffer_context("first block")
        buffer_context("second block")
        content = drain()
        assert "first block" in content and "second block" in content
        assert not has_buffered()
        # drain() never emits anything itself — unlike flush(), it's silent.
        assert capsys.readouterr().out == ""

    def test_drain_empty_is_safe(self, codex, capsys):
        assert not has_buffered()
        assert drain() == ""
        assert capsys.readouterr().out == ""

    def test_drain_after_block_prevents_leak_into_next_event(self, codex, capsys):
        """The invariant fix_2/fix_3 exist to guarantee: content buffered for
        one event must never survive into the next event's flush."""
        buffer_context("event-one context")
        drain()  # simulates main()'s BlockAction/finally path
        flush("PostToolUse")  # a later event in the same (hypothetical) process
        assert capsys.readouterr().out == "", "drained buffer leaked into a later flush"


class TestPermissionDecisionChokePoint:
    """hooks.hook_manager.emit_permission_decision is the sole legal call
    site for a permissionDecision envelope. It must filter every decision
    through allowed_permission_decisions() so a future non-deny decision
    cannot leak through on codex, even though nothing emits one today."""

    def test_codex_deny_is_emitted(self, codex, capsys):
        from hooks.hook_manager import emit_permission_decision

        emit_permission_decision("PreToolUse", "deny", reason="blocked")
        out = capsys.readouterr().out.strip()
        doc = json.loads(out)
        assert doc["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert doc["hookSpecificOutput"]["permissionDecisionReason"] == "blocked"

    def test_codex_allow_is_dropped_not_printed(self, codex, capsys):
        from hooks.hook_manager import emit_permission_decision

        emit_permission_decision("PreToolUse", "allow")
        assert capsys.readouterr().out == ""

    def test_codex_ask_is_dropped_not_printed(self, codex, capsys):
        from hooks.hook_manager import emit_permission_decision

        emit_permission_decision("PreToolUse", "ask")
        assert capsys.readouterr().out == ""

    def test_claude_allow_is_emitted(self, claude, capsys):
        from hooks.hook_manager import emit_permission_decision

        emit_permission_decision("PreToolUse", "allow")
        out = capsys.readouterr().out.strip()
        doc = json.loads(out)
        assert doc["hookSpecificOutput"]["permissionDecision"] == "allow"


class TestGlobalRecord:
    """hooks.targets.global_record — statusline/enforcement read state.json
    directly and must tolerate both the keyed and legacy flat shapes."""

    KEYED = {
        "targets": {
            "global": {
                "claude": {"profile": "anton,brain", "settings_profile": "sp1"},
                "codex": {"profile": "anton"},
            }
        }
    }
    LEGACY = {"targets": {"global": {"path": "/x", "profile": "anton,brain"}}}

    def test_keyed_shape_claude(self, claude):
        from hooks.targets import global_record

        assert global_record(self.KEYED)["profile"] == "anton,brain"

    def test_keyed_shape_codex(self, codex):
        from hooks.targets import global_record

        assert global_record(self.KEYED)["profile"] == "anton"

    def test_legacy_flat_shape(self, claude):
        from hooks.targets import global_record

        assert global_record(self.LEGACY)["profile"] == "anton,brain"

    def test_missing_target_record_empty(self, codex):
        from hooks.targets import global_record

        assert global_record({"targets": {"global": {"claude": {"profile": "p"}}}}) == {}

    def test_empty_state(self, claude):
        from hooks.targets import global_record

        assert global_record({}) == {}


class TestCodexTranscriptResolution:
    """Codex omits transcript_path; the normalizer resolves the rollout by
    session id so brain markers / auto-save / tool-memory keep working."""

    def _rollout(self, home, sid, day="2026/08/10"):
        d = home / "sessions" / day
        d.mkdir(parents=True, exist_ok=True)
        f = d / f"rollout-2026-08-10T21-30-30-{sid}.jsonl"
        f.write_text('{"type":"session_meta","payload":{}}\n')
        return f

    def test_resolves_rollout_from_session_id(self, codex, tmp_path, monkeypatch):
        from hooks.targets.normalizer import normalize_payload

        monkeypatch.setenv("CODEX_HOME", str(tmp_path))
        sid = "019fed27-b61d-7a92-bcec-4ffcccf53b71"
        expected = self._rollout(tmp_path, sid)
        out = normalize_payload({"hook_event_name": "SessionEnd", "session_id": sid})
        assert out["transcript_path"] == str(expected)

    def test_existing_transcript_path_wins(self, codex, tmp_path, monkeypatch):
        from hooks.targets.normalizer import normalize_payload

        monkeypatch.setenv("CODEX_HOME", str(tmp_path))
        sid = "abc-123"
        self._rollout(tmp_path, sid)
        out = normalize_payload({"session_id": sid, "transcript_path": "/given/path.jsonl"})
        assert out["transcript_path"] == "/given/path.jsonl"

    def test_no_match_leaves_key_absent(self, codex, tmp_path, monkeypatch):
        from hooks.targets.normalizer import normalize_payload

        monkeypatch.setenv("CODEX_HOME", str(tmp_path))
        out = normalize_payload({"session_id": "nothing-here"})
        assert not out.get("transcript_path")

    def test_claude_payload_untouched(self, claude, tmp_path, monkeypatch):
        from hooks.targets.normalizer import normalize_payload

        monkeypatch.setenv("CODEX_HOME", str(tmp_path))
        sid = "xyz-789"
        self._rollout(tmp_path, sid)
        out = normalize_payload({"session_id": sid})
        assert "transcript_path" not in out


class TestCodexRolloutResolverHardening:
    """A hook that raises here skips every guardrail for that event, and a
    lookup charged to every tool call taxes the whole turn."""

    def test_glob_metachars_never_raise(self, codex, tmp_path, monkeypatch):
        from hooks.targets.normalizer import codex_rollout_path

        monkeypatch.setenv("CODEX_HOME", str(tmp_path))
        (tmp_path / "sessions" / "2026" / "08" / "10").mkdir(parents=True)
        for evil in ("**", "*", "?", "[a-z]", "../../etc", "a" * 500, ""):
            assert codex_rollout_path(evil) == ""

    def test_metachar_id_cannot_match_another_session(self, codex, tmp_path, monkeypatch):
        from hooks.targets.normalizer import codex_rollout_path

        monkeypatch.setenv("CODEX_HOME", str(tmp_path))
        d = tmp_path / "sessions" / "2026" / "08" / "10"
        d.mkdir(parents=True)
        real = "019fed35-c6df-7a43-a079-562b82daf86a"
        (d / f"rollout-2026-08-10T21-45-52-{real}.jsonl").write_text("{}\n")
        # One character replaced by a wildcard must NOT resolve to the real file.
        assert codex_rollout_path(real[:-1] + "?") == ""
        assert codex_rollout_path(real).endswith(f"{real}.jsonl")

    def test_tool_events_do_not_pay_for_resolution(self, codex, tmp_path, monkeypatch):
        """PreToolUse/PostToolUse must not touch the filesystem for a value
        their handlers never read — that cost is per tool call."""
        from hooks.targets import normalizer

        monkeypatch.setenv("CODEX_HOME", str(tmp_path))
        calls = []
        monkeypatch.setattr(normalizer, "codex_rollout_path", lambda sid: calls.append(sid) or "")
        for event in ("PreToolUse", "PostToolUse", "UserPromptSubmit", "SessionStart"):
            normalizer.normalize_payload({"hook_event_name": event, "session_id": "abc"})
        assert calls == []
        for event in ("SessionEnd", "Stop", "SubagentStop", "PreCompact"):
            normalizer.normalize_payload({"hook_event_name": event, "session_id": "abc"})
        assert len(calls) == 4

    def test_deep_history_stays_fast(self, codex, tmp_path, monkeypatch):
        """Resolution must not scale with total session history."""
        import time

        from hooks.targets.normalizer import codex_rollout_path

        monkeypatch.setenv("CODEX_HOME", str(tmp_path))
        sessions = tmp_path / "sessions"
        for month in range(1, 9):  # 8 months of history
            for day in range(1, 29):
                d = sessions / "2026" / f"{month:02d}" / f"{day:02d}"
                d.mkdir(parents=True)
                for n in range(10):
                    (d / f"rollout-2026-{month:02d}-{day:02d}T00-00-{n:02d}-old{month}{day}{n}.jsonl").touch()
        sid = "019fed99-aaaa-bbbb-cccc-ddddeeeeffff"
        newest = sessions / "2026" / "08" / "28"
        (newest / f"rollout-2026-08-28T12-00-00-{sid}.jsonl").write_text("{}\n")
        start = time.perf_counter()
        for _ in range(20):
            assert codex_rollout_path(sid)
        elapsed = (time.perf_counter() - start) / 20
        # A full-tree walk of ~2200 files costs milliseconds per call; the
        # newest-first scan is bounded by one day directory.
        assert elapsed < 0.005, f"{elapsed * 1000:.2f} ms/call — resolution is walking history"


class TestSessionIdBannerHost:
    """The banner names the host; saying 'Claude Code' inside codex is a lie."""

    def _banner(self, monkeypatch, target):
        monkeypatch.setenv("AGENTIHOOKS_TARGET", target)
        captured = []
        import hooks.common as common

        monkeypatch.setattr(common, "inject_context", lambda msg, *a, **k: captured.append(msg))
        from hooks.hook_manager import on_session_start

        try:
            on_session_start({"hook_event_name": "SessionStart", "session_id": "sid-1", "cwd": "/tmp"})
        except Exception:
            pass
        return "\n".join(captured)

    def test_codex_banner_names_codex(self, monkeypatch):
        assert "Your Codex session_id" in self._banner(monkeypatch, "codex")

    def test_claude_banner_unchanged(self, monkeypatch):
        assert "Your Claude Code session_id" in self._banner(monkeypatch, "claude")
