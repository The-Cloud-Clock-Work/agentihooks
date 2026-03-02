---
layout: home
title: Home
nav_order: 1
description: "AgentiHooks — Hook system and MCP tool server for Claude Code agents."
permalink: /
---

# AgentiHooks
{: .fs-9 .fw-700 }

Lifecycle hooks and 45 MCP tools for Claude Code — install once, work everywhere.
{: .fs-5 .text-grey-dk-100 .mb-6 }

<div class="hero-actions text-center mb-8" markdown="0">
  <a href="#install" class="btn btn-primary fs-5 mr-2">Get Started</a>
  <a href="https://github.com/The-Cloud-Clock-Work/agentihooks" class="btn fs-5" target="_blank">View on GitHub</a>
</div>

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/The-Cloud-Clock-Work/agentihooks/blob/main/LICENSE)
[![CI](https://github.com/The-Cloud-Clock-Work/agentihooks/actions/workflows/ci.yml/badge.svg)](https://github.com/The-Cloud-Clock-Work/agentihooks/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://python.org)
{: .text-center .mb-8 }

---

## Install
{: #install }

```bash
pip install agentihooks
```

Then wire everything into Claude Code in one command:

```bash
agentihooks global
```

That's it. Hooks are active and 45 MCP tools are registered the next time you start `claude`.

---

## Choose a profile

Profiles set the agent's personality and tool permissions. The default profile works for most people.

```bash
# See what's available
agentihooks global --list-profiles

# Install with a specific profile
agentihooks global --profile coding

# Check which profile is active
agentihooks global --query
```

---

## Load your secrets — the `agentienv` alias

Claude Code expands `${VAR}` in MCP configs from its own process environment. The cleanest way to get secrets into that environment is the `agentienv` alias:

```bash
# One-time setup — writes a managed block to ~/.bashrc
agentihooks --loadenv

# Reload your shell
source ~/.bashrc
```

From now on, run this before starting Claude Code:

```bash
agentienv        # sources ~/.agentihooks/.env into the current shell
claude           # inherits all your vars
```

All `${VAR}` placeholders in MCP server configs resolve automatically.

---

## Restrict which tools load

By default all 45 tools across all 12 categories are active. Use environment variables in the MCP server's `env` block (inside `~/.claude.json`) to cut that down.

**Restrict by category** — only load the categories you need:

```json
"env": {
  "MCP_CATEGORIES": "github,utilities"
}
```

Valid category names (comma-separated, any order):

```
github  confluence  aws  email  messaging  storage
database  compute  observability  smith  agent  utilities
```

**Restrict to specific tools** — allowlist exact tool names within the loaded categories:

```json
"env": {
  "MCP_CATEGORIES": "github,utilities",
  "ALLOWED_TOOLS": "github_get_token,github_clone_repo,hooks_list_tools"
}
```

`ALLOWED_TOOLS` is an **allowlist** — only the tools you name will be active. Tools not in the list are removed at server startup.

**Where to edit:** open `~/.claude.json`, find the `hooks-utils` server under `mcpServers`, and update its `env` block. Restart Claude Code for the change to take effect.

**Verify what's active:** ask Claude Code to call `hooks_list_tools()` — it returns the exact set of loaded categories and tool names.

---

## Per-project MCP tools

Don't want a global install? Wire the MCP server into a single project instead:

```bash
agentihooks project ~/dev/my-project
agentihooks project ~/dev/my-project --profile coding
```

This writes a `.mcp.json` directly into the project directory.

---

## Add more MCP servers

```bash
# Add servers from any .mcp.json file
agentihooks --mcp /path/to/.mcp.json

# Remove them
agentihooks --mcp /path/to/.mcp.json --uninstall

# Interactive picker from a directory of .mcp.json files
agentihooks --mcp-lib /path/to/mcp-library/
```

Registered files are tracked in `~/.agentihooks/state.json` and re-applied automatically on every `agentihooks global` run.

---

## Uninstall

```bash
agentihooks uninstall        # prompts for confirmation
agentihooks uninstall --yes  # scripting / no prompt
```

User data in `~/.agentihooks/` (logs, memory, state) is left in place. Remove it manually if you want a full reset:

```bash
rm -rf ~/.agentihooks
```

---

## What you get

| | |
|---|---|
| **Lifecycle hooks** | Auto-log transcripts, inject session context, save memory on stop |
| **45 MCP tools** | GitHub, AWS, Confluence, email, SQS, S3, DynamoDB, PostgreSQL, observability, and more |
| **Profiles** | Swap agent personality and permissions with one flag |
| **`agentienv` alias** | Clean, shell-native secret loading — no wrapper scripts |

Full details in the [docs]({{ site.baseurl }}/docs/getting-started/).

---

## Related projects

| Project | Description |
|---------|-------------|
| [agenticore](https://github.com/The-Cloud-Clock-Work/agenticore) | Claude Code runner and orchestrator (uses agentihooks) |
| [agentibridge](https://github.com/The-Cloud-Clock-Work/agentibridge) | MCP server for session persistence and remote control |

---

<p align="center">
  Built by <a href="https://github.com/The-Cloud-Clock-Work">The Cloud Clock Work</a> &middot;
  <a href="https://github.com/The-Cloud-Clock-Work/agentihooks/blob/main/LICENSE">MIT License</a>
</p>
