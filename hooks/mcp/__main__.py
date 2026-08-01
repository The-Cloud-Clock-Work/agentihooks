"""Entry point: python -m hooks.mcp

Transport is stdio unless MCP_TRANSPORT selects sse or streamable-http. The
network transports exist for clients that filter stdio MCP servers out at load
time; everything else keeps the stdio default.
"""

from hooks.mcp import build_server, resolve_transport

mcp = build_server()
mcp.run(transport=resolve_transport())
