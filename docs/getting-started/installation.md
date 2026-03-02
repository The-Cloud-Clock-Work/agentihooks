---
title: Installation
nav_order: 2
---

# Installation
{: .no_toc }

## Table of contents
{: .no_toc .text-delta }

1. TOC
{:toc}

---

## 1. Install uv

AgentiHooks uses [uv](https://github.com/astral-sh/uv) for dependency management.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Verify:

```bash
uv --version
```

---

## 2. Clone the repository

```bash
git clone https://github.com/The-Cloud-Clock-Work/agentihooks
cd agentihooks
```

---

## 3. Install dependencies

```bash
uv sync --all-extras
```

This installs all optional dependencies (boto3, psycopg2, pyyaml, redis).

---

## 4. Run the global install

```bash
uv run agentihooks global
```

This single command:

1. Reads `profiles/_base/settings.base.json` (the canonical settings source)
2. Substitutes `/app` placeholders with the real repo path
3. Writes `~/.claude/settings.json` with hook wiring and tool permissions
4. Symlinks skills, agents, and commands from `.claude/` into `~/.claude/`
5. Symlinks `~/.claude/CLAUDE.md` to the chosen profile's system prompt
6. Merges profile `.mcp.json` into `~/.claude.json` (user-scope MCP servers)
7. Installs the `agentihooks` CLI globally via `uv tool install --editable .`

The install is **idempotent** — re-running is safe. Settings are only backed up on the first run.

---

## 5. Verify

Confirm the hooks are wired:

```bash
cat ~/.claude/settings.json | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d.get('hooks',{})), 'hook events configured')"
```

Confirm the MCP server is registered:

```bash
cat ~/.claude.json | python3 -c "import json,sys; d=json.load(sys.stdin); print(list(d.get('mcpServers',{}).keys()))"
```

Start a Claude Code session and verify by asking:

```
What MCP tools do you have available?
```

The agent should list tools from agentihooks (e.g., `hooks_list_tools`, `get_env`, etc.).

---

## Using a specific profile

```bash
uv run agentihooks global --profile coding
```

List available profiles:

```bash
uv run agentihooks global --list-profiles
```

Query the currently active profile:

```bash
uv run agentihooks global --query
```

---

## Install MCP tools into a specific project

To wire the MCP server for a single project (without global install):

```bash
uv run agentihooks project ~/dev/my-project
```

This writes a `.mcp.json` into the target project directory.

---

## Standalone MCP server

Run the MCP server directly (useful for testing):

```bash
# All 45 tools
python -m hooks.mcp

# Specific categories only
MCP_CATEGORIES=github,utilities python -m hooks.mcp
```

---

## Uninstall

To remove everything agentihooks installed:

```bash
agentihooks uninstall
```

Add `--yes` to skip the confirmation prompt.

{: .warning }
This removes hooks, skills, agents, CLAUDE.md, and MCP server registrations. User data in `~/.agentihooks/` is **not** removed — delete it manually with `rm -rf ~/.agentihooks` if desired.
