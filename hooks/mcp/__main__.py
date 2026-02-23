"""Entry point: python -m hooks.mcp"""

from hooks.mcp import build_server

mcp = build_server()
mcp.run()
