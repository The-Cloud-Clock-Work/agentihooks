"""Backward-compatible entry point. Delegates to hooks.mcp.

Usage:
    python -m hooks.mcp_server   # still works
    python -m hooks.mcp          # preferred new entry point
"""

from hooks.mcp import build_server

mcp = build_server()


def main():
    """Run the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
