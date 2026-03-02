---
title: Utilities
nav_order: 13
---

# Utilities Tools
{: .no_toc }

The Utilities category provides general-purpose tools for Mermaid diagram validation, markdown writing, environment variable inspection, and tool discovery.

## Table of contents
{: .no_toc .text-delta }

1. TOC
{:toc}

---

## Tools

| Tool | Description |
|------|-------------|
| `validate_mermaid()` | Validate Mermaid diagram syntax |
| `write_markdown()` | Write a markdown file with auto Mermaid validation |
| `get_env()` | Get environment variables with optional filtering |
| `hooks_list_tools()` | List all available MCP tools grouped by category |

---

## Tool reference

### `validate_mermaid`

```python
validate_mermaid(
    filepath: str = "",
    content: str = "",
    strict: bool = True
) -> str
```

Validates Mermaid diagram syntax. Supply **either** `filepath` (path to a `.md` file) **or** `content` (raw markdown string) — not both.

When `strict=True`, any syntax error causes a failure result. When `strict=False`, warnings are reported but the result is still marked valid.

**Returns:** JSON with `valid` (bool), `diagram_count`, `issues` (list), `diagrams` (list of diagram types found)

---

### `write_markdown`

```python
write_markdown(
    filepath: str,
    content: str,
    validate_mermaid: bool = True
) -> str
```

Writes a markdown file and optionally validates embedded Mermaid diagrams before writing.

{: .important }
**Path restrictions:** `filepath` must have a `.md` extension and must be under either `$AGENTIHOOKS_HOME/package` or `/tmp`. Writes outside these paths are rejected.

When `validate_mermaid=True` (default), the content is validated first. If validation fails, the file is not written and the validation errors are returned instead.

**Returns:** JSON with `filepath`, `bytes_written`, `mermaid_validation`

---

### `get_env`

```python
get_env(filter: str = "") -> str
```

Returns environment variables. When `filter` is provided, only variables whose names contain the filter string (case-insensitive) are returned.

```python
# All env vars
get_env()

# Only GitHub-related vars
get_env(filter="GITHUB")

# Only SMTP vars
get_env(filter="SMTP")
```

**Returns:** JSON with `filter`, `count`, `variables` (dict)

{: .note }
Secret values are not redacted by this tool. Use it for diagnostics but avoid logging the output in untrusted contexts.

---

### `hooks_list_tools`

```python
hooks_list_tools() -> str
```

Introspects the running MCP server and returns all registered tools grouped by category. Useful for agents to discover what capabilities are available at runtime without relying on static documentation.

**Returns:** JSON with `total_tools`, `available_categories`, `categories` (dict mapping category name → list of active tool names)

---

## Notes

### `write_markdown` use cases

This tool is designed for agents that generate documentation or reports as part of their task. The path restrictions ensure generated files land in controlled locations:
- `/tmp/<session_id>/` — temporary session artifacts
- `$AGENTIHOOKS_HOME/package/` — persistent package-level files

### `validate_mermaid` standalone vs. integrated

`validate_mermaid` can be used standalone to check diagrams before publishing to Confluence or committing to a repo. `write_markdown` calls it automatically when writing, so explicit validation is only needed when working with existing files.
