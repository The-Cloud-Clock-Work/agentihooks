"""Category module registry — single source of truth for MCP tool categories."""

CATEGORY_MODULES = {
    "github": "hooks.mcp.github",
    "confluence": "hooks.mcp.confluence",
    "aws": "hooks.mcp.aws",
    "email": "hooks.mcp.email",
    "messaging": "hooks.mcp.messaging",
    "storage": "hooks.mcp.storage",
    "database": "hooks.mcp.database",
    "compute": "hooks.mcp.compute",
    "observability": "hooks.mcp.observability",
    "smith": "hooks.mcp.smith",
    "agent": "hooks.mcp.agent",
    "utilities": "hooks.mcp.utilities",
}

ALL_CATEGORIES = list(CATEGORY_MODULES.keys())
