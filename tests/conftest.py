"""Shared test fixtures for agentihooks."""

import os
from unittest.mock import patch

import pytest


@pytest.fixture
def mock_env():
    """Provide a clean environment for tests."""
    env = {
        "CLAUDE_HOOK_LOG_ENABLED": "true",
        "CLAUDE_HOOK_LOG_FILE": "/tmp/test-hooks.log",
    }
    with patch.dict(os.environ, env, clear=False):
        yield env


@pytest.fixture
def tmp_log_file(tmp_path):
    """Provide a temporary log file path."""
    return tmp_path / "test.log"


@pytest.fixture
def sample_transcript_entry():
    """A sample transcript JSONL entry."""
    return {
        "type": "user",
        "message": {"content": [{"type": "text", "text": "Hello Claude"}]},
        "timestamp": "2026-01-15T10:00:00Z",
        "uuid": "test-uuid-001",
    }


@pytest.fixture
def sample_tool_use_event():
    """A sample PreToolUse hook event."""
    return {
        "session_id": "test-session",
        "tool_name": "Write",
        "tool_input": {"file_path": "/tmp/test.txt", "content": "hello"},
    }
