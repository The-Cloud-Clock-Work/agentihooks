#!/usr/bin/env python3
"""Build profile artifacts from base settings + per-profile overrides.

Generates .claude/settings.json and .mcp.json for each profile by merging:
  1. profiles/_base/settings.base.json  (shared hooks, permissions, env)
  2. profiles/<name>/settings.overrides.json  (optional per-profile overrides)
  3. profiles/<name>/profile.yml  (mcp_categories → .mcp.json env)

Usage:
    python scripts/build_profiles.py
"""

import json
import sys
from copy import deepcopy
from pathlib import Path

try:
    import yaml
except ImportError:
    # Fallback: minimal YAML parser for the subset we need
    yaml = None

PROFILES_DIR = Path(__file__).resolve().parent.parent / "profiles"
BASE_DIR = PROFILES_DIR / "_base"
BASE_SETTINGS = BASE_DIR / "settings.base.json"


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


def deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base (override wins)."""
    merged = deepcopy(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def build_mcp_json(mcp_categories: str) -> dict:
    """Generate .mcp.json content from mcp_categories string."""
    return {
        "mcpServers": {
            "hooks-utils": {
                "command": "python",
                "args": ["-m", "hooks.mcp"],
                "cwd": "/app",
                "env": {
                    "MCP_CATEGORIES": mcp_categories,
                },
            }
        }
    }


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

    settings_out = profile_dir / ".claude" / "settings.json"
    save_json(settings_out, settings)
    print(f"  [OK] {settings_out.relative_to(PROFILES_DIR.parent)}")

    # --- .mcp.json ---
    mcp_categories = profile_config.get("mcp_categories", "all")
    mcp_json = build_mcp_json(mcp_categories)

    mcp_out = profile_dir / ".mcp.json"
    save_json(mcp_out, mcp_json)
    print(f"  [OK] {mcp_out.relative_to(PROFILES_DIR.parent)}")


def main() -> None:
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
