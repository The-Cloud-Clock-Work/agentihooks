"""Normalize a Codex or Copilot hook payload into the shape handlers consume.

Codex cloned Claude Code's hook stdin contract almost verbatim (same
``hook_event_name``, ``tool_name``/``tool_input``/``tool_response``,
``session_id``/``transcript_path``/``cwd``), so that path is alias-filling,
not translation.

Copilot sends the same fields camelCased (``sessionId``, ``toolName``,
``toolArgs``, ``cwd``) and stores its transcript as a session-events log
rather than a rollout, so its path fills both spellings and resolves
``events.jsonl``.

Claude payloads pass through untouched so the claude behavior stays
byte-identical.
"""

from __future__ import annotations

import glob
import os
import re
from pathlib import Path
from typing import Any

from hooks.targets import is_codex, is_copilot

# Events whose handlers read the transcript: session digest/metrics, brain
# marker capture, auto-save, compaction. Tool events deliberately excluded.
_TRANSCRIPT_EVENTS = frozenset({"SessionEnd", "Stop", "SubagentStop", "PreCompact"})


def _codex_home() -> Path:
    raw = (os.environ.get("CODEX_HOME") or "").split(",")[0].strip()
    return Path(raw).expanduser() if raw else Path.home() / ".codex"


def _copilot_home() -> Path:
    raw = (os.environ.get("COPILOT_HOME") or "").split(",")[0].strip()
    return Path(raw).expanduser() if raw else Path.home() / ".copilot"


# A codex session id is a UUID; anything else is refused rather than
# interpolated into a glob, where `*`/`?`/`[` would match another session's
# rollout and `**` would raise ValueError out of the hook process.
_SESSION_ID_SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")

# Rollouts live under sessions/YYYY/MM/DD. A hook only ever asks about the
# session it is running in, so the newest day directories hold it; walking
# them newest-first turns the common case into one directory scan instead of
# a walk of the operator's entire session history.
_RECENT_DAY_DIRS = 8


def _day_dirs_newest_first(sessions: Path) -> list[Path]:
    days: list[Path] = []
    try:
        for year in sorted((d for d in sessions.iterdir() if d.is_dir()), reverse=True):
            for month in sorted((d for d in year.iterdir() if d.is_dir()), reverse=True):
                days.extend(sorted((d for d in month.iterdir() if d.is_dir()), reverse=True))
                if len(days) >= _RECENT_DAY_DIRS:
                    return days[:_RECENT_DAY_DIRS]
    except OSError:
        return days[:_RECENT_DAY_DIRS]
    return days[:_RECENT_DAY_DIRS]


def codex_rollout_path(session_id: str) -> str:
    """Locate the rollout jsonl for *session_id*, or "" if there is none.

    Codex omits ``transcript_path`` from its hook payloads, so every
    transcript-driven feature (brain markers, auto-save, tool-memory error
    scanning, session metrics) would silently no-op. Rollouts are written to
    ``<codex home>/sessions/YYYY/MM/DD/rollout-<stamp>-<session id>.jsonl``,
    and the session id is unique, so the first match is the file.

    Never raises: a hook that dies here would skip every guardrail for that
    event, so any lookup failure degrades to "no transcript".
    """
    if not session_id or not _SESSION_ID_SAFE.fullmatch(session_id):
        return ""
    sessions = _codex_home() / "sessions"
    pattern = f"rollout-*{glob.escape(session_id)}.jsonl"
    try:
        if not sessions.is_dir():
            return ""
        for day in _day_dirs_newest_first(sessions):
            match = next(day.glob(pattern), None)
            if match:
                return str(match)
        # Older than the recent window (a long-dormant session resumed today
        # still writes into today's directory, so this is the rare path).
        match = next(sessions.glob(f"**/{pattern}"), None)
        return str(match) if match else ""
    except (OSError, ValueError, RuntimeError):
        return ""


def copilot_events_path(session_id: str) -> str:
    """Locate the session-events jsonl for *session_id*, or "" if there is none.

    Copilot writes ``<copilot home>/session-state/<session id>/events.jsonl``
    and omits ``transcript_path`` from hook payloads, so every
    transcript-driven feature would silently no-op without this. The session
    id is a path segment here, not a glob, so it is validated against the same
    charset the codex resolver uses before being joined.

    Never raises: a hook that dies here would skip every guardrail for that
    event, so any lookup failure degrades to "no transcript".
    """
    if not session_id or not _SESSION_ID_SAFE.fullmatch(session_id):
        return ""
    try:
        events = _copilot_home() / "session-state" / session_id / "events.jsonl"
        return str(events) if events.is_file() else ""
    except (OSError, ValueError, RuntimeError):
        return ""


