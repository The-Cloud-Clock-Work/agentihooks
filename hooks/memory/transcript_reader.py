"""Transcript reading: agent.log search plus the unified transcript-record API.

Two responsibilities share this module because they are the same shape of
problem — "parse a JSONL conversation log into a usable record stream":

1. agent.log search/retrieval (the original content, below).
2. ``iter_transcript_records`` — ONE parser for the ``transcript_path`` a hook
   payload points at, covering both host formats:
   - Claude Code transcripts: entries ``{type: user|assistant, message:
     {content: [{type: text|tool_use|tool_result, ...}]}}`` (JSONL or a bare
     JSON array).
   - Codex rollouts (verified against codex-cli 0.147.0): lines ``{type,
     payload}`` where ``response_item`` payloads carry ``{type: message, role,
     content: [{type: input_text|output_text, text}]}`` /
     ``function_call`` / ``function_call_output``, and ``event_msg`` payloads
     carry ``token_count`` / ``task_complete`` (with ``last_agent_message``).

   Consumers (brain_writer marker scan, tool_memory error scan, memory
   auto-save, Stop metrics) iterate records instead of hand-rolling the
   Claude JSONL shape — which this repo had done six separate times.
"""

import json
import os
from pathlib import Path
from typing import Iterator, List, Optional, TypedDict

from hooks.config import AGENTIHOOKS_HOME


class TranscriptRecord(TypedDict, total=False):
    kind: str  # user_text | assistant_text | system_text | tool_call | tool_result | token_usage | turn_complete | meta
    text: str
    tool_name: str
    tool_input: object
    tool_result: object
    tool_use_id: str
    is_error: bool
    raw: dict


def detect_transcript_format(path: str | Path) -> str:
    """Return ``"codex"`` or ``"claude"`` by peeking at the first record."""
    p = Path(path)
    try:
        with open(p) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                if line.startswith("["):
                    return "claude"  # bare-array variant is claude-only
                try:
                    first = json.loads(line)
                except json.JSONDecodeError:
                    return "claude"
                if first.get("type") in ("session_meta", "response_item", "event_msg", "turn_context"):
                    return "codex"
                return "claude"
    except OSError:
        pass
    return "claude"


def _load_entries(path: Path) -> list[dict]:
    """Tolerant load: JSONL (skipping bad lines) or a bare JSON array."""
    try:
        content = path.read_text().strip()
    except OSError:
        return []
    if not content:
        return []
    if content.startswith("["):
        try:
            loaded = json.loads(content)
            return loaded if isinstance(loaded, list) else []
        except json.JSONDecodeError:
            return []
    entries = []
    for line in content.split("\n"):
        line = line.strip()
        if line:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def _iter_claude_records(entries: list[dict]) -> Iterator[TranscriptRecord]:
    for entry in entries:
        etype = entry.get("type")
        if etype not in ("user", "assistant"):
            continue
        message = entry.get("message")
        content = message.get("content", []) if isinstance(message, dict) else []
        if isinstance(content, str):
            kind = "assistant_text" if etype == "assistant" else "user_text"
            yield {"kind": kind, "text": content, "raw": entry}
            continue
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                kind = "assistant_text" if etype == "assistant" else "user_text"
                yield {"kind": kind, "text": block.get("text", ""), "raw": entry}
            elif btype == "tool_use":
                yield {
                    "kind": "tool_call",
                    "tool_name": block.get("name", ""),
                    "tool_input": block.get("input"),
                    "tool_use_id": block.get("id", ""),
                    "raw": entry,
                }
            elif btype == "tool_result":
                yield {
                    "kind": "tool_result",
                    "tool_result": block.get("content"),
                    "tool_use_id": block.get("tool_use_id", ""),
                    "is_error": bool(block.get("is_error")),
                    "raw": entry,
                }


def _iter_codex_records(entries: list[dict]) -> Iterator[TranscriptRecord]:
    for entry in entries:
        etype = entry.get("type")
        payload = entry.get("payload", {})
        if not isinstance(payload, dict):
            continue
        if etype == "response_item":
            ptype = payload.get("type")
            if ptype == "message":
                role = payload.get("role", "")
                kind = {
                    "assistant": "assistant_text",
                    "user": "user_text",
                }.get(role, "system_text")
                texts = [
                    b.get("text", "")
                    for b in payload.get("content", [])
                    if isinstance(b, dict) and b.get("type") in ("input_text", "output_text", "text")
                ]
                if texts:
                    yield {"kind": kind, "text": "\n".join(texts), "raw": entry}
            elif ptype in ("function_call", "local_shell_call", "custom_tool_call"):
                yield {
                    "kind": "tool_call",
                    "tool_name": payload.get("name", ptype),
                    "tool_input": payload.get("arguments") or payload.get("action"),
                    "tool_use_id": payload.get("call_id", ""),
                    "raw": entry,
                }
            elif ptype in ("function_call_output", "custom_tool_call_output"):
                output = payload.get("output")
                yield {
                    "kind": "tool_result",
                    "tool_result": output,
                    "tool_use_id": payload.get("call_id", ""),
                    # Codex does not carry an is_error flag on outputs; leave
                    # False and let consumers pattern-match the content.
                    "is_error": False,
                    "raw": entry,
                }
        elif etype == "event_msg":
            ptype = payload.get("type")
            if ptype == "token_count":
                yield {"kind": "token_usage", "raw": entry}
            elif ptype == "task_complete":
                yield {
                    "kind": "turn_complete",
                    "text": payload.get("last_agent_message") or "",
                    "raw": entry,
                }
        elif etype == "session_meta":
            yield {"kind": "meta", "raw": entry}


def iter_transcript_records(path: str | Path) -> Iterator[TranscriptRecord]:
    """Yield unified records from a Claude transcript or a Codex rollout."""
    p = Path(path)
    if not p.exists():
        return
    entries = _load_entries(p)
    if not entries:
        return
    fmt = detect_transcript_format(p)
    if fmt == "codex":
        yield from _iter_codex_records(entries)
    else:
        yield from _iter_claude_records(entries)


_AGENT_LOG = os.getenv("AGENT_LOG_FILE", str(AGENTIHOOKS_HOME / "logs" / "agent.log"))


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
