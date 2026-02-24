"""Tests for hooks.integrations.base module."""

import pytest

pytestmark = pytest.mark.unit


class TestIntegrationBase:
    """Test the integration base class."""

    def test_import(self):
        """IntegrationBase and registry can be imported."""
        from hooks.integrations.base import IntegrationBase, IntegrationRegistry

        assert IntegrationBase is not None
        assert IntegrationRegistry is not None

    def test_config_status_dataclass(self):
        """ConfigStatus dataclass works."""
        from hooks.integrations.base import ConfigStatus

        status = ConfigStatus(integration_name="test", is_configured=True)
        assert status.is_configured is True
        assert status.integration_name == "test"

    def test_env_var_status_dataclass(self):
        """EnvVarStatus dataclass works."""
        from hooks.integrations.base import EnvVarStatus

        status = EnvVarStatus(name="TEST_VAR", description="A test var", is_set=False, is_required=True)
        assert status.name == "TEST_VAR"
        assert status.is_required is True
        assert status.is_set is False
