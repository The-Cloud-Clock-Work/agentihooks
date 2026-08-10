"""Tests for the unified transcript-record API (claude transcripts + codex rollouts)."""

from pathlib import Path

from hooks.memory.transcript_reader import detect_transcript_format, iter_transcript_records

FIXTURES = Path(__file__).parent / "fixtures"
CLAUDE = FIXTURES / "claude_transcript_sample.jsonl"
CODEX = FIXTURES / "codex_rollout_sample.jsonl"


class TestDetection:
    def test_formats_detected(self):
        assert detect_transcript_format(CLAUDE) == "claude"
        assert detect_transcript_format(CODEX) == "codex"

    def test_missing_file_yields_nothing(self, tmp_path):
        assert list(iter_transcript_records(tmp_path / "nope.jsonl")) == []


class TestSameScenarioBothFormats:
    """Both fixtures encode the same conceptual scenario: user turn, assistant
    text with an embedded @lesson marker, one tool call, one tool result."""

    def test_claude_records(self):
        recs = list(iter_transcript_records(CLAUDE))
        kinds = [r["kind"] for r in recs]
        assert "user_text" in kinds and "assistant_text" in kinds
        assert "tool_call" in kinds and "tool_result" in kinds
        call = next(r for r in recs if r["kind"] == "tool_call")
        result = next(r for r in recs if r["kind"] == "tool_result")
        assert call["tool_name"] == "Bash"
        assert call["tool_use_id"] == result["tool_use_id"] == "tu1"
        assert result["is_error"] is True
        assistant = "\n".join(r["text"] for r in recs if r["kind"] == "assistant_text")
        assert "@lesson" in assistant

    def test_codex_records(self):
        recs = list(iter_transcript_records(CODEX))
        kinds = [r["kind"] for r in recs]
        assert "meta" in kinds and "token_usage" in kinds and "turn_complete" in kinds
        # Injected context (role=developer) must NOT masquerade as assistant text.
        system = [r for r in recs if r["kind"] == "system_text"]
        assert any("CONTEXT INJECTION" in r["text"] for r in system)
        assistant = "\n".join(r["text"] for r in recs if r["kind"] == "assistant_text")
        assert "@lesson" in assistant and "CONTEXT INJECTION" not in assistant
        call = next(r for r in recs if r["kind"] == "tool_call")
        result = next(r for r in recs if r["kind"] == "tool_result")
        assert call["tool_name"] == "shell"
        assert call["tool_use_id"] == result["tool_use_id"] == "c1"


class TestConsumers:
    def test_brain_writer_finds_markers_in_codex_rollout(self):
        from hooks.context.brain_writer_hook import _parse_transcript_for_markers

        markers = _parse_transcript_for_markers(str(CODEX), max_markers=5)
        assert len(markers) == 1
        assert markers[0]["type"] == "lesson"
        assert "response_item" in markers[0]["content"]

    def test_brain_writer_finds_markers_in_claude_transcript(self):
        from hooks.context.brain_writer_hook import _parse_transcript_for_markers

        markers = _parse_transcript_for_markers(str(CLAUDE), max_markers=5)
        assert len(markers) == 1
        assert markers[0]["type"] == "lesson"

    def test_tool_memory_scan_claude_errors(self):
        from hooks.tool_memory import _scan_transcript_for_errors

        entries = _scan_transcript_for_errors(str(CLAUDE), session_id="s")
        assert len(entries) == 1
        assert entries[0]["tool"] == "Bash"
        assert "command not found" in entries[0]["error"]

    def test_tool_memory_scan_codex_no_false_positives(self):
        from hooks.tool_memory import _scan_transcript_for_errors

        # Codex outputs carry no is_error flag — scan must stay silent, not guess.
        assert _scan_transcript_for_errors(str(CODEX), session_id="s") == []

    def test_auto_save_reads_both(self):
        from hooks.memory.auto_save import _read_transcript

        for fixture in (CLAUDE, CODEX):
            entries = _read_transcript(fixture)
            types = {e["type"] for e in entries}
            assert {"user", "assistant"} <= types, fixture.name
