---
title: CLI Commands
nav_order: 3
---

# CLI Commands
{: .no_toc }

The `agentihooks` CLI is installed globally via `uv tool install --editable .` as part of `agentihooks global`. All subcommands are idempotent.

## Table of contents
{: .no_toc .text-delta }

1. TOC
{:toc}

---

## `agentihooks global`

Install hooks, skills, agents, and `CLAUDE.md` into `~/.claude`.

```bash
agentihooks global [--profile <name>] [--list-profiles] [--query]
```

### What it does

1. Reads `profiles/_base/settings.base.json`
2. Substitutes `/app` → real repo path in all commands
3. Preserves personal keys (`model`, `autoUpdatesChannel`, `skipDangerousModePermissionPrompt`) from any pre-existing unmanaged settings
4. Writes `~/.claude/settings.json` with hook wiring and tool permissions
5. Symlinks skills, agents, and commands from `.claude/` into `~/.claude/`
6. Symlinks `~/.claude/CLAUDE.md` → chosen profile's `CLAUDE.md`
7. Merges profile `.mcp.json` into `~/.claude.json` (user-scope MCP servers)
8. If `~/.agentihooks/state.json` exists, re-syncs any custom MCP files via `--sync`

### Flags

| Flag | Description |
|------|-------------|
| `--profile <name>` | Profile to install (default: `default`) |
| `--list-profiles` | Print all available profiles and exit |
| `--query` | Print the currently active profile name and exit |

### Examples

```bash
# Install with default profile
agentihooks global

# Install with the coding profile
agentihooks global --profile coding

# List available profiles
agentihooks global --list-profiles

# Query active profile
agentihooks global --query
```

---

## `agentihooks project`

Write a rendered `.mcp.json` into a specific project directory.

```bash
agentihooks project <path> [--profile <name>]
```

This makes agentihooks MCP tools available in a single project without a global install. The `.mcp.json` is written to `<path>/.mcp.json`.

### Flags

| Flag | Description |
|------|-------------|
| `--profile <name>` | Profile whose MCP config to use (default: `default`) |

### Example

```bash
agentihooks project ~/dev/my-project
agentihooks project ~/dev/my-project --profile coding
```

---

## `agentihooks uninstall`

Remove everything agentihooks installed from the system.

```bash
agentihooks uninstall [--yes]
```

### What gets removed

- `~/.claude/settings.json` — if managed by agentihooks (detected via `_managedBy` marker)
- Skills, agents, and command symlinks in `~/.claude/` — if they target the agentihooks repo
- `~/.claude/CLAUDE.md` — if it points into `profiles/`
- MCP servers in `~/.claude.json` — from profile `.mcp.json` files and `state.json`
- `agentihooks` CLI — via `uv tool uninstall agentihooks`

### What is NOT removed

`~/.agentihooks/` (user data: logs, memory, state) is left in place. To fully reset:

```bash
rm -rf ~/.agentihooks
```

### Flags

| Flag | Description |
|------|-------------|
| `--yes` | Skip confirmation prompt (for scripting) |

---

## `agentihooks --mcp`

Manage MCP servers at user scope (`~/.claude.json`), making them available in every project.

```bash
# Add MCP servers from a file
agentihooks --mcp /path/to/.mcp.json

# Remove MCP servers
agentihooks --mcp /path/to/.mcp.json --uninstall
```

When adding, the file path is recorded in `~/.agentihooks/state.json` so `agentihooks global` can re-apply it automatically on future runs.

### Flags

| Flag | Description |
|------|-------------|
| `--uninstall` | Remove the servers from `~/.claude.json` instead of adding them |

---

## `agentihooks --sync`

Re-apply all MCP files previously registered via `--mcp`.

```bash
agentihooks --sync
```

Reads `~/.agentihooks/state.json` and merges each recorded `.mcp.json` file back into `~/.claude.json`. Called automatically by `agentihooks global` when `state.json` exists.

---

## Standalone Python execution

The hook and MCP server modules can be run directly with Python:

```bash
# Run the MCP tool server (all 45 tools)
python -m hooks.mcp

# Run with specific categories
MCP_CATEGORIES=github,utilities python -m hooks.mcp

# Process a hook event manually
echo '{"hook_event_name":"SessionStart","session_id":"test-123"}' | python -m hooks

# Pipe a PreToolUse event
echo '{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"ls"}}' | python -m hooks
```

---

## Exit codes

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1` | Error (installation failed, missing config, etc.) |
| `2` | Block (used by hook handlers to cancel tool execution) |
