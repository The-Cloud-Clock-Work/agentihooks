"""Utility MCP tools — mermaid validation, markdown writing, env, tool listing."""

import json
import os

from hooks.common import log


def register(mcp):
    @mcp.tool()
    def validate_mermaid(filepath: str = "", content: str = "", strict: bool = True) -> str:
        """Validate Mermaid diagram syntax in markdown files or raw content.

        Call this AFTER generating documentation to catch syntax errors
        before uploading to Confluence or creating GitHub PRs.

        Args:
            filepath: Path to markdown file (mutually exclusive with content)
            content: Raw markdown or mermaid content to validate (mutually exclusive with filepath)
            strict: If True, warnings are treated as errors (default: True)

        Returns:
            JSON with validation results (valid, diagram_count, issues, diagrams)
        """
        try:
            from hooks.integrations.mermaid_validator import (
                validate_markdown_file,
                validate_mermaid_content,
            )

            if filepath and content:
                return json.dumps({"success": False, "error": "Provide either 'filepath' OR 'content', not both"})

            if not filepath and not content:
                return json.dumps({"success": False, "error": "Provide either 'filepath' or 'content' parameter"})

            if filepath:
                result = validate_markdown_file(filepath, strict=strict)
            else:
                result = validate_mermaid_content(content, strict=strict)

            response = {
                "success": True,
                "valid": result.valid,
                "diagram_count": result.diagram_count,
                "issues": [issue.to_dict() for issue in result.issues],
                "diagrams": [d.to_dict() for d in result.diagrams],
            }

            if result.filepath:
                response["filepath"] = result.filepath

            return json.dumps(response)

        except Exception as e:
            log(
                "MCP validate_mermaid failed",
                {"filepath": filepath, "content_length": len(content) if content else 0, "error": str(e)},
            )
            return json.dumps({"success": False, "error": str(e)})

    @mcp.tool()
    def write_markdown(filepath: str, content: str, validate_mermaid: bool = True) -> str:
        """Write a markdown file with automatic Mermaid syntax validation.

        MANDATORY tool for docgen agent - Write tool is blocked for markdown files.
        This tool writes the file AND validates Mermaid diagrams automatically.

        Args:
            filepath: Path to write (must be .md extension, under /app/package or /tmp)
            content: Markdown content to write
            validate_mermaid: Auto-validate Mermaid diagrams (default: True)

        Returns:
            JSON with write result and mermaid_validation
        """
        try:
            from pathlib import Path

            from hooks.integrations.mermaid_validator import validate_mermaid_content

            path = Path(filepath)
            if path.suffix.lower() != ".md":
                return json.dumps({"success": False, "error": f"Only .md files allowed, got: '{path.suffix}'"})

            resolved = path.resolve()
            allowed_prefixes = ["/app/package", "/tmp"]
            if not any(str(resolved).startswith(p) for p in allowed_prefixes):
                return json.dumps(
                    {"success": False, "error": f"Path not allowed. Must be under: {allowed_prefixes}. Got: {resolved}"}
                )

            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            bytes_written = len(content.encode("utf-8"))

            mermaid_result = None
            if validate_mermaid:
                result = validate_mermaid_content(content, strict=True)
                mermaid_result = {
                    "valid": result.valid,
                    "diagram_count": result.diagram_count,
                    "issues": [issue.to_dict() for issue in result.issues],
                }

            log(
                "MCP write_markdown completed",
                {
                    "filepath": str(path),
                    "bytes_written": bytes_written,
                    "mermaid_valid": mermaid_result["valid"] if mermaid_result else "skipped",
                    "mermaid_diagram_count": mermaid_result["diagram_count"] if mermaid_result else 0,
                    "mermaid_issues_count": len(mermaid_result["issues"]) if mermaid_result else 0,
                },
            )

            return json.dumps(
                {
                    "success": True,
                    "filepath": str(path),
                    "bytes_written": bytes_written,
                    "mermaid_validation": mermaid_result,
                }
            )

        except Exception as e:
            log("MCP write_markdown failed", {"filepath": filepath, "error": str(e)})
            return json.dumps({"success": False, "error": str(e)})

    @mcp.tool()
    def get_env(filter: str = "") -> str:
        """Get environment variables, optionally filtered by a substring.

        Returns environment variables that contain the filter string (case-insensitive).
        If no filter is provided, returns all environment variables.

        Args:
            filter: Substring to filter environment variable names (case-insensitive).

        Returns:
            JSON with matching environment variables (names and values)
        """
        try:
            env_vars = dict(os.environ)

            if filter:
                filter_lower = filter.lower()
                filtered_vars = {k: v for k, v in env_vars.items() if filter_lower in k.lower()}
            else:
                filtered_vars = env_vars

            return json.dumps(
                {
                    "success": True,
                    "filter": filter if filter else None,
                    "count": len(filtered_vars),
                    "variables": filtered_vars,
                }
            )

        except Exception as e:
            log("MCP get_env failed", {"filter": filter, "error": str(e)})
            return json.dumps({"success": False, "error": str(e)})

    @mcp.tool()
    def hooks_list_tools() -> str:
        """List all available MCP tools in this server.

        Returns:
            JSON with tool names grouped by category
        """
        from hooks.mcp._registry import CATEGORY_MODULES

        tools = {
            "github": [
                "github_get_token",
                "github_clone_repo",
                "github_create_pr",
                "github_get_repo_info",
                "git_summary",
            ],
            "confluence": [
                "confluence_get_page",
                "confluence_find_page",
                "confluence_create_page",
                "confluence_update_page",
                "confluence_delete_page",
                "confluence_get_child_pages",
                "confluence_docgen",
                "confluence_validate_page",
                "confluence_test_connection",
            ],
            "aws": [
                "aws_get_profiles",
                "aws_get_account_id",
                "aws_get_all_accounts",
                "aws_find_account",
            ],
            "email": [
                "email_send",
                "email_send_markdown_file",
            ],
            "messaging": [
                "sqs_send_message",
                "sqs_load_state",
                "webhook_send",
            ],
            "storage": [
                "storage_upload_path",
                "filesystem_delete",
            ],
            "database": [
                "dynamodb_put_item",
                "postgres_insert",
                "postgres_execute",
            ],
            "compute": [
                "lambda_invoke_function",
            ],
            "observability": [
                "metrics_start_timer",
                "metrics_stop_timer",
                "metrics_create_collector",
                "metrics_get_summary",
                "log_message",
                "log_command_output",
                "tail_container_logs",
            ],
            "smith": [
                "smith_list_commands",
                "smith_get_prompt",
                "smith_build_command",
                "smith_execute",
            ],
            "agent": [
                "agent_completions",
            ],
            "utilities": [
                "validate_mermaid",
                "write_markdown",
                "get_env",
                "hooks_list_tools",
            ],
        }

        # Filter to only categories that are actually loaded
        registered_tools = {t.name for t in mcp._tool_manager.list_tools()}
        active = {}
        for cat, cat_tools in tools.items():
            present = [t for t in cat_tools if t in registered_tools]
            if present:
                active[cat] = present

        total = sum(len(t) for t in active.values())

        return json.dumps(
            {
                "success": True,
                "total_tools": total,
                "available_categories": list(CATEGORY_MODULES.keys()),
                "categories": active,
            }
        )
