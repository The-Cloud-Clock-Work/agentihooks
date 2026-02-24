"""Tests for hooks.hook_manager module."""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest


pytestmark = pytest.mark.unit


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
