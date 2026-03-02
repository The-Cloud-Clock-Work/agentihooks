#!/usr/bin/env python3
"""Build profile artifacts from base settings + per-profile overrides.

Generates .claude/settings.json and .mcp.json for each profile by merging:
  1. profiles/_base/settings.base.json  (shared hooks, permissions, env)
  2. profiles/<name>/settings.overrides.json  (optional per-profile overrides)
  3. profiles/<name>/profile.yml  (mcp_categories → .mcp.json env)

Placeholders resolved at build time:
  __PYTHON__   →  sys.executable  (actual Python binary in current env)
  /app         →  AGENTIHOOKS_HOME (install dir passed by agenticore, or auto-detected)

Also symlinks skills/, agents/, commands/ from the agentihooks root .claude/
into each profile's .claude/ so CLAUDE_CONFIG_DIR finds them automatically.

Usage:
    python scripts/build_profiles.py
    AGENTIHOOKS_HOME=/shared/agentihooks python scripts/build_profiles.py
"""

import json
import os
import sys
from copy import deepcopy
from pathlib import Path

try:
    import yaml
except ImportError:
    # Fallback: minimal YAML parser for the subset we need
    yaml = None

# Resolve install directory. Agenticore passes AGENTIHOOKS_HOME when invoking
# this script so generated paths are correct for the actual install location.
# Fallback: derive from this file's location (works when run directly from repo).
AGENTIHOOKS_HOME = os.environ.get(
    "AGENTIHOOKS_HOME",
    str(Path(__file__).resolve().parent.parent),
)
AGENTIHOOKS_ROOT = Path(AGENTIHOOKS_HOME)

PROFILES_DIR = AGENTIHOOKS_ROOT / "profiles"
BASE_DIR = PROFILES_DIR / "_base"
BASE_SETTINGS = BASE_DIR / "settings.base.json"

PYTHON_BIN = sys.executable


# ---------------------------------------------------------------------------
# JSON / YAML helpers
# ---------------------------------------------------------------------------


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def load_yaml(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if yaml:
        return yaml.safe_load(text) or {}
    # Minimal fallback for simple key: value YAML
    result = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if value:
                result[key] = value
    return result


# ---------------------------------------------------------------------------
# Placeholder substitution
# ---------------------------------------------------------------------------


def substitute_paths(obj: object, src: str = "/app", dst: str = AGENTIHOOKS_HOME) -> object:
    """Recursively replace *src* with *dst* in all string values of a JSON structure."""
    if isinstance(obj, str):
        return obj.replace(src, dst)
    if isinstance(obj, dict):
        return {k: substitute_paths(v, src, dst) for k, v in obj.items()}
    if isinstance(obj, list):
        return [substitute_paths(item, src, dst) for item in obj]
    return obj


# ---------------------------------------------------------------------------
# Merge helper
# ---------------------------------------------------------------------------


def deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base (override wins)."""
    merged = deepcopy(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


# ---------------------------------------------------------------------------
# MCP JSON generator
# ---------------------------------------------------------------------------


def build_mcp_json(mcp_categories: str) -> dict:
    """Generate .mcp.json content from mcp_categories string."""
    return {
        "mcpServers": {
            "hooks-utils": {
                "command": PYTHON_BIN,
                "args": ["-m", "hooks.mcp"],
                "cwd": AGENTIHOOKS_HOME,
                "env": {
                    "MCP_CATEGORIES": mcp_categories,
                },
            }
        }
    }


# ---------------------------------------------------------------------------
# Skills / agents / commands symlinks
# ---------------------------------------------------------------------------


def _link_shared_claude_dirs(profile_dir: Path) -> None:
    """Symlink skills/, agents/, commands/ from the agentihooks root .claude/
    into the profile's .claude/ so CLAUDE_CONFIG_DIR points at the profile dir
    and Claude still finds all the shared content.

    Uses relative symlinks so they survive moving the install dir.
    Skips directories that are empty (only contain README.md or nothing).
    """
    root_claude = AGENTIHOOKS_ROOT / ".claude"
    profile_claude = profile_dir / ".claude"
    profile_claude.mkdir(parents=True, exist_ok=True)

    for subdir in ("skills", "agents", "commands"):
        src = root_claude / subdir
        dst = profile_claude / subdir

        # Only link if the source has real content beyond README.md
        if src.exists():
            real_files = [f for f in src.iterdir() if f.name != "README.md"]
            if not real_files:
                continue  # nothing useful to link

        if not src.exists():
            continue

        # Remove stale link / existing dir before re-linking
        if dst.is_symlink():
            if dst.resolve() == src.resolve():
                continue  # already correct
            dst.unlink()
        elif dst.exists():
            continue  # user-managed content, don't touch

        # Relative path: ../../.claude/skills (from profile_dir/.claude/skills)
        rel = Path(os.path.relpath(src, profile_claude))
        dst.symlink_to(rel)
        print(f"  [LN] {dst.relative_to(PROFILES_DIR.parent)} → {rel}")


# ---------------------------------------------------------------------------
# Per-profile build
# ---------------------------------------------------------------------------


def build_profile(profile_dir: Path, base_settings: dict) -> None:
    """Build artifacts for a single profile."""
    profile_yml = profile_dir / "profile.yml"

    if not profile_yml.exists():
        return

    profile_config = load_yaml(profile_yml)

    # --- settings.json ---
    overrides_path = profile_dir / "settings.overrides.json"
    if overrides_path.exists():
        overrides = load_json(overrides_path)
        settings = deep_merge(base_settings, overrides)
    else:
        settings = deepcopy(base_settings)

    # Resolve placeholders: /app → AGENTIHOOKS_HOME, __PYTHON__ → sys.executable
    settings = substitute_paths(settings)
    settings = substitute_paths(settings, "__PYTHON__", PYTHON_BIN)

    settings_out = profile_dir / ".claude" / "settings.json"
    save_json(settings_out, settings)
    print(f"  [OK] {settings_out.relative_to(PROFILES_DIR.parent)}")

    # --- .mcp.json ---
    mcp_categories = profile_config.get("mcp_categories", "all")
    mcp_json = build_mcp_json(mcp_categories)

    mcp_out = profile_dir / ".mcp.json"
    save_json(mcp_out, mcp_json)
    print(f"  [OK] {mcp_out.relative_to(PROFILES_DIR.parent)}")

    # --- shared skills / agents / commands symlinks ---
    _link_shared_claude_dirs(profile_dir)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    print(f"AGENTIHOOKS_HOME : {AGENTIHOOKS_HOME}")
    print(f"Python           : {PYTHON_BIN}")
    print()

    if not BASE_SETTINGS.exists():
        print(f"ERROR: Base settings not found: {BASE_SETTINGS}", file=sys.stderr)
        sys.exit(1)

    base_settings = load_json(BASE_SETTINGS)
    print(f"Base settings loaded: {BASE_SETTINGS.relative_to(PROFILES_DIR.parent)}")
    print()

    profile_dirs = sorted(d for d in PROFILES_DIR.iterdir() if d.is_dir() and not d.name.startswith("_"))

    if not profile_dirs:
        print("No profiles found.")
        return

    for profile_dir in profile_dirs:
        profile_yml = profile_dir / "profile.yml"
        if not profile_yml.exists():
            continue
        print(f"Building profile: {profile_dir.name}")
        build_profile(profile_dir, base_settings)
        print()

    print("Done.")


if __name__ == "__main__":
    main()
