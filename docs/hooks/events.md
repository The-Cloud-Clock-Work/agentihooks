---
title: Events
nav_order: 2
---

# Hook Events
{: .no_toc }

AgentiHooks registers handlers for all 10 Claude Code hook events.

## Table of contents
{: .no_toc .text-delta }

1. TOC
{:toc}

---

## Exit code semantics

| Exit code | Meaning |
|-----------|---------|
| `0` | Allow — Claude Code proceeds normally |
| `2` | Block — Claude Code cancels the action and injects the hook's stdout as a warning |

---

## SessionStart

**When:** A new Claude Code session begins.

**Payload fields:**

| Field | Type | Description |
|-------|------|-------------|
| `session_id` | string | Unique session identifier |

**Handler actions:**

1. Creates `/tmp/<session_id>/` as the session working directory
2. Injects a context message into Claude's context window with session awareness
3. Logs output token limit awareness if `CLAUDE_CODE_MAX_OUTPUT_TOKENS` is set

---

## SessionEnd

**When:** The session ends normally (not via Stop).

**Payload fields:**

| Field | Type | Description |
|-------|------|-------------|
| `session_id` | string | Session identifier |
| `transcript_path` | string | Path to the session transcript JSONL file |

**Handler actions:**

1. Parses the transcript to extract metrics (`num_turns`, `duration_ms`)
2. Logs all transcript entries to the hooks log
3. Cleans up the `/tmp/<session_id>/` directory

---

## UserPromptSubmit

**When:** The user submits a prompt (before Claude processes it).

**Payload fields:**

| Field | Type | Description |
|-------|------|-------------|
| `session_id` | string | Session identifier |
| `prompt` | string | The user's raw prompt text |

**Handler actions:**

1. Scans the prompt for secrets and credentials using regex patterns
2. If secrets are detected: injects a warning into the context (does **not** block — warnings only at this stage)

---

## PreToolUse

**When:** Before any tool executes. This is the primary security gate.

**Payload fields:**

| Field | Type | Description |
|-------|------|-------------|
| `session_id` | string | Session identifier |
| `tool_name` | string | Name of the tool about to run |
| `tool_input` | object | Tool input parameters |
| `transcript_path` | string | Path to transcript |

**Handler actions:**

1. Logs the transcript entry
2. **Secret scanning** — scans `tool_input` for credentials; exits with code `2` (block) if found
3. **Tool memory injection** — looks up past errors for this tool and injects them as context so the agent can avoid repeating mistakes
4. Special handling for `Bash`, `Write`, and `Edit` tools

**Exit codes used:**

- `0` — tool is safe to run
- `2` — secret detected; action blocked

---

## PostToolUse

**When:** After a tool completes (success or failure).

**Payload fields:**

| Field | Type | Description |
|-------|------|-------------|
| `session_id` | string | Session identifier |
| `tool_name` | string | Name of the tool that ran |
| `transcript_path` | string | Path to transcript |
| `tool_output` | string | Tool's stdout |
| `tool_error` | string | Tool's stderr (empty on success) |

**Handler actions:**

1. Logs the transcript entry
2. If `tool_error` is non-empty: records the error pattern to the tool memory file (`~/.agenticore_tool_memory.ndjson`) for future injection

---

## Stop

**When:** The agent stops (task complete or unrecoverable error). This is the most active handler.

**Payload fields:**

| Field | Type | Description |
|-------|------|-------------|
| `session_id` | string | Session identifier |
| `transcript_path` | string | Path to transcript |

**Handler actions:**

1. Parses transcript to extract metrics (`num_turns`, `duration_ms`)
2. Scans transcript for MCP errors that `PostToolUse` may have missed
3. If errors found and email is configured (`SMTP_SERVER`): sends an error notification email
4. Logs all transcript entries
5. If `MEMORY_AUTO_SAVE=true`: saves a session digest to the memory store

---

## SubagentStop

**When:** A subagent (spawned agent) stops.

**Payload fields:**

| Field | Type | Description |
|-------|------|-------------|
| `session_id` | string | Subagent's session identifier |
| `transcript_path` | string | Path to subagent transcript |

**Handler actions:**

1. Logs the subagent's transcript entries to the hooks log

---

## Notification

**When:** Claude Code sends a notification (e.g., requesting user attention).

**Payload fields:** varies — the entire notification data object.

**Handler actions:**

1. Logs the notification event and payload

---

## PreCompact

**When:** Claude Code is about to compact the context window.

**Payload fields:**

| Field | Type | Description |
|-------|------|-------------|
| `session_id` | string | Session identifier |

**Handler actions:**

1. Logs a pre-compaction event marker

---

## PermissionRequest

**When:** Claude Code requests permission for an action that requires user approval.

**Payload fields:**

| Field | Type | Description |
|-------|------|-------------|
| `tool_name` | string | Tool requesting permission |
| _(other fields)_ | varies | Permission metadata |

**Handler actions:**

1. Logs the permission request and tool name

---

## Tool memory learning

`PreToolUse` and `PostToolUse` work together to implement cross-session error learning:

```mermaid
sequenceDiagram
    participant Agent
    participant PreToolUse
    participant ToolMemory as Tool Memory<br/>(.ndjson)
    participant PostToolUse

    Agent->>PreToolUse: about to call tool X
    PreToolUse->>ToolMemory: look up past errors for tool X
    ToolMemory-->>PreToolUse: last N error patterns
    PreToolUse-->>Agent: inject error patterns as context
    Agent->>PostToolUse: tool X returned error Y
    PostToolUse->>ToolMemory: record error Y for tool X
```

Configure via:

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENTICORE_TOOL_MEMORY_PATH` | `~/.agenticore_tool_memory.ndjson` | Memory file path |
| `AGENTICORE_TOOL_MEMORY_MAX` | `100` | Maximum stored entries |
| `AGENTICORE_TOOL_MEMORY_SHOW` | `15` | Entries injected per PreToolUse |
