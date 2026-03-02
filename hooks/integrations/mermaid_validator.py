"""Mermaid diagram syntax validator.

This module provides validation for Mermaid diagrams embedded in markdown files.
It catches syntax errors before documents are uploaded to Confluence or created as PRs.

Usage:
    from hooks.integrations.mermaid_validator import validate_markdown_file, validate_mermaid_content

    # Validate a markdown file
    result = validate_markdown_file("/path/to/document.md")
    if not result.valid:
        for issue in result.issues:
            print(f"Error at line {issue.line_number}: {issue.message}")

    # Validate raw mermaid content
    result = validate_mermaid_content("graph TD\\n  A --> B")
"""

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class ValidationIssue:
    """A single validation issue found in a Mermaid diagram."""

    diagram_index: int  # Which diagram (0-based)
    line_number: int  # Line within the diagram (1-based)
    severity: str  # "error" | "warning"
    rule: str  # Rule ID (e.g., "TIMELINE_001")
    message: str  # Human-readable error
    snippet: str  # The problematic line
    suggestion: str  # How to fix it

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class DiagramInfo:
    """Metadata about a parsed Mermaid diagram."""

    index: int  # Position in the document (0-based)
    diagram_type: str  # "flowchart", "timeline", "sequence", etc.
    start_line: int  # Line number in source markdown (1-based)
    end_line: int  # Line number in source markdown (1-based)
    content: str  # Raw diagram content (without code fence)
    lines: List[str]  # Individual lines of the diagram

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "index": self.index,
            "diagram_type": self.diagram_type,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "line_count": len(self.lines),
        }


@dataclass
class ValidationResult:
    """Result of validating Mermaid diagrams in a document."""

    valid: bool
    diagram_count: int
    issues: List[ValidationIssue] = field(default_factory=list)
    diagrams: List[DiagramInfo] = field(default_factory=list)
    filepath: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "valid": self.valid,
            "diagram_count": self.diagram_count,
            "issues": [issue.to_dict() for issue in self.issues],
            "diagrams": [d.to_dict() for d in self.diagrams],
            "filepath": self.filepath,
        }


