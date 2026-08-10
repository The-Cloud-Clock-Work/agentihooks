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

    def test_corrupt_first_line_still_detects_codex(self, tmp_path):
        # A rollout read mid-write can have a truncated/corrupt first line.
        # detection must look past it instead of misdetecting as claude.
        p = tmp_path / "corrupt_first.jsonl"
        p.write_text(
            "not valid json{{{\n"
            '{"type": "response_item", "payload": {"type": "message", "id": "m1", '
            '"role": "user", "content": [{"type": "input_text", "text": "hi"}]}}\n'
        )
        assert detect_transcript_format(p) == "codex"
        recs = list(iter_transcript_records(p))
        assert any(r["kind"] == "user_text" for r in recs)

    def test_world_state_first_line_detects_codex(self, tmp_path):
        p = tmp_path / "world_state_first.jsonl"
        p.write_text(
            '{"type": "world_state", "payload": {}}\n'
            '{"type": "response_item", "payload": {"type": "message", "id": "m1", '
            '"role": "user", "content": [{"type": "input_text", "text": "hi"}]}}\n'
        )
        assert detect_transcript_format(p) == "codex"

    def test_invalid_utf8_bytes_no_exception(self, tmp_path):
        p = tmp_path / "bad_utf8.jsonl"
        p.write_bytes(b'{"type": "user", "message": {"content": [{"type": "text", "text": "bad byte \xff here"}]}}\n')
        recs = list(iter_transcript_records(p))
        assert recs and recs[0]["kind"] == "user_text"


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
        assert "meta" in kinds and "token_usage" in kinds
        # The fixture's task_complete repeats the same reply the response_item
        # message already yielded as assistant_text — turn_complete must be
        # suppressed so consumers don't double-count the turn.
        assert "turn_complete" not in kinds
        assert kinds.count("assistant_text") == 1
        # Injected context (role=developer) must NOT masquerade as assistant text.
        system = [r for r in recs if r["kind"] == "system_text"]
        assert any("CONTEXT INJECTION" in r["text"] for r in system)
        assistant = "\n".join(r["text"] for r in recs if r["kind"] == "assistant_text")
        assert "@lesson" in assistant and "CONTEXT INJECTION" not in assistant
        call = next(r for r in recs if r["kind"] == "tool_call")
        result = next(r for r in recs if r["kind"] == "tool_result")
        assert call["tool_name"] == "shell"
        assert call["tool_use_id"] == result["tool_use_id"] == "c1"

    def test_codex_truncated_rollout_falls_back_to_turn_complete(self, tmp_path):
        # No response_item assistant message landed before task_complete —
        # the reader must still surface the turn via the fallback text.
        p = tmp_path / "truncated.jsonl"
        p.write_text(
            "\n".join(
                [
                    '{"type": "session_meta", "payload": {"id": "s2", "cwd": "/w"}}',
                    '{"type": "response_item", "payload": {"type": "message", "id": "m1", '
                    '"role": "user", "content": [{"type": "input_text", "text": "fix it"}]}}',
                    '{"type": "event_msg", "payload": {"type": "task_complete", "turn_id": "t1", '
                    '"last_agent_message": "Truncated response"}}',
                ]
            )
            + "\n"
        )
        recs = list(iter_transcript_records(p))
        kinds = [r["kind"] for r in recs]
        assert kinds.count("assistant_text") == 0
        assert kinds.count("turn_complete") == 1
        turn_complete = next(r for r in recs if r["kind"] == "turn_complete")
        assert turn_complete["text"] == "Truncated response"

    def test_claude_bare_string_message_yields_text(self, tmp_path):
        # Some claude entries carry `message` as a plain string rather than
        # {content: [...]} — a marker inside it must not be dropped.
        p = tmp_path / "bare_string.jsonl"
        p.write_text(
            '{"type": "assistant", "message": "Done.\\n<!-- @lesson -->\\nbare string message\\n<!-- @/lesson -->"}\n'
        )
        recs = list(iter_transcript_records(p))
        assert len(recs) == 1
        assert recs[0]["kind"] == "assistant_text"
        assert "@lesson" in recs[0]["text"]


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
