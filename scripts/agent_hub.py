#!/usr/bin/env python3
"""Agent Hub — attach an external agent hub to the agentihooks profile system.

Reads agent definitions from an agentihub repo, builds them using
agentihooks' _base template, and outputs ready-to-use profiles.

Usage:
    python scripts/agent_hub.py /path/to/agentihub
    python scripts/agent_hub.py --output /custom/profiles/dir /path/to/agentihub
    AGENTIHUB_PATH=/path/to/agentihub python scripts/agent_hub.py
"""

import argparse
import os
import shutil
import sys
from pathlib import Path

# Ensure scripts/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_profiles import (
    BASE_SETTINGS,
    PROFILES_DIR,
    build_profile,
    load_json,
)


def discover_agents(hub_path: Path) -> list[Path]:
    """Find all agent dirs in agentihub/agents/."""
    agents_dir = hub_path / "agents"
    if not agents_dir.exists():
        print(f"WARNING: No agents/ directory found in {hub_path}", file=sys.stderr)
        return []
    return sorted(
        d
        for d in agents_dir.iterdir()
        if d.is_dir() and (d / "agent.yml").exists()
    )


def attach_agent(agent_dir: Path, output_dir: Path, base_settings: dict) -> Path:
    """Copy agent to output, rename agent.yml -> profile.yml, build."""
    name = agent_dir.name
    target = output_dir / name

    # Copy agent dir to output (preserves .claude/CLAUDE.md, overrides, etc.)
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(agent_dir, target)

    # Rename agent.yml -> profile.yml (agenticore expects profile.yml)
    agent_yml = target / "agent.yml"
    profile_yml = target / "profile.yml"
    if agent_yml.exists() and not profile_yml.exists():
        agent_yml.rename(profile_yml)
    elif agent_yml.exists() and profile_yml.exists():
        # Both exist — remove agent.yml, profile.yml takes precedence
        agent_yml.unlink()

    # Build using agentihooks pipeline (generates settings.json, .mcp.json, symlinks)
    build_profile(target, base_settings)
    return target


def attach_hub(hub_path: str, output_dir: str = "") -> list[str]:
    """Main entry point — attach all agents from hub."""
    hub = Path(hub_path).resolve()
    out = Path(output_dir).resolve() if output_dir else PROFILES_DIR

    if not hub.exists():
        print(f"ERROR: Hub path does not exist: {hub}", file=sys.stderr)
        sys.exit(1)

    if not BASE_SETTINGS.exists():
        print(f"ERROR: Base settings not found: {BASE_SETTINGS}", file=sys.stderr)
        sys.exit(1)

    base_settings = load_json(BASE_SETTINGS)

    agents = discover_agents(hub)
    if not agents:
        print("No agents found.")
        return []

    attached = []
    for agent_dir in agents:
        print(f"Attaching agent: {agent_dir.name}")
        attach_agent(agent_dir, out, base_settings)
        attached.append(agent_dir.name)
        print()

    return attached


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Agent Hub — attach an external agent hub to agentihooks profiles"
    )
    parser.add_argument(
        "hub_path",
        nargs="?",
        default=os.environ.get("AGENTIHUB_PATH", ""),
        help="Path to agentihub repo (or set AGENTIHUB_PATH env var)",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Output directory for built profiles (default: agentihooks profiles/)",
    )
    args = parser.parse_args()

    if not args.hub_path:
        parser.error("hub_path is required (positional arg or AGENTIHUB_PATH env var)")

    attached = attach_hub(args.hub_path, args.output)
    print(f"Attached {len(attached)} agent(s): {', '.join(attached)}")


if __name__ == "__main__":
    main()
