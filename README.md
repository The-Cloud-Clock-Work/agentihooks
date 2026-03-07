# agentihooks

[![Standalone](https://img.shields.io/badge/runs-standalone-brightgreen)](https://the-cloud-clock-work.github.io/agentihooks/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/The-Cloud-Clock-Work/agentihooks/blob/main/LICENSE)
[![CI](https://github.com/The-Cloud-Clock-Work/agentihooks/actions/workflows/ci.yml/badge.svg)](https://github.com/The-Cloud-Clock-Work/agentihooks/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://python.org)
[![Docs](https://img.shields.io/badge/docs-GitHub%20Pages-blue)](https://the-cloud-clock-work.github.io/agentihooks/)

Hook system and MCP tool server for [Claude Code](https://docs.anthropic.com/en/docs/claude-code) agents. Designed to work with [agenticore](https://github.com/The-Cloud-Clock-Work/agenticore) and meant to be forked and extended for custom workflows.

**agentihooks** intercepts every Claude Code lifecycle event (session start/end, tool use, prompts, stops) and provides 45 MCP tools across 12 categories for interacting with external services.

> **Full documentation:** [the-cloud-clock-work.github.io/agentihooks](https://the-cloud-clock-work.github.io/agentihooks/)

## Architecture

```
Claude Code
  │
  ├── Hook Events (stdin JSON) ──► python -m hooks ──► hook_manager.py
  │     SessionStart, PreToolUse,       │
  │     PostToolUse, Stop, ...          ├── transcript logging
  │                                     ├── tool error memory
  │                                     ├── metrics parsing
  │                                     └── email notifications
  │
  └── MCP Tools ──► python -m hooks.mcp ──► 12 category modules
        github, aws, confluence,              │
        email, database, ...                  └── hooks/integrations/*
```

## Quick Start

**Requirement:** [uv](https://docs.astral.sh/uv/getting-started/installation/) must be installed.

```bash
git clone https://github.com/The-Cloud-Clock-Work/agentihooks
cd agentihooks
uv sync
uv run agentihooks global
```

`agentihooks global` wires hooks into `~/.claude/settings.json`, symlinks skills/agents, merges MCP servers into `~/.claude.json`, and installs the CLI globally. Re-run any time — it's idempotent.

See [Installation](https://the-cloud-clock-work.github.io/agentihooks/docs/getting-started/installation/) for the full step-by-step walkthrough.

## Hook Events

10 lifecycle events, all handled by `python -m hooks`:

| Event | What happens |
|-------|-------------|
| `SessionStart` | Creates session context directory, injects session awareness |
| `PreToolUse` | Secret scan (blocks on detection), injects tool error memory |
| `PostToolUse` | Records tool errors for cross-session learning |
| `Stop` | Scans transcript for errors, parses metrics, auto-saves memory |
| `SessionEnd` | Logs transcript, cleans up session directory |
| `SubagentStop` | Logs subagent transcript |
| `UserPromptSubmit` | Warns on detected secrets |
| `Notification` | Logs notifications |
| `PreCompact` | Logs before context compaction |
| `PermissionRequest` | Logs permission requests |

Full payload schemas and handler details: [Hook Events](https://the-cloud-clock-work.github.io/agentihooks/docs/hooks/events/)

## MCP Tool Categories

45 tools across 12 categories, selectively loaded via `MCP_CATEGORIES`:

| Category | Tools | Description |
|----------|------:|-------------|
| `github` | 5 | Clone repos, create PRs, token management, git summary |
| `confluence` | 9 | CRUD pages, markdown docgen, validation |
| `aws` | 4 | Profile listing, account discovery |
| `email` | 2 | SMTP send with text / HTML / markdown |
| `messaging` | 3 | SQS + webhook with state enrichment |
| `storage` | 2 | S3 upload, `/tmp`-restricted filesystem delete |
| `database` | 3 | DynamoDB put, PostgreSQL insert + execute |
| `compute` | 1 | Lambda invocation (sync/async) |
| `observability` | 7 | Timers, metrics, structured logging, container log tailing |
| `smith` | 4 | Command builder: list, prompt, build, execute |
| `agent` | 1 | Remote agent completions with model presets |
| `utilities` | 4 | Mermaid validation, markdown writer, env vars, tool listing |

Per-tool signatures, parameters, and environment variables: [MCP Tools](https://the-cloud-clock-work.github.io/agentihooks/docs/mcp-tools/)

## CLI

```bash
agentihooks global [--profile <name>]   # install/re-apply to ~/.claude
agentihooks project <path>              # write .mcp.json into a project
agentihooks uninstall                   # remove everything
agentihooks --mcp <file>                # add MCP servers at user scope
agentihooks --mcp --uninstall           # interactive: pick a tracked file to remove
agentihooks --mcp-lib [dir]             # browse a dir of MCP files, install one
agentihooks --sync                      # re-apply all tracked MCP files
agentihooks --loadenv                   # install agentienv alias into ~/.bashrc

```

Full reference: [CLI Commands](https://the-cloud-clock-work.github.io/agentihooks/docs/reference/cli-commands/)

## Configuration

All integrations are configured via environment variables. Key ones:

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENTIHOOKS_HOME` | `~/.agentihooks` | Root for logs, memory, and state |
| `CLAUDE_CODE_HOME_DIR` | `$HOME` | Home-directory root override (`.claude` appended automatically) |
| `AGENTIHOOKS_CLAUDE_HOME` | `~/.claude` | Legacy: direct path to `.claude` directory |
| `AGENTIHOOKS_PROFILE` | `default` | Profile to use for `agentihooks global` / `project` (env alternative to `--profile`) |
| `AGENTIHOOKS_MCP_FILE` | — | Path to an MCP JSON file to auto-merge during `agentihooks global` |
| `MCP_CATEGORIES` | `all` | Comma-separated list of tool categories to load |
| `LOG_ENABLED` | `true` | Enable hook logging |
| `MEMORY_AUTO_SAVE` | `true` | Auto-save session digest on Stop |
| `REDIS_URL` | — | Redis for session state/memory (optional) |

Complete table covering all 40+ variables across every integration: [Configuration Reference](https://the-cloud-clock-work.github.io/agentihooks/docs/reference/configuration/)

## Profiles

Profiles bundle a system prompt (`CLAUDE.md`), MCP category selection, and model settings. Switch with `agentihooks global --profile <name>`.

## Portability

Everything user-specific lives in `~/.agentihooks/`:

```
~/.agentihooks/
├── .env        # All integration credentials (seeded from .env.example)
├── state.json  # Tracked MCP files, lib path, and other state
├── logs/       # Hook + MCP logs
└── memory/     # Cross-session agent memory
```

To move to a new machine: clone the repo, copy `~/.agentihooks/.env`, run `agentihooks global`. Done.

**Install the `agentienv` alias** (sources `.env` into any shell on demand):

```bash
agentihooks --loadenv   # writes managed block to ~/.bashrc
source ~/.bashrc
agentienv          # load vars into current shell before launching claude
```

**Browse a directory of MCP files** and install one interactively:

```bash
agentihooks --mcp-lib ~/.agentitools/   # saved for future calls
agentihooks --mcp-lib                   # reuses saved path
```

**Interactive uninstall** — pick from tracked files:

```bash
agentihooks --mcp --uninstall
```

Details: [Portability & Reusability](https://the-cloud-clock-work.github.io/agentihooks/docs/getting-started/portability/)

## Extending

Add a new MCP tool category with a `register(server)` function + one line in `_registry.py`. Add a new hook handler with one function + one entry in the dispatcher dict.

Guide: [Extending AgentiHooks](https://the-cloud-clock-work.github.io/agentihooks/docs/extending/)

## Code Quality

Continuously analyzed by [SonarQube](https://sonar.homeofanton.com/dashboard?id=agentihooks).

## Related Projects

| Project | Description |
|---------|-------------|
| [agenticore](https://github.com/The-Cloud-Clock-Work/agenticore) | Claude Code runner and orchestrator |
| [agentibridge](https://github.com/The-Cloud-Clock-Work/agentibridge) | MCP server for session persistence and remote control |
| [agentihub](https://github.com/The-Cloud-Clock-Work/agentihub) (private) | Agent identities — CLAUDE.md, workflows, evaluation. Provisioned directly by agenticore. |

## License

See [LICENSE](LICENSE) for details.
