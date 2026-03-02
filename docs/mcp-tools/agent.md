---
title: Agent
nav_order: 12
---

# Agent Tools
{: .no_toc }

The Agent category provides a single tool for invoking remote Claude agents via the agenticore `/completions` HTTP endpoint. Unlike [Smith](smith.md), which spawns a local subprocess, `agent_completions` calls a remote API — suitable for distributed architectures.

## Table of contents
{: .no_toc .text-delta }

1. TOC
{:toc}

---

## Tools

| Tool | Description |
|------|-------------|
| `agent_completions()` | Call the completions endpoint to invoke a remote agent |

---

## Tool reference

### `agent_completions`

```python
agent_completions(
    prompt: str,
    command: str = "default",
    wait: bool = True,
    stateless: bool = False,
    template_vars: str = "{}",
    context: str = "{}"
) -> str
```

Sends a prompt to the agenticore completions API. The `command` preset determines which model and system prompt are used.

- **`wait=True`** (default) — blocks until the agent returns a response
- **`wait=False`** — fire-and-forget; returns an acceptance message immediately
- **`stateless=True`** — omits session context from the request
- **`template_vars`** — JSON object for `{{VAR}}` substitution in the prompt
- **`context`** — JSON object with additional context fields passed to the agent

**Returns:** the agent's response text (or an acceptance message when `wait=False`)

---

## Command presets

| Preset | Model | Use case |
|--------|-------|---------|
| `default` | `claude-haiku-4-5-20251001` | Fast, lightweight tasks |
| `thinkhard` | `claude-sonnet-4-6` | Moderate reasoning |
| `ultrathink` | `claude-opus-4-6` | Complex analysis, deep reasoning |

---

## Example usage

```python
# Quick question with the default (haiku) model
agent_completions(
    prompt="Summarize the key changes in this diff: {{diff}}",
    command="default",
    template_vars='{"diff": "..."}'
)

# Deep analysis with opus
agent_completions(
    prompt="Review this architecture and identify risks",
    command="ultrathink",
    context='{"repo": "my-service", "pr_number": 42}'
)

# Fire-and-forget notification
agent_completions(
    prompt="Send a Slack summary of today's deployments",
    command="default",
    wait=False
)
```

---

## Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `AGENT_API_ENDPOINT` | No | `http://localhost:8000` | Completions API base URL |
| `AGENT_API_KEY` | No | — | API key for authentication |
| `AGENT_API_TIMEOUT` | No | `300` | Request timeout in seconds |
