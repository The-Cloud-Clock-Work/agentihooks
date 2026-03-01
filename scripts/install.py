#!/usr/bin/env python3
"""Install agentihooks settings, hooks, skills, and agents to ~/.claude.

Usage:
    python scripts/install.py global [--profile default]
        Installs hooks, skills, agents, and CLAUDE.md into ~/.claude.
        --profile selects which profile's CLAUDE.md to link (default: 'default').
        Available profiles are listed from profiles/ (excluding _base).

    python scripts/install.py project <path> [--profile default]
        Installs a profile's .mcp.json into a target project directory.

Re-run `python scripts/install.py global` after any changes to
settings.base.json to keep ~/.claude/settings.json up to date.
The script is idempotent.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AGENTIHOOKS_ROOT = Path(__file__).resolve().parent.parent
PROFILES_DIR = AGENTIHOOKS_ROOT / "profiles"
BASE_SETTINGS = PROFILES_DIR / "_base" / "settings.base.json"

CLAUDE_HOME = Path.home() / ".claude"

# Keys from ~/.claude/settings.json that belong to the user and should be
# preserved when merging (unless the base settings already define them).
PERSONAL_KEYS = {"model", "autoUpdatesChannel", "skipDangerousModePermissionPrompt"}

# Marker written into the managed settings so we can detect re-runs.
MANAGED_BY_KEY = "_managedBy"
MANAGED_BY_VALUE = "agentihooks/scripts/install.py"


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Path substitution: replace /app with the actual agentihooks root
# ---------------------------------------------------------------------------


def substitute_paths(obj: object, src: str = "/app", dst: str = str(AGENTIHOOKS_ROOT)) -> object:
    """Recursively replace *src* with *dst* in all string values of a JSON structure."""
    if isinstance(obj, str):
        return obj.replace(src, dst)
    if isinstance(obj, dict):
        return {k: substitute_paths(v, src, dst) for k, v in obj.items()}
    if isinstance(obj, list):
        return [substitute_paths(item, src, dst) for item in obj]
    return obj


def _available_profiles() -> list[str]:
    """Return profile names (dirs under profiles/ excluding _base)."""
    return sorted(
        d.name for d in PROFILES_DIR.iterdir()
        if d.is_dir() and not d.name.startswith("_")
    )


def _read_profile_description(profile_dir: Path) -> str:
    """Return the description field from profile.yml, or '' if absent."""
    yml = profile_dir / "profile.yml"
    if not yml.exists():
        return ""
    for line in yml.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("description:"):
            value = stripped[len("description:"):].strip().strip('"').strip("'")
            return value
    return ""


def list_profiles() -> None:
    """Print all available profiles and exit."""
    profiles = _available_profiles()
    if not profiles:
        print("No profiles found in profiles/ (only _base exists).")
        return
    print(f"Available profiles ({PROFILES_DIR}):\n")
    for name in profiles:
        desc = _read_profile_description(PROFILES_DIR / name)
        marker = ""
        claude_md = PROFILES_DIR / name / ".claude" / "CLAUDE.md"
        if not claude_md.exists():
            marker = "  [no CLAUDE.md]"
        mcp = PROFILES_DIR / name / ".mcp.json"
        if not mcp.exists():
            marker += "  [no .mcp.json]"
        desc_str = f"  — {desc}" if desc else ""
        print(f"  {name}{desc_str}{marker}")
    print()


# ---------------------------------------------------------------------------
# Global install
# ---------------------------------------------------------------------------


def install_global(args: argparse.Namespace) -> None:
    profile_name: str = args.profile
    print(f"agentihooks root : {AGENTIHOOKS_ROOT}")
    print(f"Target           : {CLAUDE_HOME}")
    print(f"Profile          : {profile_name}")
    print(f"Python           : {sys.executable}")
    print()

    # --- 1. Load and render base settings ---
    if not BASE_SETTINGS.exists():
        print(f"ERROR: {BASE_SETTINGS} not found.", file=sys.stderr)
        sys.exit(1)

    raw_settings = load_json(BASE_SETTINGS)
    rendered: dict = substitute_paths(raw_settings)  # type: ignore[assignment]
    rendered = substitute_paths(rendered, "__PYTHON__", sys.executable)

    # --- 2. Preserve personal keys from existing settings ---
    existing_settings_path = CLAUDE_HOME / "settings.json"
    personal: dict = {}
    if existing_settings_path.exists():
        try:
            existing = load_json(existing_settings_path)
            # Only carry over personal keys if the file is NOT already managed
            # by this script (to avoid re-importing stale copies of what we
            # wrote last time).
            if existing.get(MANAGED_BY_KEY) != MANAGED_BY_VALUE:
                for key in PERSONAL_KEYS:
                    if key in existing:
                        personal[key] = existing[key]
                if personal:
                    print(f"Preserving personal keys from existing settings: {sorted(personal)}")
        except json.JSONDecodeError:
            print("WARNING: existing settings.json is invalid JSON – skipping preservation.")

    # Merge: personal keys fill in gaps; base settings win for everything else.
    merged: dict = deepcopy(personal)
    merged.update(rendered)
    merged[MANAGED_BY_KEY] = MANAGED_BY_VALUE

    # --- 3. Backup existing settings (skip if already managed) ---
    if existing_settings_path.exists():
        existing_raw = load_json(existing_settings_path) if existing_settings_path.exists() else {}
        if existing_raw.get(MANAGED_BY_KEY) != MANAGED_BY_VALUE:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = existing_settings_path.with_suffix(f".json.bak.{timestamp}")
            shutil.copy2(existing_settings_path, backup_path)
            print(f"Backed up existing settings → {backup_path}")

    # --- 4. Write merged settings ---
    CLAUDE_HOME.mkdir(parents=True, exist_ok=True)
    save_json(existing_settings_path, merged)
    print(f"[OK] Wrote {existing_settings_path}")

    # --- 5. Symlink skills (directories only) ---
    skills_src = AGENTIHOOKS_ROOT / ".claude" / "skills"
    skills_dst = CLAUDE_HOME / "skills"
    _symlink_dir_contents(
        skills_src, skills_dst, label="skill",
        filter_fn=lambda p: p.is_dir(),
    )

    # --- 6. Symlink agents (.md files only, excluding README.md) ---
    agents_src = AGENTIHOOKS_ROOT / ".claude" / "agents"
    agents_dst = CLAUDE_HOME / "agents"
    _symlink_dir_contents(
        agents_src, agents_dst, label="agent",
        filter_fn=lambda p: p.suffix == ".md" and p.name != "README.md",
    )

    # --- 7. Symlink CLAUDE.md from the chosen profile ---
    profile_dir = PROFILES_DIR / profile_name
    profile_claude_md = profile_dir / ".claude" / "CLAUDE.md"
    claude_md_dst = CLAUDE_HOME / "CLAUDE.md"
    _install_claude_md(profile_claude_md, claude_md_dst, profile_name)

    # --- Done ---
    print()
    print("Installation complete.")
    print()
    print("Verification steps:")
    print(f"  ls -la {existing_settings_path}")
    print(f"  ls -la {claude_md_dst}")
    print("  Open Claude Code in any project → run /status (hooks should be active)")
    print("  Run /skills to list installed skills")
    print()
    print("To update after settings.base.json changes:")
    print(f"  python scripts/install.py global --profile {profile_name}")


def _symlink_dir_contents(
    src_dir: Path,
    dst_dir: Path,
    *,
    label: str,
    filter_fn: object = None,
) -> None:
    """Symlink filtered children of *src_dir* into *dst_dir*.

    *filter_fn* is called with each source ``Path``; only items for which it
    returns ``True`` are linked.  Stale symlinks (broken or pointing to items
    that no longer pass the filter) are removed automatically.
    """
    if not src_dir.exists():
        print(f"  (no {label}s directory at {src_dir}, skipping)")
        return

    # --- Cleanup: remove stale symlinks in dst_dir ---
    if dst_dir.exists():
        for link in sorted(dst_dir.iterdir()):
            if not link.is_symlink():
                continue
            target = link.resolve()
            # Broken symlink
            if not link.exists():
                link.unlink()
                print(f"  [RM] Removed broken symlink: {link.name}")
                continue
            # Points to our src_dir but fails the current filter
            if target.parent.resolve() == src_dir.resolve() and filter_fn and not filter_fn(target):
                link.unlink()
                print(f"  [RM] Removed stale symlink: {link.name} (no longer a valid {label})")

    children = list(src_dir.iterdir())
    if not children:
        print(f"  (no {label}s found in {src_dir}, skipping)")
        return

    # Apply filter
    if filter_fn:
        children = [c for c in children if filter_fn(c)]

    if not children:
        print(f"  (no valid {label}s found in {src_dir} after filtering, skipping)")
        return

    dst_dir.mkdir(parents=True, exist_ok=True)
    for item in sorted(children):
        if item.name.startswith("."):
            continue
        link = dst_dir / item.name
        if link.is_symlink():
            if link.resolve() == item.resolve():
                print(f"  [--] {label} '{item.name}' already linked → {item}")
            else:
                link.unlink()
                link.symlink_to(item)
                print(f"  [OK] Re-linked {label} '{item.name}' → {item}")
        elif link.exists():
            print(f"  [!!] {label} '{item.name}' exists at {link} and is not a symlink – skipping (remove manually to replace)")
        else:
            link.symlink_to(item)
            print(f"  [OK] Linked {label} '{item.name}' → {item}")


def _install_claude_md(src: Path, dst: Path, profile_name: str) -> None:
    """Symlink *dst* (~/.claude/CLAUDE.md) → *src* (profile CLAUDE.md)."""
    if not src.exists():
        print(f"  [!!] Profile CLAUDE.md not found at {src} — skipping CLAUDE.md linking.")
        print(f"       Available profiles: {_available_profiles()}")
        return

    if dst.is_symlink():
        if dst.resolve() == src.resolve():
            print(f"  [--] CLAUDE.md already linked → {src}")
            return
        # Different target — silently re-link (was probably the old CLAUDE.global.md)
        dst.unlink()
        dst.symlink_to(src)
        print(f"  [OK] Re-linked CLAUDE.md → {src}")
        return

    if dst.exists():
        # Real file exists — ask before replacing
        print(f"\nA CLAUDE.md already exists at {dst}.")
        answer = input(f"Replace with symlink to profiles/{profile_name}/.claude/CLAUDE.md? [y/N] ").strip().lower()
        if answer == "y":
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup = dst.with_suffix(f".md.bak.{timestamp}")
            shutil.copy2(dst, backup)
            print(f"  Backed up existing CLAUDE.md → {backup}")
            dst.unlink()
            dst.symlink_to(src)
            print(f"  [OK] Linked CLAUDE.md → {src}")
        else:
            print("  [--] Skipped CLAUDE.md linking.")
        return

    dst.symlink_to(src)
    print(f"  [OK] Linked CLAUDE.md → {src}")


# ---------------------------------------------------------------------------
# Project install
# ---------------------------------------------------------------------------


def install_project(args: argparse.Namespace) -> None:
    project_path = Path(args.path).expanduser().resolve()
    profile_name = args.profile

    if not project_path.exists():
        print(f"ERROR: Project path does not exist: {project_path}", file=sys.stderr)
        sys.exit(1)
    if not project_path.is_dir():
        print(f"ERROR: Project path is not a directory: {project_path}", file=sys.stderr)
        sys.exit(1)

    profile_dir = PROFILES_DIR / profile_name
    mcp_src = profile_dir / ".mcp.json"
    if not mcp_src.exists():
        print(f"ERROR: Profile '.mcp.json' not found: {mcp_src}", file=sys.stderr)
        print(f"Available profiles: {_available_profiles()}", file=sys.stderr)
        sys.exit(1)

    raw_mcp = load_json(mcp_src)
    rendered_mcp: dict = substitute_paths(raw_mcp)  # type: ignore[assignment]

    mcp_dst = project_path / ".mcp.json"
    if mcp_dst.exists():
        answer = input(f".mcp.json already exists at {mcp_dst}. Overwrite? [y/N] ").strip().lower()
        if answer != "y":
            print("Aborted.")
            sys.exit(0)

    save_json(mcp_dst, rendered_mcp)
    print(f"[OK] Wrote {mcp_dst}")
    print()
    print(f"Next: open Claude Code in '{project_path}' and run /mcp to verify the hooks-utils server.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Install agentihooks settings/hooks/skills/agents to ~/.claude or a project.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--list-profiles",
        action="store_true",
        help="List available profiles and exit",
    )
    sub = parser.add_subparsers(dest="command")

    glob_p = sub.add_parser("global", help="Install hooks + skills + agents into ~/.claude")
    glob_p.add_argument(
        "--profile",
        default="default",
        help="Profile whose CLAUDE.md to link (default: 'default'). "
             f"Available: {', '.join(_available_profiles())}",
    )

    proj = sub.add_parser("project", help="Install a profile's .mcp.json into a target project")
    proj.add_argument("path", help="Target project directory")
    proj.add_argument(
        "--profile",
        default="default",
        help="Profile to use (default: 'default')",
    )

    args = parser.parse_args()

    if args.list_profiles:
        list_profiles()
        return

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "global":
        install_global(args)
    elif args.command == "project":
        install_project(args)


if __name__ == "__main__":
    main()
