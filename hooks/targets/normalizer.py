"""Normalize a Codex hook payload into the shape the handlers consume.

Codex cloned Claude Code's hook stdin contract almost verbatim (same
``hook_event_name``, ``tool_name``/``tool_input``/``tool_response``,
``session_id``/``transcript_path``/``cwd``), so this is alias-filling, not
translation. Runs only under the codex target; claude payloads pass through
untouched so the claude behavior stays byte-identical.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from hooks.targets import is_codex


def _codex_home() -> Path:
    raw = (os.environ.get("CODEX_HOME") or "").split(",")[0].strip()
    return Path(raw).expanduser() if raw else Path.home() / ".codex"


def codex_rollout_path(session_id: str) -> str:
    """Locate the rollout jsonl for *session_id*, or "" if there is none.

    Codex omits ``transcript_path`` from its hook payloads, so every
    transcript-driven feature (brain markers, auto-save, tool-memory error
    scanning, session metrics) would silently no-op. Rollouts are written to
    ``<codex home>/sessions/YYYY/MM/DD/rollout-<stamp>-<session id>.jsonl``,
    and the session id is unique, so the first match is the file.
    """
    if not session_id:
        return ""
    sessions = _codex_home() / "sessions"
    if not sessions.is_dir():
        return ""
    try:
        match = next(sessions.glob(f"**/rollout-*{session_id}.jsonl"), None)
    except OSError:
        return ""
    return str(match) if match else ""


def normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not is_codex():
        return payload

    # Some handlers read the older ``tool_output`` / ``tool_result`` aliases.
    resp = payload.get("tool_response")
    if resp is not None:
        payload.setdefault("tool_output", resp)
        payload.setdefault("tool_result", resp)

    # Codex never sends ``transcript_path``; resolve its rollout from the
    # session id so transcript-driven features work the same on both targets.
    if not payload.get("transcript_path"):
        resolved = codex_rollout_path(str(payload.get("session_id", "")))
        if resolved:
            payload["transcript_path"] = resolved

    # Codex SessionEnd carries ``reason`` (currently only "other"); nothing to map.
    # Codex adds ``turn_id`` on turn-scoped events; handlers ignore unknown keys.
    return payload
