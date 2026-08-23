"""Serve codex a model catalog that keeps each model's best-known window.

gpt-5.6-sol's long-context entitlement flaps: consecutive /models fetches under
one unchanged ETag alternate max_context_window 272000 and 872000, and a codex
session binds whichever body it fetched for its whole lifetime — 258,400 or
828,400 effective context, decided per launch. A capped session compacts more
than three times sooner.

``model_catalog_json`` in config.toml replaces that fetch outright, so the
window stops depending on which body the server happened to return. This module
owns the file that key points at: every SessionStart merges codex's live cache
into a per-slug high-water record and rewrites the catalog from it. A model is
only ever held to a window the server itself advertised for that exact slug, so
a small model is never inflated by a larger sibling, and a genuinely new
ceiling is adopted the first time it appears.
"""

from __future__ import annotations

import json
from pathlib import Path


def catalog_path() -> Path:
    from hooks.config import AGENTIHOOKS_HOME

    return AGENTIHOOKS_HOME / "codex_model_catalog.json"


def highwater_path() -> Path:
    from hooks.config import AGENTIHOOKS_HOME

    return AGENTIHOOKS_HOME / "codex_context_highwater.json"


def live_cache_path() -> Path:
    from hooks.targets import codex_home

    return codex_home() / "models_cache.json"


def _load(path: Path) -> dict | None:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return doc if isinstance(doc, dict) and doc.get("models") else None


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


def refresh() -> tuple[int, dict[str, int]] | None:
    """Rebuild the managed catalog from codex's live cache plus the high-water record.

    Returns ``(entries_restored, highwater)``, or None when neither the live
    cache nor a previously written catalog can be read.
    """
    live = live_cache_path()
    # An earlier build locked the live cache read-only to stop codex reverting
    # it. The catalog key made that unnecessary, and codex logs a write error
    # for as long as the lock survives.
    if live.exists():
        try:
            live.chmod(0o644)
        except OSError:
            pass

    doc = _load(live) or _load(catalog_path())
    if doc is None:
        return None

    store = highwater_path()
    try:
        highwater: dict[str, int] = json.loads(store.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, FileNotFoundError):
        highwater = {}

    restored = 0
    for entry in _models(doc):
        slug, window = entry["slug"], entry["max_context_window"]
        best = max(highwater.get(slug, 0), window)
        highwater[slug] = best
        if window < best:
            entry["max_context_window"] = best
            restored += 1

    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps(highwater, indent=2, sort_keys=True), encoding="utf-8")
    catalog_path().write_text(json.dumps(doc), encoding="utf-8")
    return (restored, highwater)
