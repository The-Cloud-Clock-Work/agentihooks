"""Install-target abstraction — which agent CLI agentihooks installs into.

A *target* is the agent CLI whose config surface ``agentihooks init`` writes:
``claude`` (Claude Code, ``~/.claude``) or ``codex`` (OpenAI Codex CLI,
``~/.codex``). Profile resolution, bundle linking, settings merging and MCP
server-dict assembly are target-agnostic and stay in ``scripts.install``;
everything that touches a target-specific path or schema goes through the
adapter returned by :func:`get_adapter`.

Design doc: ``~/dev/tcc-ecosystem/CODEX-COMPAT.md`` (§4).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Protocol

SUPPORTED_TARGETS = ("claude", "codex")
DEFAULT_TARGET = "claude"


def resolve_target(cli_value: str | None, stored: str, *, interactive_ok: bool = True) -> str:
    """Resolve the install target.

    Precedence: CLI flag > AGENTIHOOKS_TARGET env > state.json > TTY prompt >
    ``claude``. Mirrors the profile-resolution precedence in
    ``cmd_init_unified``. Non-TTY (or *interactive_ok* False) skips the prompt
    so headless installs keep today's behavior unchanged.
    """
    candidate = (cli_value or "").strip()
    if not candidate:
        candidate = os.environ.get("AGENTIHOOKS_TARGET", "").strip()
    if not candidate:
        candidate = (stored or "").strip()
    if not candidate:
        if interactive_ok and sys.stdin.isatty():
            options = "/".join(SUPPORTED_TARGETS)
            candidate = input(f"Target ({options}) [{DEFAULT_TARGET}]: ").strip() or DEFAULT_TARGET
            if candidate.lower() not in SUPPORTED_TARGETS:
                # Interactive typo: warn and fall back rather than killing the
                # whole init. Flag/env values below still fail hard.
                print(f"  [WARN] Unknown target '{candidate}' — using '{DEFAULT_TARGET}'.")
                candidate = DEFAULT_TARGET
        else:
            candidate = DEFAULT_TARGET
    candidate = candidate.lower()
    if candidate not in SUPPORTED_TARGETS:
        print(
            f"ERROR: Unknown target '{candidate}'. Supported: {', '.join(SUPPORTED_TARGETS)}",
            file=sys.stderr,
        )
        sys.exit(1)
    return candidate


class TargetAdapter(Protocol):
    """Target-specific write surface consumed by ``_install_global_inner``."""

    name: str

    def home(self) -> Path:
        """Config root this target reads (``~/.claude`` / ``~/.codex``)."""
        ...

    def write_settings(self, rendered: dict) -> Path:
        """Persist the merged settings for this target; returns the file written."""
        ...

    def install_features(self, subdir: str, layers: list[tuple[str, Path]], filter_fn) -> None:
        """Install one feature kind (skills/agents/commands/rules) from its
        resolved source layers. Claude symlinks all four into ``~/.claude``;
        codex symlinks skills to ``~/.agents/skills``, translates commands to
        ``~/.codex/prompts``, compiles rules into AGENTS.md, and skips agents."""
        ...

    def install_persona(
        self, profile_dirs: list[tuple[str, Path]], profile_chain: list[str], bundle_dir: Path | None
    ) -> None:
        """Assemble and write the persona/system-prompt file for this target."""
        ...

    def register_hooks_utils(self, profile_name: str) -> None:
        """Register agentihooks' own hooks-utils MCP server with the target."""
        ...

    def register_mcp(self, servers: dict) -> None:
        """Merge a layer of MCP server definitions into the target's config."""
        ...

    def post_install_reconcile(self, profile_chain: list[str], persisted_profile: str) -> None:
        """Target-specific end-of-install bookkeeping (ledgers, snapshots)."""
        ...


def get_adapter(target: str) -> TargetAdapter:
    if target == "claude":
        from scripts.targets.claude_target import ClaudeAdapter

        return ClaudeAdapter()
    if target == "codex":
        from scripts.targets.codex_target import CodexAdapter

        return CodexAdapter()
    raise ValueError(f"Unknown target: {target}")
