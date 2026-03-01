"""Tests for hooks.hook_manager module."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_PROJECT_ROOT = Path(__file__).parent.parent


class TestHookManager:
    """Test the central event dispatcher."""

    def test_event_handlers_dict_exists(self):
        """EVENT_HANDLERS is defined and non-empty."""
        from hooks.hook_manager import EVENT_HANDLERS

        assert isinstance(EVENT_HANDLERS, dict)
        assert len(EVENT_HANDLERS) > 0

    def test_known_events(self):
        """Standard hook events are registered."""
        from hooks.hook_manager import EVENT_HANDLERS

        expected_events = ["PreToolUse", "PostToolUse", "Stop"]
        for event in expected_events:
            assert event in EVENT_HANDLERS, f"Missing handler for {event}"

    def test_main_requires_stdin(self):
        """main() reads from stdin for event data."""
        from hooks.hook_manager import main

        assert callable(main)

    def test_block_action_exception_exists(self):
        """BlockAction is importable and is an Exception subclass."""
        from hooks.hook_manager import BlockAction

        assert issubclass(BlockAction, Exception)


class TestBlockActionIntegration:
    """Integration tests: BlockAction propagates through main() with exit 2."""

    def _run(self, payload: dict) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "hooks"],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            cwd=_PROJECT_ROOT,
        )

    def _bash_payload(self, command: str) -> dict:
        return {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "session_id": "test",
            "transcript_path": "",
        }

    def _write_payload(self, content: str) -> dict:
        return {
            "hook_event_name": "PreToolUse",
            "tool_name": "Write",
            "tool_input": {"file_path": "/tmp/test.py", "content": content},
            "session_id": "test",
            "transcript_path": "",
        }

    def test_bash_secret_exits_2(self):
        """Bash command containing an inline secret is blocked (exit 2)."""
        key_name = "aws_secret" + "_access_key"
        key_val = "wJalrXUtnFEMI" + "/K7MDENG/bPxRfiCYEXAMPLEKEY"
        result = self._run(self._bash_payload(f"export {key_name}={key_val}"))
        assert result.returncode == 2
        assert "BLOCKED" in result.stdout

    def test_write_secret_exits_2(self):
        """Write content containing a credential is blocked (exit 2)."""
        key = "AKIA" + "IOSFODNN7EXAMPLE"
        result = self._run(self._write_payload(f"my_key = '{key}'"))
        assert result.returncode == 2
        assert "BLOCKED" in result.stdout

    def test_block_stdout_names_the_pattern(self):
        """The block message names which pattern was detected."""
        key = "AKIA" + "IOSFODNN7EXAMPLE"
        result = self._run(self._write_payload(f"my_key = '{key}'"))
        assert result.returncode == 2
        assert "aws_access_key" in result.stdout

    def test_clean_bash_exits_0(self):
        """A clean Bash command is not blocked."""
        result = self._run(self._bash_payload("ls -la /tmp"))
        assert result.returncode == 0

    def test_clean_write_exits_0(self):
        """Clean Write content is not blocked."""
        result = self._run(self._write_payload("x = 1\n"))
        assert result.returncode == 0
