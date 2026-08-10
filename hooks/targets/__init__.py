"""Hook-runtime target detection.

Which agent CLI invoked this hook process. Claude Code is the default; the
Codex hooks.json writer sets ``AGENTIHOOKS_TARGET=codex`` in every hook
command, so detection is a deterministic env read — no payload sniffing.
Read per-call (not bound at import) so tests and long-lived processes see
the live value.
"""

from __future__ import annotations

import os


def current_target() -> str:
    return os.environ.get("AGENTIHOOKS_TARGET", "").strip().lower() or "claude"


def is_codex() -> bool:
    return current_target() == "codex"


def global_record(state: dict) -> dict:
    """The current target's record under ``targets.global`` in state.json.

    Tolerates both the target-keyed shape ({"claude": {...}, "codex": {...}})
    and the legacy flat shape (pre-migration state files, where the record's
    fields sit directly under "global").
    """
    g = state.get("targets", {}).get("global", {})
    if not isinstance(g, dict):
        return {}
    rec = g.get(current_target())
    if isinstance(rec, dict):
        return rec
    if g and any(not isinstance(v, dict) for v in g.values()):
        return g
    return {}
