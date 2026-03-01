# agentihooks

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/The-Cloud-Clock-Work/agentihooks/blob/main/LICENSE)
[![CI](https://github.com/The-Cloud-Clock-Work/agentihooks/actions/workflows/ci.yml/badge.svg)](https://github.com/The-Cloud-Clock-Work/agentihooks/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://python.org)

Hook system and MCP tool server for [Claude Code](https://docs.anthropic.com/en/docs/claude-code) agents. Designed to work with [agenticore](https://github.com/The-Cloud-Clock-Work/agenticore) and meant to be forked and extended for custom workflows.

**agentihooks** intercepts every Claude Code lifecycle event (session start/end, tool use, prompts, stops) and provides 45 MCP tools across 12 categories for interacting with external services.

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

## Getting Started

### 1. Clone and install dependencies

```bash
git clone https://github.com/The-Cloud-Clock-Work/agentihooks
cd agentihooks
pip install mcp[cli] PyJWT requests httpx psycopg2-binary
```

### 2. Install into Claude Code

```bash
scripts/install.py global
```

This writes `~/.claude/settings.json` (with all hook wiring), and symlinks
skills, agents, and commands from the repo into `~/.claude/`.

Run with `--profile <name>` to select a profile's system prompt:

```bash
scripts/install.py global --profile coding
scripts/install.py --list-profiles   # show available profiles
```

Re-run any time you update `settings.base.json` — the script is idempotent.

### 3. Create the `/app` symlink (one-time, requires sudo)

All hooks and log paths use `/app` as the canonical root (works identically
in Docker, local dev, and Kubernetes).

```bash
sudo ln -sfn /path/to/agentihooks /app
```

> The install script prints this exact command if it can't create `/app` itself.
> After this, logs appear at `/app/logs/hooks.log` and `/app/logs/agent.log`.

### 4. Verify

Open Claude Code in any project and run `/status` — hooks should be active.
Check `ls /app/logs/` after the first tool call to confirm logs are flowing.

### Install a profile's MCP server into a project

```bash
python3 scripts/install.py project ~/dev/my-project --profile default
```

This writes `.mcp.json` into the target project so Claude Code connects to
the hooks MCP server when opening that project.

### Standalone usage

```bash
# Run the MCP server with all tools
python -m hooks.mcp

# Run with specific categories only
MCP_CATEGORIES=github,utilities python -m hooks.mcp

# Process a hook event manually
echo '{"hook_event_name":"SessionStart"}' | python -m hooks
```

## Project Structure

```
agentihooks/
├── hooks/
│   ├── __main__.py              # Hook event entry point (python -m hooks)
│   ├── hook_manager.py          # Event dispatcher — routes to handlers
│   ├── common.py                # Logging, context injection, script runner
│   ├── config.py                # Environment-based configuration
│   ├── tool_memory.py           # Cross-session tool error learning
│   ├── _redis.py                # Redis helper (session state, positions)
│   │
│   ├── mcp/                     # MCP tool server (python -m hooks.mcp)
│   │   ├── __init__.py          #   build_server() composition engine
│   │   ├── __main__.py          #   Entry point
│   │   ├── _registry.py         #   Category → module mapping
│   │   ├── github.py            #   5 tools: clone, PR, tokens, repo info, git summary
│   │   ├── confluence.py        #   9 tools: CRUD pages, docgen, validation
│   │   ├── aws.py               #   4 tools: profiles, accounts, search
│   │   ├── email.py             #   2 tools: send email, send markdown file
│   │   ├── messaging.py         #   3 tools: SQS messages, webhooks
│   │   ├── storage.py           #   2 tools: S3 upload, filesystem delete
│   │   ├── database.py          #   3 tools: DynamoDB, PostgreSQL
│   │   ├── compute.py           #   1 tool:  Lambda invocation
│   │   ├── observability.py     #   7 tools: timers, metrics, logging, container logs
│   │   ├── smith.py             #   4 tools: command builder, execution
│   │   ├── agent.py             #   1 tool:  agent-to-agent completions
│   │   └── utilities.py         #   4 tools: mermaid validation, env, tool listing
│   │
│   ├── integrations/            # External service clients
│   │   ├── github.py            #   GitHub App auth, git operations
│   │   ├── confluence.py        #   Confluence API client
│   │   ├── aws.py               #   AWS config/account parsing
│   │   ├── mailer.py            #   SMTP with markdown→HTML
│   │   ├── sqs.py               #   SQS messaging with state enrichment
│   │   ├── storage.py           #   S3 uploads
│   │   ├── webhook.py           #   HTTP webhook client
│   │   ├── lambda_invoke.py     #   Lambda sync/async invocation
│   │   ├── dynamodb.py          #   DynamoDB put/query
│   │   ├── postgres.py          #   PostgreSQL insert/execute
│   │   ├── completions.py       #   LLM completions API
│   │   ├── mermaid_validator.py #   Mermaid diagram syntax checker
│   │   ├── git_diff.py          #   Git summary utilities
│   │   ├── file_system.py       #   /tmp-restricted file operations
│   │   ├── session_state.py     #   Session state management
│   │   └── base.py              #   Integration base class
│   │
│   ├── observability/           # Logging & metrics
│   │   ├── transcript.py        #   Conversation transcript logging
│   │   ├── metrics.py           #   Timer, MetricsCollector
│   │   ├── container_logs.py    #   Docker/K8s/ECS log tailing
│   │   └── agent_log_stream.py  #   Agent log streaming
│   │
│   └── memory/                  # Persistent cross-session memory (MCP)
│       ├── server.py            #   Memory MCP: save, search, recall, delete
│       ├── store.py             #   Redis + JSONL file storage
│       ├── auto_save.py         #   Auto-save session digests on Stop
│       └── transcript_reader.py #   Transcript reading utilities
│
├── profiles/                    # Claude Code profile configurations
│   ├── _base/
│   │   └── settings.base.json  #   Shared hooks/permissions (single source of truth)
│   ├── default/
│   │   ├── profile.yml          #   Profile config (model, mcp_categories, etc.)
│   │   ├── .mcp.json            #   MCP server configuration (generated)
│   │   └── .claude/
│   │       ├── settings.json    #   Claude Code settings (generated)
│   │       └── CLAUDE.md        #   Agent system prompt
│   └── coding/
│       └── ...                  #   Same structure
│
└── scripts/
    ├── install.py               # Install hooks/skills/agents to ~/.claude (local dev)
    └── build_profiles.py        # Generate settings.json + .mcp.json per profile (Docker)
```

## Hook Events

The hook system processes every Claude Code lifecycle event via `python -m hooks`:

| Event | What happens |
|-------|-------------|
| `SessionStart` | Creates session context directory, injects session awareness |
| `PreToolUse` | Injects tool error memory from past sessions |
| `PostToolUse` | Records tool errors for future learning |
| `Stop` | Scans transcript for missed errors, parses metrics, auto-saves memory |
| `SessionEnd` | Logs transcript, cleans up session directory |
| `SubagentStop` | Logs subagent transcript |
| `UserPromptSubmit` | Logs prompt submission |
| `Notification` | Logs notifications |
| `PreCompact` | Logs before context compaction |
| `PermissionRequest` | Logs permission requests |

## MCP Tool Categories

Tools are organized into 12 categories that can be selectively loaded:

| Category | Tools | Description |
|----------|-------|-------------|
| `github` | 5 | Clone repos, create PRs, get tokens, repo info, git summary |
| `confluence` | 9 | CRUD pages, docgen from markdown, validation, test connection |
| `aws` | 4 | List profiles, get account IDs, search accounts |
| `email` | 2 | Send email with text/HTML/markdown, send from file |
| `messaging` | 3 | SQS messages with state enrichment, webhooks |
| `storage` | 2 | S3 uploads, /tmp-restricted filesystem delete |
| `database` | 3 | DynamoDB put_item, PostgreSQL insert/execute |
| `compute` | 1 | Lambda invocation (sync/async) |
| `observability` | 7 | Timers, metrics collectors, logging, container log tailing |
| `smith` | 4 | Command builder, prompt management, execution |
| `agent` | 1 | Agent-to-agent completions via internal API |
| `utilities` | 4 | Mermaid validation, markdown writing, env vars, tool listing |

### Category filtering

Control which tools are loaded via the `MCP_CATEGORIES` environment variable:

```bash
# All tools (default)
MCP_CATEGORIES=all python -m hooks.mcp

# Only GitHub and utilities
MCP_CATEGORIES=github,utilities python -m hooks.mcp

# Set in profile.yml
mcp_categories: github,aws,utilities
```

## Profiles

Profiles configure how Claude Code agents behave. Each profile contains:

- **`profile.yml`** — Model, max turns, permissions, MCP categories
- **`.mcp.json`** — MCP server connection (generated by build script)
- **`.claude/settings.json`** — Hook wiring and permissions (generated by build script)
- **`.claude/CLAUDE.md`** — Agent system prompt

### Building profiles

```bash
python scripts/build_profiles.py
```

This merges `profiles/_base/settings.base.json` with any per-profile `settings.overrides.json` to generate the final `.claude/settings.json` and `.mcp.json`.

### Creating a new profile

1. Copy an existing profile directory
2. Edit `profile.yml` (model, categories, etc.)
3. Optionally add `settings.overrides.json` for custom permissions
4. Edit `.claude/CLAUDE.md` for agent-specific instructions
5. Run `python scripts/build_profiles.py`

## Extending

### Adding a new MCP tool category

1. Create `hooks/mcp/mytools.py` with a `register(mcp)` function:

```python
"""My custom MCP tools."""
import json
from hooks.common import log

def register(mcp):
    @mcp.tool()
    def my_custom_tool(arg: str) -> str:
        """Tool description."""
        try:
            # your logic here
            return json.dumps({"success": True, "result": "..."})
        except Exception as e:
            log("MCP my_custom_tool failed", {"error": str(e)})
            return json.dumps({"success": False, "error": str(e)})
```

2. Register it in `hooks/mcp/_registry.py`:

```python
CATEGORY_MODULES = {
    ...
    "mytools": "hooks.mcp.mytools",
}
```

3. Add it to your profile's `mcp_categories` in `profile.yml`

### Adding a new integration

1. Create `hooks/integrations/myservice.py`
2. Use lazy imports in your MCP tool module to keep startup fast
3. Follow the existing pattern: service client class + convenience functions

### Adding a custom hook handler

Edit `hooks/hook_manager.py` and add your handler to the `EVENT_HANDLERS` dict. Each handler receives the parsed JSON payload from stdin.

## Configuration

Key environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_CATEGORIES` | `all` | Comma-separated list of tool categories to load |
| `ALLOWED_TOOLS` | (empty) | Legacy: comma-separated list of specific tool names |
| `CLAUDE_HOOK_LOG_FILE` | `/app/logs/hooks.log` | Hook log file path |
| `AGENT_LOG_FILE` | `/app/logs/agent.log` | Agent transcript log path |
| `LOG_ENABLED` | `true` | Enable hook logging |
| `LOG_TRANSCRIPT` | `true` | Auto-log conversation transcript |
| `STREAM_AGENT_LOG` | `true` | Stream transcript to `AGENT_LOG_FILE` in real-time |
| `MEMORY_AUTO_SAVE` | `true` | Auto-save session digest on Stop |
| `LOG_HOOKS_COMMANDS` | `false` | Log hook command output |
| `REDIS_URL` | (empty) | Redis connection for session state/memory |

Integration-specific variables (GitHub App, AWS, SMTP, etc.) are documented in each integration module.

## Code Quality

This project is continuously analyzed by [SonarQube](https://sonar.homeofanton.com/dashboard?id=agentihooks) for code quality, security vulnerabilities, and test coverage.

## License

See [LICENSE](LICENSE) for details.
