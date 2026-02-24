"""Tests for hooks.tool_memory module."""

import json
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit


class TestToolMemory:
    """Test tool memory system."""

    def test_import(self):
        """Module can be imported."""
        from hooks.tool_memory import inject_memory, record_error, scan_transcript

        assert callable(inject_memory)
        assert callable(record_error)
        assert callable(scan_transcript)

    def test_record_error_creates_entry(self, tmp_path):
        """record_error() stores error data."""
        mem_file = tmp_path / "tool_memory.ndjson"
        with patch("hooks.tool_memory.MEMORY_PATH", mem_file):
            from hooks.tool_memory import record_error

            # record_error takes a payload dict
            payload = {
                "tool_name": "Write",
                "tool_input": {"file_path": "/tmp/test.txt"},
                "tool_response": {"is_error": True, "content": "File not found"},
                "session_id": "test-session",
            }
            record_error(payload)
            # Verify it wrote an entry
            assert mem_file.exists()
            lines = mem_file.read_text().strip().split("\n")
            assert len(lines) == 1
            entry = json.loads(lines[0])
            assert entry["tool"] == "Write"
            assert "File not found" in entry["error"]
