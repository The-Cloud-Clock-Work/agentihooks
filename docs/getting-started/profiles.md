---
title: Profiles
nav_order: 3
---

# Profiles
{: .no_toc }

## Table of contents
{: .no_toc .text-delta }

1. TOC
{:toc}

---

## What is a profile?

A **profile** is a named configuration bundle that controls:

- Which **agent system prompt** (`CLAUDE.md`) Claude Code loads
- Which **MCP tool categories** are enabled (via `MCP_CATEGORIES`)
- Model selection, turn limits, and timeout settings

Profiles are stored under `profiles/<name>/` in the repository.

---

## Profile structure

```
profiles/
├── _base/
│   └── settings.base.json      # Canonical settings (hooks, permissions, MCP servers)
├── default/
│   ├── profile.yml             # Model, turns, timeout, MCP_CATEGORIES
│   ├── .mcp.json               # Generated MCP server config (has /app paths)
│   └── .claude/
│       ├── CLAUDE.md           # Agent system prompt for this profile
│       └── settings.json       # Generated hook wiring + permissions
└── coding/
    └── ...                     # Same structure
```

### `_base/settings.base.json`

This is the **single source of truth** for all settings. It contains:

- Hook event wiring (`hooks` → shell commands)
- Tool permission allowances
- MCP server definitions

All paths use `/app` as a placeholder. The install script substitutes `/app` with the real repo path at render time.

### `profile.yml`

Controls runtime behavior:

```yaml
model: claude-sonnet-4-6
max_turns: 50
timeout: 600
mcp_categories: github,utilities,observability
```

### `.claude/CLAUDE.md`

The agent's system prompt. This is what Claude Code loads as its operating instructions. The install script symlinks `~/.claude/CLAUDE.md` to the chosen profile's `CLAUDE.md`.

---

## Listing profiles

```bash
agentihooks global --list-profiles
```

Example output:

```
Available profiles:
  default
  coding
```

---

## Switching profiles

Re-run the global install with `--profile`:

```bash
agentihooks global --profile coding
```

Or set the `AGENTIHOOKS_PROFILE` environment variable so you don't have to pass `--profile` every time:

```bash
export AGENTIHOOKS_PROFILE=coding
agentihooks global
```

This is especially useful in CI/Docker automation where the profile is set once in the container environment.

Either way, the command atomically:
1. Replaces the `~/.claude/CLAUDE.md` symlink
2. Updates `MCP_CATEGORIES` in the hook environment
3. Re-merges the profile `.mcp.json`

The switch takes effect on the next Claude Code session.

---

## Querying the active profile

```bash
agentihooks global --query
```

---

## Creating a custom profile

1. Copy an existing profile:
   ```bash
   cp -r profiles/default profiles/myprofile
   ```

2. Edit `profiles/myprofile/profile.yml` to set model, turns, and categories.

3. Edit `profiles/myprofile/.claude/CLAUDE.md` with your custom system prompt.

4. Install the new profile:
   ```bash
   agentihooks global --profile myprofile
   ```

{: .note }
Profiles affect the **agent's persona and tool access** but not the underlying hook behavior. Hooks are always wired from `_base/settings.base.json` regardless of profile.

---

## Agent Hop — external agent hubs

Agent Hop (`scripts/agent_hop.py`) lets you maintain agent identities in a separate repo (e.g. a private **agentihub** repo) and build them through the same `_base` pipeline as local profiles.

### Three-layer architecture

```
agenticore   = execution engine (runs Claude, manages jobs)
agentihooks  = build system (profiles, hooks, guardrails, Agent Hop connector)
agentihub    = agent identities (CLAUDE.md, workflows, evaluation) — your private repo
```

### agentihub agent structure

```
agentihub/agents/<name>/
├── agent.yml                  # Same schema as profile.yml
├── settings.overrides.json    # Env overrides (merged with _base)
├── .claude/
│   └── CLAUDE.md              # Agent personality + workflow
└── evaluation/                # Eval harness (future)
    ├── eval.yml
    └── cases/
```

### Usage

```bash
# Build all agents from agentihub into agentihooks profiles/
python scripts/agent_hop.py /path/to/agentihub

# Custom output directory
python scripts/agent_hop.py --output /custom/profiles/dir /path/to/agentihub

# Via environment variable
AGENTIHUB_PATH=/path/to/agentihub python scripts/agent_hop.py
```

Agent Hop:
1. Discovers all `agents/*/agent.yml` in the hub repo
2. Copies each agent into the output directory (default: `profiles/`)
3. Renames `agent.yml` → `profile.yml`
4. Calls `build_profile()` — generates `settings.json`, `.mcp.json`, symlinks

The result is a standard profile that agenticore discovers normally via `AGENTICORE_AGENTIHOOKS_PATH`.
