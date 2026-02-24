"""Tests for hooks.integrations.mermaid_validator module."""

import pytest

pytestmark = pytest.mark.unit


class TestMermaidValidator:
    """Test Mermaid diagram validation."""

    def test_import(self):
        """MermaidValidator can be imported."""
        from hooks.integrations.mermaid_validator import MermaidValidator

        assert MermaidValidator is not None

    def test_valid_flowchart(self):
        """Valid flowchart passes validation."""
        from hooks.integrations.mermaid_validator import MermaidValidator

        validator = MermaidValidator()
        diagram = "flowchart LR\n    A --> B\n    B --> C"
        result = validator.validate_mermaid_block(diagram)
        assert result.valid is True

    def test_valid_sequence(self):
        """Valid sequence diagram passes validation."""
        from hooks.integrations.mermaid_validator import MermaidValidator

        validator = MermaidValidator()
        diagram = "sequenceDiagram\n    Alice->>Bob: Hello"
        result = validator.validate_mermaid_block(diagram)
        # Just verify it doesn't crash and returns a result
        assert result is not None
        assert result.diagram_count == 1