# Copilot dispatches its own camelCase event names and also accepts the
# Claude-style PascalCase aliases at registration. Which spelling comes back in
# the payload is not contractual — and the adapter registers the PascalCase
# ones — so BOTH must resolve. An unmapped name reaches no handler and exits 0,
# silently bypassing every guardrail for that event, so the identity entries
# below are load-bearing, not cosmetic.
#
# postToolUseFailure has no distinct handler — it is the failure arm of
# PostToolUse and carries the same payload plus an error, so folding it in is
# what lets tool-error recording see copilot failures at all.
#
# postResult and prePRDescription are deliberately absent: the adapter does not
# register them, and folding them onto Stop would re-run session-end work once
# per result. hook_manager logs one as an unknown event if it ever arrives.
_COPILOT_EVENTS = {
    "sessionStart": "SessionStart",
    "sessionEnd": "SessionEnd",
    "userPromptSubmitted": "UserPromptSubmit",
    "userPromptTransformed": "UserPromptSubmit",
    "preToolUse": "PreToolUse",
    "preMcpToolCall": "PreToolUse",
    "postToolUse": "PostToolUse",
    "postToolUseFailure": "PostToolUse",
    "agentStop": "Stop",
    "subagentStart": "SubagentStart",
    "subagentStop": "SubagentStop",
    "preCompact": "PreCompact",
    "permissionRequest": "PermissionRequest",
    "notification": "Notification",
    "errorOccurred": "Notification",
}
# Identity entries so the PascalCase spelling the adapter registers under
# resolves too. Derived, not hand-listed: a value added above cannot be
# forgotten here.
_COPILOT_EVENTS.update({v: v for v in list(_COPILOT_EVENTS.values())})
# PascalCase names the adapter registers that are NOT their own dispatch name,
# so the derived identity pass above cannot cover them.
_COPILOT_EVENTS["PostToolUseFailure"] = "PostToolUse"


# Copilot hook payload keys → the snake_case spelling handlers read.
_COPILOT_ALIASES = (
    ("sessionId", "session_id"),
    ("toolName", "tool_name"),
    ("toolArgs", "tool_input"),
    ("toolResult", "tool_response"),
    ("transcriptPath", "transcript_path"),
    ("workspaceRoot", "cwd"),
)


def _normalize_copilot(payload: dict[str, Any]) -> dict[str, Any]:
    raw_event = payload.get("hookEventName") or payload.get("hook_event_name") or ""
    mapped = _COPILOT_EVENTS.get(raw_event)
    if mapped:
        payload["hook_event_name"] = mapped
        payload.setdefault("copilot_event_name", raw_event)

    # Not setdefault: a destination key that is PRESENT but empty ({} / "" /
    # None) would win over the real value and hand every guardrail blank
    # arguments while the tool call still executes. Fill whenever the
    # destination has no content of its own.
    for camel, snake in _COPILOT_ALIASES:
        value = payload.get(camel)
        if value:
            if not payload.get(snake):
                payload[snake] = value
        elif payload.get(snake):
            payload[camel] = payload[snake]

    resp = payload.get("tool_response")
    if resp is not None:
        payload.setdefault("tool_output", resp)
        payload.setdefault("tool_result", resp)

    if payload.get("hook_event_name", "") in _TRANSCRIPT_EVENTS and not payload.get("transcript_path"):
        resolved = copilot_events_path(str(payload.get("session_id", "")))
        if resolved:
            payload["transcript_path"] = resolved
    return payload


def normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if is_copilot():
        return _normalize_copilot(payload)
    if not is_codex():
        return payload

    # Some handlers read the older ``tool_output`` / ``tool_result`` aliases.
    resp = payload.get("tool_response")
    if resp is not None:
        payload.setdefault("tool_output", resp)
        payload.setdefault("tool_result", resp)

    # Codex never sends ``transcript_path``; resolve its rollout from the
    # session id so transcript-driven features work the same on both targets.
    # Only on the events that actually read a transcript — resolving on every
    # PreToolUse/PostToolUse would charge a filesystem lookup to every tool
    # call in the turn for consumers that never look at the value.
    if payload.get("hook_event_name", "") in _TRANSCRIPT_EVENTS and not payload.get("transcript_path"):
        resolved = codex_rollout_path(str(payload.get("session_id", "")))
        if resolved:
            payload["transcript_path"] = resolved

    # Codex SessionEnd carries ``reason`` (currently only "other"); nothing to map.
    # Codex adds ``turn_id`` on turn-scoped events; handlers ignore unknown keys.
    return payload
