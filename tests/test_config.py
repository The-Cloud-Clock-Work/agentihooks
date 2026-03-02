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


class TestSecretsMode:
    """Tests for SECRETS_MODE configuration."""

    def test_secrets_mode_default(self):
        """SECRETS_MODE defaults to 'standard' when env var is not set."""
        with patch.dict(os.environ, {}, clear=False):
            # Remove the env var if it exists
            os.environ.pop("AGENTIHOOKS_SECRETS_MODE", None)
            import importlib

            import hooks.config as cfg

            importlib.reload(cfg)
            assert cfg.SECRETS_MODE == "standard"

    def test_secrets_mode_reads_env(self):
        """SECRETS_MODE reads AGENTIHOOKS_SECRETS_MODE from env."""
        with patch.dict(os.environ, {"AGENTIHOOKS_SECRETS_MODE": "strict"}):
            import importlib

            import hooks.config as cfg

            importlib.reload(cfg)
            assert cfg.SECRETS_MODE == "strict"

    def test_secrets_mode_warn(self):
        """SECRETS_MODE=warn is valid."""
        with patch.dict(os.environ, {"AGENTIHOOKS_SECRETS_MODE": "warn"}):
            import importlib

            import hooks.config as cfg

            importlib.reload(cfg)
            assert cfg.SECRETS_MODE == "warn"

    def test_secrets_mode_off(self):
        """SECRETS_MODE=off is valid."""
        with patch.dict(os.environ, {"AGENTIHOOKS_SECRETS_MODE": "off"}):
            import importlib

            import hooks.config as cfg

            importlib.reload(cfg)
            assert cfg.SECRETS_MODE == "off"

    def test_secrets_mode_invalid_falls_back(self):
        """Invalid SECRETS_MODE falls back to 'standard' (not 'off')."""
        with patch.dict(os.environ, {"AGENTIHOOKS_SECRETS_MODE": "INVALID_VALUE"}):
            import importlib

            import hooks.config as cfg

            importlib.reload(cfg)
            assert cfg.SECRETS_MODE == "standard"

    def test_secrets_mode_case_insensitive(self):
        """SECRETS_MODE is case-insensitive."""
        with patch.dict(os.environ, {"AGENTIHOOKS_SECRETS_MODE": "STRICT"}):
            import importlib

            import hooks.config as cfg

            importlib.reload(cfg)
            assert cfg.SECRETS_MODE == "strict"

    def test_secrets_mode_strips_whitespace(self):
        """SECRETS_MODE strips surrounding whitespace."""
        with patch.dict(os.environ, {"AGENTIHOOKS_SECRETS_MODE": "  warn  "}):
            import importlib

            import hooks.config as cfg

            importlib.reload(cfg)
            assert cfg.SECRETS_MODE == "warn"
