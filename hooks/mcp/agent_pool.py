"""Agent-pool MCP tools — directed agent-to-agent (A2A) messaging.

- ``call_agent``: message a specific peer by session id. Routed by liveness —
  a live peer is notified via directed inbox AND read via a throwaway fork; a
  dormant peer is resumed and answers directly. Never corrupts a live peer's
  transcript.
- ``pool_list``: who is live in the fleet + what they're working on (scan this
  before deciding whom to call).
- ``pool_status``: self-declare what THIS session is working on.
"""

import json

import anyio

from hooks.common import log
from hooks.mcp._session import resolve_session_id


def register(mcp):
    @mcp.tool()
    async def call_agent(target_session_id: str, message: str, session_id: str = "") -> str:
        """Send a message to a specific fleet agent by its session id.

        Use this to coordinate directly with a peer — e.g. you find (via
        ``pool_list``) that another agent is working the same pipeline and you
        need to warn it off or ask what it's doing.

        For every peer it does the same two safe things: (1) drops your message
        in the peer's private inbox — the peer reads it itself on its next turn,
        or before its next tool call if it's mid-work — and (2) forks a throwaway
        copy of the peer's context to answer you now with what it's doing. The
        peer's real session is never written to, so it can never be corrupted.
        ``mode`` reports whether the peer is ``live`` (will see your message
        soon) or ``dormant`` (sees it only if reopened before the message
        expires). ``delivered`` means "enqueued to the peer's inbox".

        The forked reader runs with NO tools (``--bare``) — call_agent cannot
        make another agent run tools or change anything. It is communication,
        not remote execution. Call once and read ``their_state``; do not poll in
        a loop (each call spawns a subprocess).

        Args:
            target_session_id: The peer's session id (from ``pool_list``).
            message: What to say/ask. Coordination and status questions.
            session_id: THIS session's own id, shown to you at session start as
                "Your Claude Code session_id is ...". Always pass it — under a
                network MCP transport one server process serves every session,
                so there is no per-caller environment to fall back on.

        Returns:
            JSON: success, mode (live|dormant), delivered, their_state, and note.
        """
        try:
            from hooks.context.agent_pool import call_agent as _call_agent

            caller = resolve_session_id(session_id)
            if not caller:
                # This writes to another agent's inbox attributed to the caller,
                # so an unattributable call must not proceed — same bar as
                # pool_status and channel_acknowledge.
                return json.dumps({"success": False, "error": "no session id resolvable — pass session_id explicitly"})
            # Offloaded to a worker thread: the underlying call spawns a headless
            # claude subprocess and blocks for up to AGENT_POOL_CALL_TIMEOUT (120s
            # default). FastMCP runs sync tools directly on the event loop, and the
            # SSE / streamable-http servers are single-threaded — so left sync this
            # would freeze hooks-utils for every other session for the duration.
            result = await anyio.to_thread.run_sync(
                lambda: _call_agent(target_session_id, message, caller_session_id=caller)
            )
            return json.dumps(result)
        except Exception as e:
            log("MCP call_agent failed", {"error": str(e)})
            return json.dumps({"success": False, "error": str(e)})

    @mcp.tool()
    def pool_list(session_id: str = "") -> str:
        """List the live agents in the fleet pool and what each is working on.

        Read this before ``call_agent`` to find who is active and whether anyone
        is touching the same work you are. Excludes your own session.

        Args:
            session_id: THIS session's own id, so it can be excluded from the
                listing. Shown to you at session start. Pass it under a network
                MCP transport, where the server cannot infer who is calling —
                omit it and you will see yourself in your own peer list.

        Returns:
            JSON with the peer list: session_id, cwd, model, status, summary, last_seen.
        """
        try:
            from hooks.context.agent_pool import list_pool

            caller = resolve_session_id(session_id)
            peers = list_pool(include_self=caller)
            return json.dumps({"success": True, "count": len(peers), "agents": peers})
        except Exception as e:
            log("MCP pool_list failed", {"error": str(e)})
            return json.dumps({"success": False, "error": str(e)})

    @mcp.tool()
    def pool_status(summary: str, session_id: str = "") -> str:
        """Declare what THIS session is currently working on, for the pool.

        A peer scanning ``pool_list`` sees this line. Set it when you start a
        distinctive piece of work (e.g. "rolling out litellm :dev") so others
        can tell whether they'd collide with you. A self-declared summary is
        PINNED — the automatic transcript-derived refresh will not overwrite it —
        so it persists for the duration of your work. Pass an empty string to
        clear the pin and hand the summary back to auto-derive.

        Args:
            summary: Short description of your current task (one line). Empty to clear.
            session_id: THIS session's own id, shown to you at session start.
                Required in practice — a network MCP transport has no per-caller
                environment to fall back on, so without it this call fails
                rather than pinning a summary on the wrong session.

        Returns:
            JSON with success status.
        """
        try:
            from hooks.context.agent_pool import set_summary

            caller = resolve_session_id(session_id)
            if not caller:
                return json.dumps({"success": False, "error": "no session id resolvable — pass session_id explicitly"})
            # A non-empty self-declare pins the summary; empty clears the pin.
            ok = set_summary(caller, summary, sticky=bool(summary.strip()))
            if not ok:
                return json.dumps({"success": False, "error": "this session is not registered in the pool yet"})
            return json.dumps({"success": True, "session_id": caller, "summary": summary})
        except Exception as e:
            log("MCP pool_status failed", {"error": str(e)})
            return json.dumps({"success": False, "error": str(e)})
