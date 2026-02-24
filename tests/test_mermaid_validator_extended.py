"""Extended tests for hooks.integrations.mermaid_validator module."""

import pytest

pytestmark = pytest.mark.unit


# =============================================================================
# Empty and invalid input
# =============================================================================


class TestMermaidValidatorEdgeCases:
    """Test edge cases and various diagram types."""

    def test_empty_input(self):
        """Empty mermaid content is invalid."""
        from hooks.integrations.mermaid_validator import MermaidValidator

        v = MermaidValidator()
        result = v.validate_mermaid_block("")
        # Empty content triggers GENERIC_001
        assert result.diagram_count == 1
        assert any(i.rule == "GENERIC_001" for i in result.issues)

    def test_unknown_diagram_type(self):
        """Unknown diagram type produces GENERIC_002 error."""
        from hooks.integrations.mermaid_validator import MermaidValidator

        v = MermaidValidator()
        result = v.validate_mermaid_block("notADiagramType\n  A --> B")
        assert any(i.rule == "GENERIC_002" for i in result.issues)

    def test_comment_only_diagram(self):
        """Diagram with only comments is empty."""
        from hooks.integrations.mermaid_validator import MermaidValidator

        v = MermaidValidator()
        result = v.validate_mermaid_block("%% This is a comment\n%% Another comment")
        assert any(i.rule == "GENERIC_001" for i in result.issues)


# =============================================================================
# Gantt chart validation
# =============================================================================


class TestGanttValidation:
    """Test gantt chart validation."""

    def test_valid_gantt(self):
        from hooks.integrations.mermaid_validator import MermaidValidator

        v = MermaidValidator(strict=False)
        diagram = """gantt
    dateFormat YYYY-MM-DD
    title Project Plan
    section Phase 1
    Task A :a1, 2024-01-01, 30d
    Task B :a2, after a1, 20d"""
        result = v.validate_mermaid_block(diagram)
        assert result.diagrams[0].diagram_type == "gantt"
        # No errors (warnings are ok in non-strict)
        errors = [i for i in result.issues if i.severity == "error"]
        assert len(errors) == 0

    def test_gantt_no_section_warning(self):
        """Gantt with tasks but no section gets a warning."""
        from hooks.integrations.mermaid_validator import MermaidValidator

        v = MermaidValidator()
        diagram = """gantt
    dateFormat YYYY-MM-DD
    Task A :a1, 2024-01-01, 30d"""
        result = v.validate_mermaid_block(diagram)
        assert any(i.rule == "GANTT_002" for i in result.issues)

    def test_gantt_missing_dateformat_value(self):
        """Gantt with empty dateFormat gets an error."""
        from hooks.integrations.mermaid_validator import MermaidValidator

        v = MermaidValidator()
        diagram = """gantt
    dateFormat"""
        result = v.validate_mermaid_block(diagram)
        assert any(i.rule == "GANTT_001" for i in result.issues)


# =============================================================================
# Class diagram
# =============================================================================


class TestClassDiagramValidation:
    """Test class diagram validation."""

    def test_valid_class_diagram(self):
        from hooks.integrations.mermaid_validator import MermaidValidator

        v = MermaidValidator()
        diagram = """classDiagram
    Animal <|-- Duck
    Animal <|-- Fish
    Animal : +int age
    Animal : +String gender"""
        result = v.validate_mermaid_block(diagram)
        assert result.diagrams[0].diagram_type == "classDiagram"


# =============================================================================
# State diagram
# =============================================================================


class TestStateDiagramValidation:
    """Test state diagram validation."""

    def test_valid_state_diagram(self):
        from hooks.integrations.mermaid_validator import MermaidValidator

        v = MermaidValidator()
        diagram = """stateDiagram
    [*] --> Still
    Still --> [*]
    Still --> Moving
    Moving --> Still
    Moving --> Crash
    Crash --> [*]"""
        result = v.validate_mermaid_block(diagram)
        assert result.diagrams[0].diagram_type == "stateDiagram"


# =============================================================================
# Timeline
# =============================================================================


