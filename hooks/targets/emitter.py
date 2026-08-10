"""Single choke point for context output back to the host CLI.

Claude Code concatenates every raw stdout line into injected context, so
handlers can print as many times as they like. Codex parses hook stdout as
ONE JSON object — multiple prints would corrupt it. Under codex, context is
buffered here across the whole hook process and flushed exactly once, as a
single ``hookSpecificOutput.additionalContext`` envelope, by ``main()``
right before exit. Events with no context channel on the target (codex
PreToolUse) drop the buffer with a log line instead.
"""

from __future__ import annotations

import json

from hooks.targets import is_codex
from hooks.targets.capabilities import can_inject_context

_buffer: list[str] = []


def buffer_context(content: str) -> None:
    """Queue *content* for the single end-of-process flush (codex path)."""
    _buffer.append(content)


def has_buffered() -> bool:
    return bool(_buffer)


def flush(event_name: str) -> None:
    """Emit the buffered context as one JSON envelope. Codex only; no-op when empty."""
    if not _buffer:
        return
    content = "\n".join(_buffer)
    _buffer.clear()
    if not is_codex():
        # Claude path never buffers; guard against misuse.
        print(content)
        return
    if not can_inject_context(event_name):
        from hooks.common import log

        log(
            "emitter: context dropped — no context channel for event on codex",
            {"event": event_name, "chars": len(content)},
        )
        return
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": event_name,
                    "additionalContext": content,
                }
            }
        )
    )
