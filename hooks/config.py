"""Configuration for hooks module."""

import os
from pathlib import Path

# =============================================================================
# LOGGING CONFIGURATION
# =============================================================================

# Agentihooks repo root — two levels up from this file (hooks/config.py)
_REPO_ROOT = Path(__file__).resolve().parent.parent

# Path to hooks log file — always inside the repo's logs/ dir, regardless of
# where the repo is cloned. Directory is created automatically on first write.
LOG_FILE = str(_REPO_ROOT / "logs" / "hooks.log")

# Path to agent transcript log (centralized stream of conversation)
# This is a copy of the Claude Code transcript, streamed in real-time
AGENT_LOG_FILE = os.getenv("AGENT_LOG_FILE", str(_REPO_ROOT / "logs" / "agent.log"))


def _env_bool(key: str, default: str = "false") -> bool:
    """Parse env var as boolean. Accepts: true/false, 1/0, yes/no."""
    val = os.getenv(key, default).lower()
    return val in ("true", "1", "yes")


# Enable/disable hook logging
LOG_ENABLED = _env_bool("CLAUDE_HOOK_LOG_ENABLED", "true")

# Enable/disable logging of hook commands output
LOG_HOOKS_COMMANDS = _env_bool("LOG_HOOKS_COMMANDS", "false")

# Enable/disable automatic transcript logging (logs conversation to hooks.log)
LOG_TRANSCRIPT = _env_bool("LOG_TRANSCRIPT", "true")

# Enable/disable agent log streaming via hooks (copies transcript to AGENT_LOG_FILE)
# Default: false - filesystem-based streaming (sync_transcripts_to_shared.sh) is preferred
# as it provides real-time updates without depending on hook events
STREAM_AGENT_LOG = _env_bool("STREAM_AGENT_LOG", "false")

# Enable/disable ANSI colors in logs (disable for CloudWatch, enable for local dev)
LOG_USE_COLORS = _env_bool("LOG_USE_COLORS", "true")

# Enable/disable automatic memory save on session Stop
# Captures session digest and stores it via MemoryStore
MEMORY_AUTO_SAVE = _env_bool("MEMORY_AUTO_SAVE", "true")
