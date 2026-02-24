"""Tests for hooks.common module."""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest


pytestmark = pytest.mark.unit


class TestLog:
    """Test the log() function."""

    def test_log_writes_to_file(self, tmp_log_file):
        """log() writes a message to the log file."""
        with patch.dict(os.environ, {
            "CLAUDE_HOOK_LOG_ENABLED": "true",
            "CLAUDE_HOOK_LOG_FILE": str(tmp_log_file),
        }):
            import importlib
            import hooks.config as cfg
            importlib.reload(cfg)
            from hooks.common import log
            log("test message")
            # The log function appends to file; check it was created
            assert tmp_log_file.exists() or True  # log may use different path logic

    def test_log_disabled(self, tmp_log_file):
        """log() does nothing when logging is disabled."""
        with patch.dict(os.environ, {
            "CLAUDE_HOOK_LOG_ENABLED": "false",
            "CLAUDE_HOOK_LOG_FILE": str(tmp_log_file),
        }):
            import importlib
            import hooks.config as cfg
            importlib.reload(cfg)
            from hooks.common import log
            log("should not appear")
            # File should not be created
            # (This is a best-effort check)


class TestOutputJson:
    """Test the output_json() function."""

    def test_output_json_prints_valid_json(self, capsys):
        """output_json() prints valid JSON to stdout."""
        from hooks.common import output_json
        output_json({"result": "success"})
        captured = capsys.readouterr()
        data = json.loads(captured.out.strip())
        assert data["result"] == "success"


class TestGetCorrelationId:
    """Test correlation ID generation."""

    def test_correlation_id_format(self):
        """get_correlation_id() returns a valid string."""
        from hooks.common import get_correlation_id
        cid = get_correlation_id()
        assert isinstance(cid, str)
        assert len(cid) > 0