class TestTimelineValidation:
    """Test timeline diagram validation."""

    def test_valid_timeline(self):
        from hooks.integrations.mermaid_validator import MermaidValidator

        v = MermaidValidator()
        diagram = """timeline
    title My Timeline
    section Phase 1
        Week 1 : Task A
        Week 2 : Task B
    section Phase 2
        Week 3 : Task C"""
        result = v.validate_mermaid_block(diagram)
        assert result.diagrams[0].diagram_type == "timeline"
        errors = [i for i in result.issues if i.severity == "error"]
        assert len(errors) == 0

    def test_timeline_nested_colon_error(self):
        """Standalone colon in timeline is an error."""
        from hooks.integrations.mermaid_validator import MermaidValidator

        v = MermaidValidator()
        diagram = """timeline
    section Phase 1
        Week 1 : Task
            : Subtask"""
        result = v.validate_mermaid_block(diagram)
        assert any(i.rule == "TIMELINE_001" for i in result.issues)

    def test_timeline_empty_section_warning(self):
        """Empty section produces warning."""
        from hooks.integrations.mermaid_validator import MermaidValidator

        v = MermaidValidator()
        diagram = """timeline
    section Empty Section
    section Another Section
        Week 1 : Task"""
        result = v.validate_mermaid_block(diagram)
        assert any(i.rule == "TIMELINE_002" for i in result.issues)

    def test_timeline_item_missing_colon(self):
        """Item without colon in timeline gets a warning."""
        from hooks.integrations.mermaid_validator import MermaidValidator

        v = MermaidValidator()
        diagram = """timeline
    section Phase 1
        Just some text without colon"""
        result = v.validate_mermaid_block(diagram)
        assert any(i.rule == "TIMELINE_004" for i in result.issues)


# =============================================================================
# Sequence diagram
# =============================================================================


class TestSequenceDiagramValidation:
    """Test sequence diagram validation."""

    def test_valid_sequence(self):
        from hooks.integrations.mermaid_validator import MermaidValidator

        v = MermaidValidator()
        diagram = """sequenceDiagram
    Alice->>Bob: Hello
    Bob-->>Alice: Hi back"""
        result = v.validate_mermaid_block(diagram)
        assert result.diagrams[0].diagram_type == "sequence"

    def test_unclosed_alt_block(self):
        """Unclosed alt block produces SEQ_002 error."""
        from hooks.integrations.mermaid_validator import MermaidValidator

        v = MermaidValidator()
        diagram = """sequenceDiagram
    Alice->>Bob: Request
    alt success
        Bob-->>Alice: OK"""
        result = v.validate_mermaid_block(diagram)
        assert any(i.rule == "SEQ_002" for i in result.issues)

    def test_extra_end_block(self):
        """Extra 'end' without opener produces SEQ_002 error."""
        from hooks.integrations.mermaid_validator import MermaidValidator

        v = MermaidValidator()
        diagram = """sequenceDiagram
    Alice->>Bob: Hello
    end"""
        result = v.validate_mermaid_block(diagram)
        assert any(i.rule == "SEQ_002" for i in result.issues)


# =============================================================================
# Flowchart
# =============================================================================


class TestFlowchartValidation:
    """Test flowchart validation."""

    def test_valid_flowchart(self):
        from hooks.integrations.mermaid_validator import MermaidValidator

        v = MermaidValidator()
        diagram = """flowchart LR
    A[Start] --> B[Process]
    B --> C[End]"""
        result = v.validate_mermaid_block(diagram)
        assert result.valid is True
        assert result.diagrams[0].diagram_type == "flowchart"

    def test_unclosed_bracket_error(self):
        """Unclosed bracket in node definition produces FLOW_001 error."""
        from hooks.integrations.mermaid_validator import MermaidValidator

        v = MermaidValidator()
        diagram = """flowchart TD
    A[Unclosed --> B[OK]"""
        result = v.validate_mermaid_block(diagram)
        assert any(i.rule == "FLOW_001" for i in result.issues)


# =============================================================================
# Markdown content validation
# =============================================================================