class MermaidValidator:
    """Validates Mermaid diagram syntax."""

    # Supported diagram types and their detection patterns
    DIAGRAM_TYPES = {
        "flowchart": r"^(graph|flowchart)\s+(TD|TB|BT|RL|LR)",
        "sequence": r"^sequenceDiagram",
        "timeline": r"^timeline",
        "gantt": r"^gantt",
        "classDiagram": r"^classDiagram",
        "stateDiagram": r"^stateDiagram",
        "erDiagram": r"^erDiagram",
        "pie": r"^pie",
        "mindmap": r"^mindmap",
        "gitGraph": r"^gitGraph",
        "journey": r"^journey",
        "quadrantChart": r"^quadrantChart",
        "requirementDiagram": r"^requirementDiagram",
        "c4Context": r"^C4Context",
        "sankey": r"^sankey",
        "block": r"^block-beta",
        "architecture": r"^architecture-beta",
        "zenuml": r"^zenuml",
        "xychart": r"^xychart-beta",
        "packet": r"^packet-beta",
        "kanban": r"^kanban",
    }

    def __init__(self, strict: bool = True):
        """Initialize validator.

        Args:
            strict: If True, warnings are treated as errors when determining validity
        """
        self.strict = strict

    def validate_markdown_file(self, filepath: str) -> ValidationResult:
        """Validate all Mermaid diagrams in a markdown file.

        Args:
            filepath: Path to the markdown file

        Returns:
            ValidationResult with issues found
        """
        path = Path(filepath)
        if not path.exists():
            return ValidationResult(
                valid=False,
                diagram_count=0,
                issues=[
                    ValidationIssue(
                        diagram_index=-1,
                        line_number=0,
                        severity="error",
                        rule="FILE_001",
                        message=f"File not found: {filepath}",
                        snippet="",
                        suggestion="Check the file path and ensure the file exists",
                    )
                ],
                filepath=filepath,
            )

        try:
            content = path.read_text(encoding="utf-8")
        except Exception as e:
            return ValidationResult(
                valid=False,
                diagram_count=0,
                issues=[
                    ValidationIssue(
                        diagram_index=-1,
                        line_number=0,
                        severity="error",
                        rule="FILE_002",
                        message=f"Error reading file: {str(e)}",
                        snippet="",
                        suggestion="Check file permissions and encoding",
                    )
                ],
                filepath=filepath,
            )

        result = self.validate_markdown_content(content)
        result.filepath = filepath
        return result

    def validate_markdown_content(self, content: str) -> ValidationResult:
        """Validate all Mermaid diagrams in markdown content.

        Args:
            content: Raw markdown content

        Returns:
            ValidationResult with issues found
        """
        diagrams = self._extract_mermaid_blocks(content)
        all_issues: List[ValidationIssue] = []

        for diagram in diagrams:
            issues = self._validate_diagram(diagram)
            all_issues.extend(issues)

        # Determine validity based on severity and strict mode
        if self.strict:
            valid = len(all_issues) == 0
        else:
            valid = len([i for i in all_issues if i.severity == "error"]) == 0

        return ValidationResult(
            valid=valid,
            diagram_count=len(diagrams),
            issues=all_issues,
            diagrams=diagrams,
        )

    def validate_mermaid_block(self, mermaid_content: str) -> ValidationResult:
        """Validate a single Mermaid diagram block.

        Args:
            mermaid_content: Raw Mermaid diagram content (without code fence)

        Returns:
            ValidationResult with issues found
        """
        lines = mermaid_content.strip().split("\n")
        diagram = DiagramInfo(
            index=0,
            diagram_type=self._detect_diagram_type(lines),
            start_line=1,
            end_line=len(lines),
            content=mermaid_content,
            lines=lines,
        )

        issues = self._validate_diagram(diagram)

        if self.strict:
            valid = len(issues) == 0
        else:
            valid = len([i for i in issues if i.severity == "error"]) == 0

        return ValidationResult(valid=valid, diagram_count=1, issues=issues, diagrams=[diagram])

    def _extract_mermaid_blocks(self, content: str) -> List[DiagramInfo]:
        """Extract all Mermaid code blocks from markdown content.

        Args:
            content: Markdown content

        Returns:
            List of DiagramInfo objects
        """
        diagrams = []
        lines = content.split("\n")

        # Pattern to match mermaid code fence start
        fence_start_pattern = re.compile(r"^```\s*mermaid\s*$", re.IGNORECASE)
        fence_end_pattern = re.compile(r"^```\s*$")

        in_mermaid_block = False
        current_block_lines: List[str] = []
        block_start_line = 0
        diagram_index = 0

        for i, line in enumerate(lines):
            if not in_mermaid_block:
                if fence_start_pattern.match(line.strip()):
                    in_mermaid_block = True
                    block_start_line = i + 1  # 1-based line number
                    current_block_lines = []
            else:
                if fence_end_pattern.match(line.strip()):
                    # End of mermaid block
                    in_mermaid_block = False
                    diagram_content = "\n".join(current_block_lines)
                    diagram_lines = current_block_lines.copy()

                    diagram = DiagramInfo(
                        index=diagram_index,
                        diagram_type=self._detect_diagram_type(diagram_lines),
                        start_line=block_start_line + 1,  # +1 because first line is after ```mermaid
                        end_line=i,  # Line before closing ```
                        content=diagram_content,
                        lines=diagram_lines,
                    )
                    diagrams.append(diagram)
                    diagram_index += 1
                    current_block_lines = []
                else:
                    current_block_lines.append(line)

        # Check for unclosed mermaid block
        if in_mermaid_block:
            # Create a diagram with the unclosed content and add an error
            diagram = DiagramInfo(
                index=diagram_index,
                diagram_type=self._detect_diagram_type(current_block_lines),
                start_line=block_start_line + 1,
                end_line=len(lines),
                content="\n".join(current_block_lines),
                lines=current_block_lines,
            )
            diagrams.append(diagram)

        return diagrams

    def _detect_diagram_type(self, lines: List[str]) -> str:
        """Detect the type of Mermaid diagram from its content.

        Args:
            lines: Lines of the diagram content

        Returns:
            Diagram type string (e.g., "flowchart", "timeline")
        """
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("%%"):
                continue  # Skip empty lines and comments

            for diagram_type, pattern in self.DIAGRAM_TYPES.items():
                if re.match(pattern, stripped, re.IGNORECASE):
                    return diagram_type

            # If first non-empty non-comment line doesn't match, it's unknown
            break

        return "unknown"

    def _validate_diagram(self, diagram: DiagramInfo) -> List[ValidationIssue]:
        """Validate a single diagram based on its type.

        Args:
            diagram: DiagramInfo to validate

        Returns:
            List of ValidationIssue objects
        """
        issues: List[ValidationIssue] = []

        # Generic validations first
        issues.extend(self._validate_generic(diagram))

        # Type-specific validations
        if diagram.diagram_type == "timeline":
            issues.extend(self._validate_timeline(diagram))
        elif diagram.diagram_type == "flowchart":
            issues.extend(self._validate_flowchart(diagram))
        elif diagram.diagram_type == "sequence":
            issues.extend(self._validate_sequence(diagram))
        elif diagram.diagram_type == "gantt":
            issues.extend(self._validate_gantt(diagram))
        elif diagram.diagram_type == "classDiagram":
            issues.extend(self._validate_class_diagram(diagram))
        elif diagram.diagram_type == "stateDiagram":
            issues.extend(self._validate_state_diagram(diagram))

        return issues

    def _validate_generic(self, diagram: DiagramInfo) -> List[ValidationIssue]:
        """Generic validations applicable to all diagram types.

        Args:
            diagram: DiagramInfo to validate

        Returns:
            List of ValidationIssue objects
        """
        issues = []

        # GENERIC_001: Empty diagram
        non_empty_lines = [line for line in diagram.lines if line.strip() and not line.strip().startswith("%%")]
        if len(non_empty_lines) == 0:
            issues.append(
                ValidationIssue(
                    diagram_index=diagram.index,
                    line_number=diagram.start_line,
                    severity="error",
                    rule="GENERIC_001",
                    message="Empty diagram - no content found",
                    snippet="(empty)",
                    suggestion="Add diagram content after the diagram type declaration",
                )
            )

        # GENERIC_002: Unknown diagram type
        if diagram.diagram_type == "unknown" and len(non_empty_lines) > 0:
            first_line = non_empty_lines[0] if non_empty_lines else ""
            issues.append(
                ValidationIssue(
                    diagram_index=diagram.index,
                    line_number=diagram.start_line,
                    severity="error",
                    rule="GENERIC_002",
                    message="Unknown or missing diagram type declaration",
                    snippet=first_line[:50] + ("..." if len(first_line) > 50 else ""),
                    suggestion="Start with a valid diagram type: graph, flowchart, sequenceDiagram, timeline, gantt, classDiagram, etc.",
                )
            )

        return issues

    def _validate_timeline(self, diagram: DiagramInfo) -> List[ValidationIssue]:
        """Validate Mermaid timeline syntax.

        VALID timeline syntax:
            timeline
                title My Timeline
                section Phase 1
                    Week 1 : Task description
                    Week 2 : Another task
                section Phase 2
                    Week 3 : Final task

        INVALID (nested colons):
            timeline
                section Phase 1
                    Week 1: Task
                        : Subtask      <- ERROR: Nested items not allowed
                        : Another sub  <- ERROR: Standalone colon invalid

        Args:
            diagram: DiagramInfo to validate

        Returns:
            List of ValidationIssue objects
        """
        issues = []
        has_section = False
        section_has_items = False
        current_section_line = 0

        for i, line in enumerate(diagram.lines):
            stripped = line.strip()
            line_num = diagram.start_line + i

            # Skip empty lines and comments
            if not stripped or stripped.startswith("%%"):
                continue

            # Skip the timeline declaration itself
            if stripped.lower() == "timeline":
                continue

            # Skip title
            if stripped.lower().startswith("title"):
                continue

            # TIMELINE_001: Detect nested/standalone colon entries
            # These are lines that START with a colon (not part of "Label : Desc" format)
            if stripped.startswith(":") and not stripped.startswith("::"):
                issues.append(
                    ValidationIssue(
                        diagram_index=diagram.index,
                        line_number=line_num,
                        severity="error",
                        rule="TIMELINE_001",
                        message="Invalid nested colon syntax. Timeline items cannot have sub-items.",
                        snippet=line.rstrip(),
                        suggestion="Combine into single line: 'Label : Description'. Timeline doesn't support nested items.",
                    )
                )
                continue

            # Track sections
            if stripped.lower().startswith("section"):
                # Check if previous section had items
                if has_section and not section_has_items:
                    issues.append(
                        ValidationIssue(
                            diagram_index=diagram.index,
                            line_number=current_section_line,
                            severity="warning",
                            rule="TIMELINE_002",
                            message="Section has no items",
                            snippet=diagram.lines[current_section_line - diagram.start_line].rstrip(),
                            suggestion="Add timeline items under this section using 'Label : Description' format",
                        )
                    )
                has_section = True
                section_has_items = False
                current_section_line = line_num
                continue

            # TIMELINE_003: Check item format (should be "Label : Description")
            # Valid items have text, colon, more text
            if ":" in stripped:
                # Check if it follows the pattern: text : text
                parts = stripped.split(":", 1)
                if len(parts) == 2:
                    label = parts[0].strip()
                    description = parts[1].strip()

                    if not label:
                        # This catches ": description" format (starts with colon)
                        # Already handled by TIMELINE_001 above
                        pass
                    elif not description:
                        issues.append(
                            ValidationIssue(
                                diagram_index=diagram.index,
                                line_number=line_num,
                                severity="warning",
                                rule="TIMELINE_003",
                                message="Timeline item has empty description",
                                snippet=line.rstrip(),
                                suggestion=f"Add description after colon: '{label} : Your description here'",
                            )
                        )
                    else:
                        section_has_items = True
            else:
                # Line without colon - could be valid continuation or error
                # In Mermaid timeline, standalone text without colon is sometimes valid
                # but usually indicates missing structure
                if has_section and not stripped.lower().startswith("section"):
                    # It's a potential item line without proper format
                    issues.append(
                        ValidationIssue(
                            diagram_index=diagram.index,
                            line_number=line_num,
                            severity="warning",
                            rule="TIMELINE_004",
                            message="Timeline item missing colon separator",
                            snippet=line.rstrip(),
                            suggestion=f"Use format: '{stripped} : Description' or move to previous line",
                        )
                    )

        # Check last section for items
        if has_section and not section_has_items:
            issues.append(
                ValidationIssue(
                    diagram_index=diagram.index,
                    line_number=current_section_line,
                    severity="warning",
                    rule="TIMELINE_002",
                    message="Section has no items",
                    snippet=diagram.lines[current_section_line - diagram.start_line].rstrip()
                    if current_section_line - diagram.start_line < len(diagram.lines)
                    else "",
                    suggestion="Add timeline items under this section using 'Label : Description' format",
                )
            )

        return issues

    def _validate_flowchart(self, diagram: DiagramInfo) -> List[ValidationIssue]:
        """Validate Mermaid flowchart/graph syntax.

        Args:
            diagram: DiagramInfo to validate

        Returns:
            List of ValidationIssue objects
        """
        issues = []
        defined_nodes = set()
        referenced_nodes = set()

        # Patterns
        node_def_pattern = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)[\[\(\{]")
        connection_pattern = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*(?:-->|---|==>|-.->|--x|--o|<-->)")
        target_pattern = re.compile(
            r"(?:-->|---|==>|-.->|--x|--o|<-->)\s*(?:\|[^|]*\|)?\s*([A-Za-z_][A-Za-z0-9_]*)"
        )

        # Track bracket balance
        bracket_types = {"[": "]", "(": ")", "{": "}", "[[": "]]", "((": "))"}

        for i, line in enumerate(diagram.lines):
            stripped = line.strip()
            line_num = diagram.start_line + i

            # Skip empty lines, comments, and diagram declaration
            if (
                not stripped
                or stripped.startswith("%%")
                or stripped.lower().startswith("graph")
                or stripped.lower().startswith("flowchart")
            ):
                continue

            # Skip subgraph declarations and end
            if stripped.lower().startswith("subgraph") or stripped.lower() == "end":
                continue

            # Find node definitions
            for match in node_def_pattern.finditer(stripped):
                defined_nodes.add(match.group(1))

            # Find connections (source nodes)
            for match in connection_pattern.finditer(stripped):
                node = match.group(1)
                referenced_nodes.add(node)
                # If it's a simple reference, also check if it's defined
                if node not in defined_nodes:
                    # It might be defined later, so track but don't error yet
                    pass

            # Find target nodes
            for match in target_pattern.finditer(stripped):
                node = match.group(1)
                referenced_nodes.add(node)

            # FLOW_001: Check for unclosed brackets in node definitions
            # Count brackets in line
            brackets_in_line = []
            j = 0
            while j < len(stripped):
                # Check for double brackets first
                if j + 1 < len(stripped):
                    two_char = stripped[j : j + 2]
                    if two_char in ["[[", "((", "]]", "))"]:
                        brackets_in_line.append((two_char, line_num, j))
                        j += 2
                        continue

                char = stripped[j]
                if char in "[](){}":
                    brackets_in_line.append((char, line_num, j))
                j += 1

            # Simple bracket balance check for the line
            line_stack = []
            for bracket, ln, pos in brackets_in_line:
                if bracket in ["[", "[[", "(", "((", "{"]:
                    line_stack.append(bracket)
                elif bracket in ["]", "]]", ")", "))", "}"]:
                    if line_stack and bracket_types.get(line_stack[-1]) == bracket:
                        line_stack.pop()
                    elif not line_stack:
                        issues.append(
                            ValidationIssue(
                                diagram_index=diagram.index,
                                line_number=line_num,
                                severity="error",
                                rule="FLOW_001",
                                message=f"Unmatched closing bracket '{bracket}'",
                                snippet=stripped[:60] + ("..." if len(stripped) > 60 else ""),
                                suggestion="Check bracket pairs: [] for rectangles, () for rounded, {} for rhombus",
                            )
                        )

            if line_stack:
                issues.append(
                    ValidationIssue(
                        diagram_index=diagram.index,
                        line_number=line_num,
                        severity="error",
                        rule="FLOW_001",
                        message=f"Unclosed bracket '{line_stack[-1]}'",
                        snippet=stripped[:60] + ("..." if len(stripped) > 60 else ""),
                        suggestion="Close all brackets: [] for rectangles, () for rounded, {} for rhombus",
                    )
                )

            # FLOW_002: Check for invalid arrow syntax
            invalid_arrows = re.findall(r"[A-Za-z0-9_]\s*(-[^->-]|-[^->]-[^>])", stripped)
            if invalid_arrows:
                issues.append(
                    ValidationIssue(
                        diagram_index=diagram.index,
                        line_number=line_num,
                        severity="error",
                        rule="FLOW_002",
                        message="Invalid arrow syntax",
                        snippet=stripped[:60] + ("..." if len(stripped) > 60 else ""),
                        suggestion="Use valid arrows: -->, --->, -.->,--> |text|, ==>",
                    )
                )

        # FLOW_003: Check for undefined nodes (only if we have definitions)
        if defined_nodes:
            undefined = referenced_nodes - defined_nodes
            # Filter out common false positives (single letter references are often implicit)
            undefined = {n for n in undefined if len(n) > 1}
            for node in undefined:
                issues.append(
                    ValidationIssue(
                        diagram_index=diagram.index,
                        line_number=diagram.start_line,
                        severity="warning",
                        rule="FLOW_003",
                        message=f"Node '{node}' referenced but not explicitly defined",
                        snippet=f"...{node}...",
                        suggestion=f"Define the node explicitly: {node}[Label] or {node}(Label)",
                    )
                )

        return issues

    def _validate_sequence(self, diagram: DiagramInfo) -> List[ValidationIssue]:
        """Validate Mermaid sequence diagram syntax.

        Args:
            diagram: DiagramInfo to validate

        Returns:
            List of ValidationIssue objects
        """
        issues = []
        block_stack = []  # Track alt/loop/opt/par/critical/break blocks

        for i, line in enumerate(diagram.lines):
            stripped = line.strip()
            line_num = diagram.start_line + i

            # Skip empty lines, comments, and diagram declaration
            if not stripped or stripped.startswith("%%") or stripped.lower() == "sequencediagram":
                continue

            # Track block openings
            block_keywords = ["alt", "else", "opt", "loop", "par", "and", "critical", "break", "rect"]
            for keyword in block_keywords:
                if stripped.lower().startswith(keyword + " ") or stripped.lower() == keyword:
                    if keyword not in ["else", "and"]:  # These don't open new blocks
                        block_stack.append((keyword, line_num))
                    break

            # Track block closings
            if stripped.lower() == "end":
                if not block_stack:
                    issues.append(
                        ValidationIssue(
                            diagram_index=diagram.index,
                            line_number=line_num,
                            severity="error",
                            rule="SEQ_002",
                            message="'end' without matching block opener",
                            snippet=stripped,
                            suggestion="Remove this 'end' or add a matching alt/loop/opt/par block",
                        )
                    )
                else:
                    block_stack.pop()

            # SEQ_003: Check arrow syntax
            arrow_pattern = re.compile(r"[A-Za-z0-9_]+\s*(->>|-->>|->|-->|-x|--x|-\)|--\))\s*[A-Za-z0-9_]+")
            if "-" in stripped and not stripped.lower().startswith("note"):
                # Line looks like it might have an arrow
                has_participant = stripped.lower().startswith("participant") or stripped.lower().startswith("actor")
                if not has_participant and not any(
                    stripped.lower().startswith(k) for k in block_keywords + ["end", "activate", "deactivate"]
                ):
                    # Check if it has a valid arrow
                    if not arrow_pattern.search(stripped):
                        # Could be invalid arrow
                        if re.search(r"[A-Za-z0-9_]\s*-[^->x\)]+\s*[A-Za-z0-9_]", stripped):
                            issues.append(
                                ValidationIssue(
                                    diagram_index=diagram.index,
                                    line_number=line_num,
                                    severity="warning",
                                    rule="SEQ_003",
                                    message="Potentially invalid arrow syntax",
                                    snippet=stripped[:60] + ("..." if len(stripped) > 60 else ""),
                                    suggestion="Use valid arrows: ->>, -->, ->, -x, --x, -), --)",
                                )
                            )

        # SEQ_002: Check for unclosed blocks at end
        for block_type, open_line in block_stack:
            issues.append(
                ValidationIssue(
                    diagram_index=diagram.index,
                    line_number=open_line,
                    severity="error",
                    rule="SEQ_002",
                    message=f"Unclosed '{block_type}' block",
                    snippet=f"{block_type}...",
                    suggestion=f"Add 'end' to close the '{block_type}' block",
                )
            )

        return issues

    def _validate_gantt(self, diagram: DiagramInfo) -> List[ValidationIssue]:
        """Validate Mermaid gantt chart syntax.

        Args:
            diagram: DiagramInfo to validate

        Returns:
            List of ValidationIssue objects
        """
        issues = []
        has_section = False
        has_tasks = False

        for i, line in enumerate(diagram.lines):
            stripped = line.strip()
            line_num = diagram.start_line + i

            # Skip empty lines, comments, and diagram declaration
            if not stripped or stripped.startswith("%%") or stripped.lower() == "gantt":
                continue

            # Check for dateFormat
            if stripped.lower().startswith("dateformat"):
                # GANTT_001: Validate date format string
                parts = stripped.split(":", 1) if ":" in stripped else stripped.split(None, 1)
                if len(parts) < 2 or not parts[1].strip():
                    issues.append(
                        ValidationIssue(
                            diagram_index=diagram.index,
                            line_number=line_num,
                            severity="error",
                            rule="GANTT_001",
                            message="Missing or invalid date format",
                            snippet=stripped,
                            suggestion="Use format like: dateFormat YYYY-MM-DD",
                        )
                    )
                continue

            # Track sections
            if stripped.lower().startswith("section"):
                has_section = True
                continue

            # Check for title
            if stripped.lower().startswith("title"):
                continue

            # Tasks should have a colon
            if ":" in stripped and not stripped.lower().startswith(
                ("dateformat", "title", "section", "excludes", "todaymarker", "tickinterval", "weekday")
            ):
                has_tasks = True
                # Basic task format: TaskName :status, id, startDate, duration
                parts = stripped.split(":", 1)
                if len(parts) == 2 and parts[1].strip():
                    # Has task definition after colon
                    pass
                else:
                    issues.append(
                        ValidationIssue(
                            diagram_index=diagram.index,
                            line_number=line_num,
                            severity="warning",
                            rule="GANTT_003",
                            message="Task may have incomplete definition",
                            snippet=stripped[:60] + ("..." if len(stripped) > 60 else ""),
                            suggestion="Format: TaskName :status, id, startDate, duration",
                        )
                    )

        # GANTT_002: Missing section
        if has_tasks and not has_section:
            issues.append(
                ValidationIssue(
                    diagram_index=diagram.index,
                    line_number=diagram.start_line,
                    severity="warning",
                    rule="GANTT_002",
                    message="Gantt chart has tasks but no section",
                    snippet="gantt...",
                    suggestion="Add 'section SectionName' before tasks for better organization",
                )
            )

        return issues

    def _validate_class_diagram(self, diagram: DiagramInfo) -> List[ValidationIssue]:
        """Validate Mermaid class diagram syntax.

        Args:
            diagram: DiagramInfo to validate

        Returns:
            List of ValidationIssue objects
        """
        issues = []

        for i, line in enumerate(diagram.lines):
            stripped = line.strip()
            line_num = diagram.start_line + i

            # Skip empty lines, comments, and diagram declaration
            if not stripped or stripped.startswith("%%") or stripped.lower() == "classdiagram":
                continue

            # Check for common class diagram issues
            # CLASS_001: Unclosed class block
            if stripped.lower().startswith("class ") and "{" in stripped:
                # Multi-line class definition started
                # Would need block tracking for full validation
                pass

        return issues

    def _validate_state_diagram(self, diagram: DiagramInfo) -> List[ValidationIssue]:
        """Validate Mermaid state diagram syntax.

        Args:
            diagram: DiagramInfo to validate

        Returns:
            List of ValidationIssue objects
        """
        issues = []

        # State diagrams use --> for transitions
        # [*] for start/end states

        for i, line in enumerate(diagram.lines):
            stripped = line.strip()
            line_num = diagram.start_line + i

            # Skip empty lines, comments, and diagram declarations
            if not stripped or stripped.startswith("%%"):
                continue
            if stripped.lower().startswith("statediagram"):
                continue

            # Check for state blocks
            if stripped.lower().startswith("state ") and "{" in stripped and "}" not in stripped:
                # Composite state started - would need block tracking
                pass

        return issues


# Convenience functions for module-level access
def validate_markdown_file(filepath: str, strict: bool = True) -> ValidationResult:
    """Validate all Mermaid diagrams in a markdown file.

    Args:
        filepath: Path to the markdown file
        strict: If True, warnings are treated as errors

    Returns:
        ValidationResult with issues found
    """
    validator = MermaidValidator(strict=strict)
    return validator.validate_markdown_file(filepath)


def validate_mermaid_content(content: str, strict: bool = True) -> ValidationResult:
    """Validate Mermaid content (either markdown with code blocks or raw mermaid).

    Args:
        content: Content to validate (markdown or raw mermaid)
        strict: If True, warnings are treated as errors

    Returns:
        ValidationResult with issues found
    """
    validator = MermaidValidator(strict=strict)

    # Check if it looks like markdown (has code fences)
    if "```" in content:
        return validator.validate_markdown_content(content)
    else:
        return validator.validate_mermaid_block(content)
