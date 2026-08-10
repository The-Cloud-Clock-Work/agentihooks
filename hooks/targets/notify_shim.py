"""Bridge codex's ``notify`` mechanism into the Notification handler.

Codex has no general Notification hook — only the ``notify`` config key,
which invokes a program after each turn with a JSON payload as ``argv[1]``
(stdin is deliberately closed; single event type ``agent-turn-complete``).
This shim reshapes that payload into a Notification hook event and routes it
through the ordinary dispatch, so logging stays uniform across targets.

Wired by the codex config writer: ``notify = [<python>, "-m",
"hooks.targets.notify_shim"]``.
"""

from __future__ import annotations

import json
import os
import sys


def main() -> int:
    if len(sys.argv) < 2:
        return 0
    try:
        raw = json.loads(sys.argv[1])
    except json.JSONDecodeError:
        return 0
    os.environ.setdefault("AGENTIHOOKS_TARGET", "codex")
    payload = {
        "hook_event_name": "Notification",
        "notification_type": raw.get("type", ""),
        "session_id": raw.get("thread-id", ""),
        "turn_id": raw.get("turn-id", ""),
        "cwd": raw.get("cwd", ""),
        "message": raw.get("last-assistant-message", ""),
        "raw_notify_payload": raw,
    }
    try:
        from hooks.hook_manager import on_notification

        on_notification(payload)
    except Exception:
        pass  # notify must never disturb the codex session
    return 0


if __name__ == "__main__":
    sys.exit(main())
