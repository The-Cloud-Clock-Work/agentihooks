"""Auto-save session digest as a memory on Stop.

Reads the transcript, extracts user prompts + assistant responses,
creates a condensed digest, and stores it via MemoryStore.
"""

from pathlib import Path
from typing import Optional

from hooks.common import log


def auto_save_session(session_id: str, transcript_path: str) -> None:
    """Extract conversation digest from transcript and save as memory.

    Called by hook_manager.on_stop() when MEMORY_AUTO_SAVE is enabled.
    Silent failure — never breaks Claude.
    """
    path = Path(transcript_path)
    if not path.exists():
        return

    try:
        entries = _read_transcript(path)
        if not entries:
            return

        digest = _build_digest(entries, session_id)
        if not digest:
            return

        from hooks.memory.store import MemoryStore

        store = MemoryStore()
        store.save(
            content=digest,
            tags=["auto", "session-summary"],
            summary=_build_summary(entries),
            session_id=session_id,
            source="auto",
        )

        log("Memory auto-save completed", {"session_id": session_id})

    except Exception as e:
        log("Memory auto-save failed", {"session_id": session_id, "error": str(e)})


def _read_transcript(path: Path) -> list[dict]:
    """Extract user/assistant text entries from a claude or codex transcript."""
    from hooks.memory.transcript_reader import iter_transcript_records

    entries = []
    for rec in iter_transcript_records(path):
        kind = rec.get("kind", "")
        if kind == "user_text":
            entries.append({"type": "user", "text": rec.get("text", "")})
        elif kind in ("assistant_text", "turn_complete") and rec.get("text"):
            entries.append({"type": "assistant", "text": rec.get("text", "")})
    return entries


def _build_summary(entries: list[dict]) -> str:
    """Build a one-line summary from the first user message."""
    for entry in entries:
        if entry["type"] == "user":
            text = entry["text"].strip()
            # Take first line, truncate to 100 chars
            first_line = text.split("\n")[0][:100]
            return first_line
    return "Session summary"


def _build_digest(entries: list[dict], session_id: str) -> Optional[str]:
    """Build condensed session digest.

    Format:
        [Task] <first user message>
        [Result] <last assistant response>
        [Stats] N turns, session_id
    """
    if not entries:
        return None

    user_entries = [e for e in entries if e["type"] == "user"]
    assistant_entries = [e for e in entries if e["type"] == "assistant"]

    if not user_entries:
        return None

    first_user = user_entries[0]["text"].strip()
    last_assistant = assistant_entries[-1]["text"].strip() if assistant_entries else "(no response)"

    num_turns = len(user_entries) + len(assistant_entries)

    # Build digest
    parts = [
        f"[Task] {first_user}",
        f"[Result] {last_assistant}",
        f"[Stats] {num_turns} turns | session: {session_id}",
    ]
    digest = "\n\n".join(parts)

    # Truncate if too long (keep task and result visible)
    max_len = 4000
    if len(digest) > max_len:
        # Truncate the middle (result section)
        task_section = parts[0][:1500]
        stats_section = parts[2]
        remaining = max_len - len(task_section) - len(stats_section) - 100
        result_section = f"[Result] {last_assistant[:remaining]}..."
        omitted = num_turns - 2
        digest = f"{task_section}\n\n[... {omitted} messages omitted ...]\n\n{result_section}\n\n{stats_section}"

    return digest
