"""Hold each codex model at the largest context window it has ever advertised.

gpt-5.6-sol's long-context entitlement flaps: consecutive /models fetches under
one unchanged ETag alternate max_context_window 272000 and 872000, and a codex
session binds whichever body it happened to fetch for its whole lifetime. Codex
re-fetches at every session start, so the usable window was a coin flip per
launch — 258,400 or 828,400 effective — and a capped session compacts more than
three times sooner.

Every SessionStart records a per-slug high-water mark and rewrites any entry
the catalog has since walked back, then locks the file read-only so codex
prefers the recorded value. A model is only ever raised to a window the server
itself advertised for that exact slug, so a genuinely small model is never
inflated by a larger sibling.
"""

from __future__ import annotations

import json
from pathlib import Path

_LOCKED = 0o444
_WRITABLE = 0o644


def cache_path() -> Path:
    from hooks.targets import codex_home

    return codex_home() / "models_cache.json"


def highwater_path() -> Path:
    from hooks.config import AGENTIHOOKS_HOME

    return AGENTIHOOKS_HOME / "codex_context_highwater.json"


def _models(node: object) -> list[dict]:
    found: list[dict] = []
    if isinstance(node, dict):
        if isinstance(node.get("max_context_window"), int) and node.get("slug"):
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


def pin() -> tuple[int, dict[str, int]] | None:
    """Restore every walked-back window from its recorded high-water mark.

    Returns ``(entries_raised, highwater)`` or None when there is no catalog.
    """
    path = cache_path()
    if not path.exists():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    entries = _models(doc)
    if not entries:
        return None

    store = highwater_path()
    try:
        highwater: dict[str, int] = json.loads(store.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, FileNotFoundError):
        highwater = {}

    raised = []
    for entry in entries:
        slug, window = entry["slug"], entry["max_context_window"]
        seen = max(highwater.get(slug, 0), window)
        highwater[slug] = seen
        if window < seen:
            entry["max_context_window"] = seen
            raised.append(slug)

    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps(highwater, indent=2, sort_keys=True), encoding="utf-8")

    if raised:
        path.chmod(_WRITABLE)
        path.write_text(json.dumps(doc), encoding="utf-8")
    path.chmod(_LOCKED)
    return (len(raised), highwater)
