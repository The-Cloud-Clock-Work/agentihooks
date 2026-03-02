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
├── state.json    # Tracks MCP files, lib path, and other state
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

The file is seeded from `.env.example` on first `agentihooks global` and is **never overwritten** on subsequent runs.

**To move to a new machine:** copy `~/.agentihooks/.env` alongside the repo clone.

---

## Loading env vars into your shell (`--loadenv`)

Claude Code expands `${VAR}` in MCP configs from its own process environment at startup. `--loadenv` installs a shell alias that sources `.env` into any shell on demand.

```bash
# Install the alias (one time — writes a managed block to ~/.bashrc)
agentihooks --loadenv

# Reload your shell
source ~/.bashrc

# Load all vars into the current shell whenever you need them
agentienv
```

Then launch `claude` from that shell — all `${VAR}` placeholders in your MCP configs resolve correctly.

The alias written to `~/.bashrc`:

```bash
# === agentihooks ===
alias agentienv='set -a && . ~/.agentihooks/.env && set +a'
# === end-agentihooks ===
```

The block is **idempotent** — re-running `--loadenv` updates the block in place rather than appending. Keep your own aliases outside the markers.

### Auto-installing requirements

After writing the alias, `--loadenv` scans `~/.agentihooks/` and the saved `mcpLibPath` for any `requirements.txt` and offers to install each one:

```
Found /home/user/.agentitools/requirements.txt — install with uv? [y/N]
```

Requirements are installed with `uv pip install` into the active virtual environment. If no venv is active and no `.venv` exists in the current directory, installation is refused to avoid polluting system Python:

```
[!!] No virtual environment found.
     Create and activate one first:
       python3 -m venv .venv && source .venv/bin/activate
     Then re-run: agentihooks --loadenv
```

---

## Linking MCP files at user scope (`--mcp`)

`agentihooks --mcp` merges servers from any `.mcp.json` into `~/.claude.json`, making them available in every project. The path is recorded in `state.json` for auto-sync.

```bash
# Install servers from a file
agentihooks --mcp ~/.agentitools/.anton-mcp.json

# Remove a specific file's servers
agentihooks --mcp ~/.agentitools/.anton-mcp.json --uninstall

# Interactive uninstall — pick from all tracked files
agentihooks --mcp --uninstall
```

The interactive uninstall shows a numbered list:

```
Tracked MCP files:

  1. /home/user/.agentitools/.anton-mcp.json
     14 server(s): anton, litellm, matrix, github, ...

Select file to uninstall [1-1] (or q to quit):
```

Restart Claude Code after any install/uninstall for changes to take effect.

---

## MCP library browser (`--mcp-lib`)

Keep all your `.mcp.json` files in one directory and browse them interactively. The directory path is saved — omit it on future calls.

```bash
# First use — set the library directory
agentihooks --mcp-lib ~/.agentitools/

# Future calls — reuses the saved path
agentihooks --mcp-lib
```

Output:

```
MCP files in /home/user/.agentitools:

  1. .anton-mcp.json  [installed]
     14 server(s): anton, litellm, matrix, github, ...
  2. staging-mcp.json
     3 server(s): staging-api, staging-db, staging-cache

Select file to install [1-2] (or q to quit):
```

`[installed]` marks files already tracked in `state.json`. The library path is saved as `mcpLibPath` in `state.json` — change it any time by passing a new path.

---

## Re-syncing all linked MCPs (`--sync`)

After pulling changes to any tracked `.mcp.json`, re-apply everything:

```bash
agentihooks --sync
```

Reads `~/.agentihooks/state.json` and re-merges each file into `~/.claude.json`. Missing files are skipped with a warning. `agentihooks global` calls `--sync` automatically when `state.json` exists.

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

# 6. Install the agentienv alias + requirements
#    (activate a venv first so --loadenv can install packages)
python3 -m venv .venv && source .venv/bin/activate
agentihooks --loadenv   # writes alias, offers to install requirements.txt
source ~/.bashrc

# 7. Load env vars and launch Claude Code
agentienv && claude

# 8. Point the MCP library to your collection
agentihooks --mcp-lib ~/.agentitools/
# Pick the files you want from the interactive list
```

Everything restored. No manual settings editing, no hunting for which keys go where.

---

## Sharing a setup within a team

1. Keep `.env.example` up to date in the repo with all variable names (no values)
2. Share values via a secrets manager (1Password, AWS Secrets Manager, Vault)
3. Each developer runs `agentihooks global` and populates `~/.agentihooks/.env`
4. Each developer runs `agentihooks --loadenv` to install the `agentienv` alias
5. Keep a shared `~/.agentitools/` style directory (or a team repo) with curated `.mcp.json` files
6. Use `agentihooks --mcp-lib` to browse and install from that collection

The repo stays credential-free. `~/.agentihooks/.env` is on each developer's machine only.
