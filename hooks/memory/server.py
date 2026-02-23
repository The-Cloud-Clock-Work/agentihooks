#!/usr/bin/env python3
"""Memory MCP Server.

Provides persistent cross-session memory for agents via MCP tools.
Memories are stored in Redis (no TTL) with JSONL file fallback.

Usage:
    python -m hooks.memory.server

Available tools:
    - memory_save       — Store a memory for future recall
    - memory_search     — Keyword search across memories
    - memory_recall     — Get recent / filtered memories
    - memory_delete     — Remove a specific memory
    - memory_clear      — Wipe all memories
    - transcript_search — Search agent.log transcripts
    - transcript_get    — Get transcript for a session
"""

import json
import os

from mcp.server.fastmcp import FastMCP

from hooks.common import log

# =============================================================================
# MCP SERVER INITIALIZATION
# =============================================================================

mcp = FastMCP("memory-mcp")

# Lazy singleton for MemoryStore
_store = None


def _get_store():
    global _store
    if _store is None:
        from hooks.memory.store import MemoryStore
        _store = MemoryStore()
    return _store


# =============================================================================
# MEMORY TOOLS
# =============================================================================


@mcp.tool()
def memory_save(
    content: str,
    tags: str = "",
    summary: str = "",
    session_id: str = "",
) -> str:
    """Save a memory for future recall across sessions.

    Memories persist until explicitly deleted. Use tags for organization.

    Args:
        content: The memory text to store
        tags: Comma-separated tags for categorization (e.g., "architecture,fastapi")
        summary: Short one-line summary (auto-generated from first 100 chars if empty)
        session_id: Source session ID (defaults to "manual")

    Returns:
        JSON with memory id, summary, and tags
    """
    try:
        store = _get_store()

        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

        mem = store.save(
            content=content,
            tags=tag_list,
            summary=summary if summary else None,
            session_id=session_id if session_id else None,
            source="manual",
        )

        return json.dumps({
            "success": True,
            "id": mem.id,
            "summary": mem.summary,
            "tags": mem.tags,
            "created_at": mem.created_at,
        })

    except Exception as e:
        log("MCP memory_save failed", {"error": str(e)})
        return json.dumps({"success": False, "error": str(e)})


@mcp.tool()
def memory_search(
    query: str,
    tags: str = "",
    limit: int = 10,
) -> str:
    """Search memories by keyword across content, summary, and tags.

    Args:
        query: Search keyword or phrase
        tags: Comma-separated tags to filter by (all must match)
        limit: Maximum results to return (default: 10)

    Returns:
        JSON with list of matching memories sorted by recency
    """
    try:
        store = _get_store()

        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None

        results = store.search(query=query, tags=tag_list, limit=limit)

        return json.dumps({
            "success": True,
            "count": len(results),
            "memories": [m.to_dict() for m in results],
        })

    except Exception as e:
        log("MCP memory_search failed", {"query": query, "error": str(e)})
        return json.dumps({"success": False, "error": str(e)})


@mcp.tool()
def memory_recall(
    session_id: str = "",
    tags: str = "",
    limit: int = 10,
    since_hours: int = 0,
) -> str:
    """Recall recent memories, optionally filtered by session, tags, or time.

    Args:
        session_id: Filter by source session ID
        tags: Comma-separated tags to filter by (all must match)
        limit: Maximum results to return (default: 10)
        since_hours: Only return memories from the last N hours (0 = no limit)

    Returns:
        JSON with list of memories sorted by recency
    """
    try:
        store = _get_store()

        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None

        results = store.recall(
            session_id=session_id if session_id else None,
            tags=tag_list,
            limit=limit,
            since_hours=since_hours if since_hours > 0 else None,
        )

        return json.dumps({
            "success": True,
            "count": len(results),
            "memories": [m.to_dict() for m in results],
        })

    except Exception as e:
        log("MCP memory_recall failed", {"error": str(e)})
        return json.dumps({"success": False, "error": str(e)})


@mcp.tool()
def memory_delete(memory_id: str) -> str:
    """Delete a specific memory by ID.

    Args:
        memory_id: UUID of the memory to delete

    Returns:
        JSON with success status
    """
    try:
        store = _get_store()
        deleted = store.delete(memory_id)

        return json.dumps({
            "success": True,
            "deleted": deleted,
            "memory_id": memory_id,
        })

    except Exception as e:
        log("MCP memory_delete failed", {"memory_id": memory_id, "error": str(e)})
        return json.dumps({"success": False, "error": str(e)})


@mcp.tool()
def memory_clear(confirm: bool = False) -> str:
    """Clear ALL memories. Requires confirm=true.

    Args:
        confirm: Must be true to proceed with deletion

    Returns:
        JSON with count of deleted memories
    """
    if not confirm:
        return json.dumps({
            "success": False,
            "error": "Set confirm=true to clear all memories",
        })

    try:
        store = _get_store()
        count = store.clear()

        return json.dumps({
            "success": True,
            "cleared": count,
        })

    except Exception as e:
        log("MCP memory_clear failed", {"error": str(e)})
        return json.dumps({"success": False, "error": str(e)})


# =============================================================================
# TRANSCRIPT TOOLS
# =============================================================================


@mcp.tool()
def transcript_search(
    query: str,
    session_id: str = "",
    limit: int = 20,
) -> str:
    """Search through past conversation transcripts in agent.log.

    Args:
        query: Search keyword or phrase
        session_id: Filter to a specific session
        limit: Maximum results (default: 20)

    Returns:
        JSON with matching transcript entries
    """
    try:
        from hooks.memory.transcript_reader import search_transcripts

        results = search_transcripts(
            query=query,
            session_id=session_id if session_id else None,
            limit=limit,
        )

        return json.dumps({
            "success": True,
            "count": len(results),
            "entries": results,
        })

    except Exception as e:
        log("MCP transcript_search failed", {"query": query, "error": str(e)})
        return json.dumps({"success": False, "error": str(e)})


@mcp.tool()
def transcript_get(
    session_id: str,
    last_n: int = 50,
) -> str:
    """Get transcript entries for a specific session.

    Args:
        session_id: Session ID to retrieve
        last_n: Number of most recent entries to return (default: 50)

    Returns:
        JSON with transcript entries for the session
    """
    try:
        from hooks.memory.transcript_reader import get_session_transcript

        entries = get_session_transcript(
            session_id=session_id,
            last_n=last_n,
        )

        return json.dumps({
            "success": True,
            "session_id": session_id,
            "count": len(entries),
            "entries": entries,
        })

    except Exception as e:
        log("MCP transcript_get failed", {"session_id": session_id, "error": str(e)})
        return json.dumps({"success": False, "error": str(e)})


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================


def main():
    """Run the memory MCP server."""
    import sys
    print("Starting memory-mcp server...", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    available_tools = mcp._tool_manager.list_tools()
    print(f"Available tools: {len(available_tools)}", file=sys.stderr)
    for tool in available_tools:
        print(f"  - {tool.name}", file=sys.stderr)

    print("=" * 60, file=sys.stderr)
    mcp.run()


if __name__ == "__main__":
    main()
