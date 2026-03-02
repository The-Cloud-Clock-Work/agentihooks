---
title: Portability & Reusability
nav_order: 4
parent: Getting Started
---

# Portability & Reusability
{: .no_toc }

AgentiHooks is designed to travel with you. One data directory, one env file, and an idempotent install command let you reproduce a complete Claude Code environment on any machine — or share a setup across a team.

## Table of contents
{: .no_toc .text-delta }

1. TOC
{:toc}

---

## The `~/.agentihooks/` data directory

Everything user-specific lives in a single directory:

```
~/.agentihooks/
├── .env          # All integration credentials (never committed)
├── state.json    # Tracks linked MCP files for --sync
├── logs/         # Hook + MCP log files
└── memory/       # Per-project agent memory files
```

`agentihooks uninstall` never touches this directory — your credentials and memory survive reinstalls.

To fully reset: `rm -rf ~/.agentihooks`

---

## Environment file (`~/.agentihooks/.env`)

All integration keys live in one place:

```bash
# MCP server credentials
MCP_ATLASSIAN_PROXY_API_KEY=...
MCP_SONAR_PROXY_API_KEY=...
MCP_AGENTIBRIDGE_API_KEY=...

# Service endpoints
LITELLM_URL=http://10.10.30.130:4000
GRAFANA_URL=http://10.10.30.130:3000

# GitHub
GITHUB_PERSONAL_ACCESS_TOKEN=ghp_...
```

The file is seeded from `.env.example` on first `agentihooks global` — it is **never overwritten** on subsequent runs.

**To move to a new machine:** copy `~/.agentihooks/.env` alongside the repo clone.

---

## Loading env vars into Claude Code (`--loadenv`)

Claude Code expands `${VAR}` in MCP server configs at startup. Variables set only inside hook subprocesses arrive too late. `--loadenv` solves this by injecting `.env` vars directly into Claude Code's process before it launches.

### Exec mode (recommended)

```bash
agentihooks --loadenv -- claude
```

This replaces the current shell process with `claude`, inheriting all `.env` vars. Add an alias to `~/.bashrc`:

```bash
alias cc='agentihooks --loadenv -- claude'
```

### Print mode (scripting)

```bash
eval $(agentihooks --loadenv)
```

Emits `export KEY='VALUE'` lines that your shell evaluates.

### Custom env file

```bash
agentihooks --loadenv /path/to/project.env -- claude
```

---

## Linking external MCP servers (`--mcp`)

`agentihooks --mcp` merges MCP servers from any `.mcp.json` file into `~/.claude.json` (user scope), making them available in every project. The path is recorded in `state.json`.

```bash
# Add servers from an external repo
agentihooks --mcp ~/dev/my-other-repo/.mcp.json

# Remove them
agentihooks --mcp ~/dev/my-other-repo/.mcp.json --uninstall
```

Multiple files can be registered. `agentihooks global` calls `--sync` automatically to re-apply all of them.

---

## Re-syncing linked MCPs (`--sync`)

After cloning a repo or pulling changes to a linked `.mcp.json`, re-apply all tracked files:

```bash
agentihooks --sync
```

This reads `~/.agentihooks/state.json` and merges each file back into `~/.claude.json`. Missing files are skipped with a warning.

`agentihooks global` calls `--sync` automatically when `state.json` exists.

---

## Reproducing a setup on a new machine

```bash
# 1. Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Clone the repo
git clone https://github.com/The-Cloud-Clock-Work/agentihooks
cd agentihooks

# 3. Install dependencies
uv sync --all-extras

# 4. Copy your env file (from backup, 1Password, etc.)
cp /path/to/backup/.env ~/.agentihooks/.env

# 5. Install hooks, skills, agents, MCPs
uv run agentihooks global

# 6. Re-link any external MCP files you had registered
agentihooks --mcp ~/dev/other-project/.mcp.json

# 7. Set up your alias
echo "alias cc='agentihooks --loadenv -- claude'" >> ~/.bashrc
source ~/.bashrc
```

Everything is restored. No manual settings editing, no digging through shell scripts to remember which keys go where.

---

## Sharing a setup within a team

1. Keep `.env.example` up to date in the repo with all variable names (no values)
2. Share values via a secrets manager (1Password, AWS Secrets Manager, Vault)
3. Each developer runs `agentihooks global` and populates `~/.agentihooks/.env`
4. Use `agentihooks project <path>` to write `.mcp.json` into shared repos

The repo itself stays credential-free. `~/.agentihooks/.env` is on each developer's machine only.
