---
title: Smith (Command Builder)
nav_order: 11
---

# Smith Tools
{: .no_toc }

The Smith category integrates with the **agenticore command builder** — a `commands.json` registry of named Claude CLI presets. Smith tools let agents discover, inspect, compose, and execute these presets programmatically.

## Table of contents
{: .no_toc .text-delta }

1. TOC
{:toc}

---

## Tools

| Tool | Description |
|------|-------------|
| `smith_list_commands()` | List all command presets from `commands.json` |
| `smith_get_prompt()` | Get the prompt content for a command preset |
| `smith_build_command()` | Build a Claude command array with prompt injection |
| `smith_execute()` | Build and execute a command synchronously |

---

## Tool reference

### `smith_list_commands`

```python
smith_list_commands() -> str
```

Reads `commands.json` and returns all available command presets with metadata.

**Returns:** JSON with `count`, `commands` (list of names), `details` (with `has_prompt`, `prompt_file`, `command_preview`)

---

### `smith_get_prompt`

```python
smith_get_prompt(command_name: str = "default") -> str
```

Reads and returns the full prompt content for the named command preset.

**Returns:** JSON with `command_name`, `prompt_file`, `content`, `char_count`

---

### `smith_build_command`

```python
smith_build_command(
    command_name: str = "default",
    parameters: str = "",
    template_vars: str = "{}",
    inject_prompt: bool = True
) -> str
```

Builds the full Claude CLI command array for a preset. Supports `{{VAR}}` template variable substitution in prompts. When `inject_prompt=True`, the prompt content is embedded directly into the command.

**Returns:** JSON with `command_name`, `command` (array), `parameters`, `template_vars`, `inject_prompt`

---

### `smith_execute`

```python
smith_execute(
    command_name: str = "default",
    parameters: str = "",
    template_vars: str = "{}",
    cwd: str = "",
    timeout: int = 120
) -> str
```

Builds the command and executes it synchronously. Captures stdout, stderr, exit code, and duration.

{: .warning }
**BLOCKING — for short tasks only.** `smith_execute` blocks until the subprocess completes. Default timeout is 120 seconds; maximum recommended is 180 seconds. For long-running agents or workflows, use `smith_build_command` and manage the process yourself.

**Returns:** JSON with `exit_code`, `stdout`, `stderr`, `duration_ms`, `timed_out` (bool)

---

## `commands.json` pattern

Smith tools expect a `commands.json` file in the working directory or `AGENTIHOOKS_HOME`. Structure:

```json
{
  "default": {
    "command": ["claude", "--model", "claude-haiku-4-5-20251001"],
    "prompt_file": "prompts/default.md"
  },
  "thinkhard": {
    "command": ["claude", "--model", "claude-sonnet-4-6"],
    "prompt_file": "prompts/thinkhard.md"
  },
  "ultrathink": {
    "command": ["claude", "--model", "claude-opus-4-6"],
    "prompt_file": "prompts/ultrathink.md"
  }
}
```

### Template variables

Prompt files can include `{{VAR}}` placeholders:

```markdown
You are a {{role}} agent. Your task is: {{task}}
```

Pass values via `template_vars`:

```python
smith_build_command(
    command_name="default",
    template_vars='{"role": "reviewer", "task": "check PR #42"}'
)
```

---

## Notes

- Smith tools are the programmatic interface to agenticore's command builder. The `agent` category's `agent_completions` tool uses the HTTP API instead of subprocess execution.
- Use `smith_list_commands` before `smith_execute` to verify the preset exists.
- The `timeout` parameter in `smith_execute` is a hard limit — the subprocess is killed when exceeded and `timed_out: true` is returned.
