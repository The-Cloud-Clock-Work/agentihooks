"""Hold codex's model catalog at the largest context window it has advertised.

gpt-5.6-sol's long-context entitlement flaps: consecutive /models fetches under
one unchanged ETag alternate max_context_window 272000 and 872000, and a codex
session binds whichever body it happened to fetch for its whole lifetime. Codex
re-fetches at every session start, so the usable window is a coin flip per
launch — 258,400 or 828,400 effective. Raising the capped entries to the
ceiling the catalog itself advertises elsewhere and denying codex write access
to the cache makes the window stable. Codex logs a non-fatal
"failed to write models cache: Permission denied" and runs normally.

The cost is real: while pinned, codex cannot pick up catalog updates.
``agentihooks init --target codex`` unpins, so a re-init refreshes the catalog
and re-pins against the newer ceiling.
"""

from __future__ import annotations

import json
import stat
from pathlib import Path

_LOCKED = 0o444
_WRITABLE = 0o644


def cache_path() -> Path:
    from hooks.targets import codex_home

    return codex_home() / "models_cache.json"


def _models(node: object) -> list[dict]:
    found: list[dict] = []
    if isinstance(node, dict):
        if "max_context_window" in node:
            found.append(node)
        for value in node.values():
            found.extend(_models(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(_models(value))
    return found


def unpin() -> bool:
    path = cache_path()
    if not path.exists():
        return False
    path.chmod(_WRITABLE)
    return True


def pin(ceiling: int | None = None) -> tuple[int, int] | None:
    """Lift capped entries to *ceiling* and lock the cache.

    Returns ``(entries_raised, ceiling)``, or None when there is nothing to
    pin. With no explicit ceiling the catalog's own highest advertised window
    is used, so a future rollout raises the floor for every model at once.
    """
    path = cache_path()
    if not path.exists():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    entries = _models(doc)
    windows = [e["max_context_window"] for e in entries if isinstance(e.get("max_context_window"), int)]
    if not windows:
        return None
    target = ceiling or max(windows)

    raised = [e for e in entries if isinstance(e.get("max_context_window"), int) and e["max_context_window"] < target]
    if raised:
        for entry in raised:
            entry["max_context_window"] = target
        path.chmod(_WRITABLE)
        path.write_text(json.dumps(doc), encoding="utf-8")
    elif stat.S_IMODE(path.stat().st_mode) == _LOCKED:
        return (0, target)

    path.chmod(_LOCKED)
    return (len(raised), target)
