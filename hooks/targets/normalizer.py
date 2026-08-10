"""Normalize a Codex hook payload into the shape the handlers consume.

Codex cloned Claude Code's hook stdin contract almost verbatim (same
``hook_event_name``, ``tool_name``/``tool_input``/``tool_response``,
``session_id``/``transcript_path``/``cwd``), so this is alias-filling, not
translation. Runs only under the codex target; claude payloads pass through
untouched so the claude behavior stays byte-identical.
"""

from __future__ import annotations

from typing import Any

from hooks.targets import is_codex


def normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not is_codex():
        return payload

    # Some handlers read the older ``tool_output`` / ``tool_result`` aliases.
    resp = payload.get("tool_response")
    if resp is not None:
        payload.setdefault("tool_output", resp)
        payload.setdefault("tool_result", resp)

    # Codex SessionEnd carries ``reason`` (currently only "other"); nothing to map.
    # Codex adds ``turn_id`` on turn-scoped events; handlers ignore unknown keys.
    return payload