class TestMarkdownValidation:
    """Test markdown file/content validation."""

    def test_markdown_with_mermaid_blocks(self):
        from hooks.integrations.mermaid_validator import MermaidValidator

        v = MermaidValidator()
        md = """# My Document

Some text here.

```mermaid
flowchart LR
    A --> B
```

More text.

```mermaid
sequenceDiagram
    Alice->>Bob: Hello
```
"""
        result = v.validate_markdown_content(md)
        assert result.diagram_count == 2

    def test_markdown_no_mermaid(self):
        from hooks.integrations.mermaid_validator import MermaidValidator

        v = MermaidValidator()
        md = """# Just a document

No diagrams here.

```python
print("hello")
```
"""
        result = v.validate_markdown_content(md)
        assert result.diagram_count == 0
        assert result.valid is True

    def test_markdown_unclosed_mermaid_block(self):
        from hooks.integrations.mermaid_validator import MermaidValidator

        v = MermaidValidator()
        md = """# Document

```mermaid
flowchart LR
    A --> B
"""
        result = v.validate_markdown_content(md)
        # Should detect the unclosed block
        assert result.diagram_count == 1

    def test_validate_markdown_file_not_found(self):
        from hooks.integrations.mermaid_validator import MermaidValidator

        v = MermaidValidator()
        result = v.validate_markdown_file("/nonexistent/path/file.md")
        assert result.valid is False
        assert any(i.rule == "FILE_001" for i in result.issues)

    def test_validate_markdown_file_success(self, tmp_path):
        from hooks.integrations.mermaid_validator import MermaidValidator

        v = MermaidValidator()
        f = tmp_path / "test.md"
        f.write_text("# Test\n\n```mermaid\nflowchart LR\n    A --> B\n```\n")
        result = v.validate_markdown_file(str(f))
        assert result.filepath == str(f)
        assert result.diagram_count == 1

    def test_non_strict_mode_allows_warnings(self):
        """Non-strict mode: warnings don't affect validity."""
        from hooks.integrations.mermaid_validator import MermaidValidator

        v = MermaidValidator(strict=False)
        # Gantt without section produces warning but no error
        diagram = """gantt
    dateFormat YYYY-MM-DD
    Task A :a1, 2024-01-01, 30d"""
        result = v.validate_mermaid_block(diagram)
        has_warning = any(i.severity == "warning" for i in result.issues)
        has_error = any(i.severity == "error" for i in result.issues)
        assert has_warning
        assert not has_error
        assert result.valid is True


# =============================================================================
# Convenience functions
# =============================================================================


class TestConvenienceFunctions:
    """Test module-level convenience functions."""

    def test_validate_markdown_file_function(self, tmp_path):
        from hooks.integrations.mermaid_validator import validate_markdown_file

        f = tmp_path / "test.md"
        f.write_text("# Test\n\n```mermaid\nflowchart LR\n    A --> B\n```\n")
        result = validate_markdown_file(str(f))
        assert result.diagram_count == 1

    def test_validate_mermaid_content_raw(self):
        from hooks.integrations.mermaid_validator import validate_mermaid_content

        result = validate_mermaid_content("flowchart LR\n    A --> B")
        assert result.diagram_count == 1

    def test_validate_mermaid_content_markdown(self):
        from hooks.integrations.mermaid_validator import validate_mermaid_content

        md = "```mermaid\nflowchart LR\n    A --> B\n```"
        result = validate_mermaid_content(md)
        assert result.diagram_count == 1


# =============================================================================
# Data class methods
# =============================================================================


class TestDataclasses:
    """Test to_dict() methods on dataclasses."""

    def test_validation_issue_to_dict(self):
        from hooks.integrations.mermaid_validator import ValidationIssue

        issue = ValidationIssue(
            diagram_index=0,
            line_number=5,
            severity="error",
            rule="TEST_001",
            message="Test error",
            snippet="bad code",
            suggestion="fix it",
        )
        d = issue.to_dict()
        assert d["rule"] == "TEST_001"
        assert d["severity"] == "error"

    def test_diagram_info_to_dict(self):
        from hooks.integrations.mermaid_validator import DiagramInfo

        info = DiagramInfo(
            index=0,
            diagram_type="flowchart",
            start_line=1,
            end_line=5,
            content="flowchart LR\n    A --> B",
            lines=["flowchart LR", "    A --> B"],
        )
        d = info.to_dict()
        assert d["diagram_type"] == "flowchart"
        assert d["line_count"] == 2

    def test_validation_result_to_dict(self):
        from hooks.integrations.mermaid_validator import ValidationResult

        result = ValidationResult(valid=True, diagram_count=2, issues=[], diagrams=[])
        d = result.to_dict()
        assert d["valid"] is True
        assert d["diagram_count"] == 2
