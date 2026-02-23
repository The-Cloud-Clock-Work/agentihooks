# Tool Memory

Cross-session error learning for Claude Code hooks.

## What It Does

Tool Memory records errors from tool calls and replays them at the start of the next session. Claude sees past mistakes and avoids repeating them.

**Example:** A bad JQL query fails with a syntax error. Next session, when Claude is about to use the Jira tool, it sees: *"Last time this query failed because single quotes aren't valid in JQL — use double quotes."* Claude adjusts automatically.

## How It Works

```
Session A (error happens):
  Claude calls MCP tool -> tool returns error
  PostToolUse hook -> record_error() -> saves to NDJSON file
  Stop hook -> scan_transcript() -> catches MCP errors missed by PostToolUse

Session B (learning applied):
  Claude is about to call a tool
  PreToolUse hook -> inject_memory() -> prints past errors to stdout
  Claude sees the errors in its context window -> adjusts behavior
```

## What Gets Captured

- MCP tool errors (explicit `is_error` flag only -- no false positives)
- Bash command failures (non-zero exit codes)
- Bash output containing error patterns (traceback, denied, timeout, etc.)

## What The Agent Sees

On PreToolUse, a formatted banner is injected into Claude's context window via `inject_banner()` from `common.py`. This is the same mechanism used by all other hook injections (output token limit, session context awareness).

```
=== CONTEXT INJECTION ===

╔══════════════════════════════════════════════════════════════════════════════╗
║  TOOL MEMORY: Lessons from past sessions                                     ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  [2025-02-10 14:32] mcp__jira_search -- Validation error: ...                ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

This only appears **once per tool per session** to avoid noise.

## Injection Mechanism

Hook stdout is the only channel to inject content into Claude's context at runtime. The call chain:

```
inject_memory() -> inject_banner() -> inject_context() -> print() to STDOUT
```

`inject_context()` does two things:
1. Prints to **STDOUT** -- Claude Code captures this and feeds it to the model
2. Writes to **hooks.log** via `log_command()` -- visible in `tail_debug` for observability

The banner does **not** appear in the JSONL transcript. Claude Code only logs `hook_progress` events (that a hook ran), not what it printed. To verify the banner fired, check `tail_debug` or the dedup tracking file at `/tmp/.tool_memory_seen_<session_id>`.

## Memory File

Stored as NDJSON (one JSON object per line):

- **Location:** `~/.agenticore_tool_memory.ndjson`
- **Max entries:** 100 (oldest rotated out)
- **Max shown:** 15 most recent per injection

Each line:
```json
{"ts":"2025-02-10T14:32:00Z","tool":"jira_search","error":"Validation error...","input":"jql=assignee = ...","session":"abc-123"}
```

## Error Detection Strategy

| Tool Type | Detection Method | Why |
|-----------|-----------------|-----|
| MCP tools (`mcp__*`) | `is_error` flag only | MCP responses contain arbitrary text (Jira descriptions with "error", "not found") that trigger false positives |
| Bash | `exitCode` + string pattern matching | Bash output is structured -- pattern matching is reliable |

## Integration

Tool memory is called from `hook_manager.py` (the centralized hook dispatcher):

| Hook Event | Function Called | Purpose |
|------------|----------------|---------|
| PreToolUse | `inject_memory()` | Show past errors to Claude |
| PostToolUse | `record_error()` | Save new errors from tool responses |
| Stop | `scan_transcript()` | Catch MCP errors that PostToolUse missed |

All imports are lazy-loaded inside handler functions.

## Per-Tool Dedup

Memory injection is tracked per tool per session via `/tmp/.tool_memory_seen_<session_id>`. Once Claude has seen memory for a given tool, it won't be shown again in the same session -- even if that tool is called 50 times.

## Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `AGENTICORE_TOOL_MEMORY_PATH` | `~/.agenticore_tool_memory.ndjson` | Memory file location |
| `AGENTICORE_TOOL_MEMORY_MAX` | `100` | Max entries to keep |
| `AGENTICORE_TOOL_MEMORY_SHOW` | `15` | Max entries shown per injection |

## Key Limitation

Claude Code does **not** fire PostToolUse when MCP tools return errors. The `scan_transcript()` function on the Stop hook compensates by scanning the full transcript at session end.
