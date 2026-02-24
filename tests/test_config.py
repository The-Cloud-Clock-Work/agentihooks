"""Tests for hooks.config module."""

import os
from unittest.mock import patch

import pytest


pytestmark = pytest.mark.unit


class TestConfig:
    """Test configuration loading."""

    def test_log_enabled_default(self):
        """LOG_ENABLED reads from CLAUDE_HOOK_LOG_ENABLED."""
        with patch.dict(os.environ, {"CLAUDE_HOOK_LOG_ENABLED": "true"}):
            # Re-import to pick up env
            import importlib
            import hooks.config as cfg
            importlib.reload(cfg)
            assert cfg.LOG_ENABLED is True

    def test_log_enabled_false(self):
        """LOG_ENABLED is False when env var is not 'true'."""
        with patch.dict(os.environ, {"CLAUDE_HOOK_LOG_ENABLED": "false"}):
            import importlib
            import hooks.config as cfg
            importlib.reload(cfg)
            assert cfg.LOG_ENABLED is False

    def test_log_file_default(self):
        """LOG_FILE has a default value."""
        import hooks.config as cfg
        assert cfg.LOG_FILE is not None

    def test_memory_auto_save_default(self):
        """MEMORY_AUTO_SAVE reads from environment."""
        with patch.dict(os.environ, {"MEMORY_AUTO_SAVE": "true"}):
            import importlib
            import hooks.config as cfg
            importlib.reload(cfg)
            assert cfg.MEMORY_AUTO_SAVE is True
