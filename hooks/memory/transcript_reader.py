"""Transcript search and retrieval from agent.log.

Reads the JSONL agent transcript log and provides search/retrieval
across past conversation entries. Reuses extract_content() from
hooks/observability/transcript.py.
"""

import json
import os
from pathlib import Path
from typing import List, Optional

_AGENT_LOG = os.getenv("AGENT_LOG_FILE", "/app/logs/agent.log")


def _parse_entries(path: str) -> List[dict]:
    """Read agent.log JSONL and parse each line into a dict."""
    p = Path(path)
    if not p.exists():
        return []
    entries = []
    with open(p, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def _extract_text(entry: dict) -> Optional[str]:
    """Extract readable text from a transcript entry.

    Reuses the same logic as hooks.observability.transcript.extract_content.
    """
    message = entry.get("message")

    if isinstance(message, str):
        return message

    if isinstance(message, dict):
        content = message.get("content", [])
        if isinstance(content, list):
            texts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text", "")
                    if text:
                        texts.append(text)
            if texts:
                return "\n".join(texts)
        elif isinstance(content, str):
            return content

    return None


def search_transcripts(
    query: str,
    session_id: Optional[str] = None,
    limit: int = 20,
    log_path: Optional[str] = None,
) -> List[dict]:
    """Search agent.log for entries matching query.

    Returns list of {session_id, type, content, timestamp}.
    """
    path = log_path or _AGENT_LOG
    entries = _parse_entries(path)
    query_lower = query.lower()

    results = []
    for entry in reversed(entries):  # newest first
        if session_id and entry.get("session_id") != session_id:
            continue

        entry_type = entry.get("type", "unknown")
        if entry_type not in ("user", "assistant"):
            continue

        text = _extract_text(entry)
        if not text:
            continue

        if query_lower not in text.lower():
            continue

        results.append(
            {
                "session_id": entry.get("session_id", ""),
                "type": entry_type,
                "content": text[:2000],  # cap long entries
                "timestamp": entry.get("timestamp", ""),
            }
        )

        if len(results) >= limit:
            break

    return results


def get_session_transcript(
    session_id: str,
    last_n: int = 50,
    log_path: Optional[str] = None,
) -> List[dict]:
    """Get last N transcript entries for a specific session."""
    path = log_path or _AGENT_LOG
    entries = _parse_entries(path)

    session_entries = []
    for entry in entries:
        if entry.get("session_id") != session_id:
            continue

        entry_type = entry.get("type", "unknown")
        if entry_type not in ("user", "assistant"):
            continue

        text = _extract_text(entry)
        if not text:
            continue

        session_entries.append(
            {
                "session_id": session_id,
                "type": entry_type,
                "content": text[:2000],
                "timestamp": entry.get("timestamp", ""),
            }
        )

    # Return last N entries
    return session_entries[-last_n:]
