#!/usr/bin/env python3
"""Install agentihooks settings, hooks, skills, and agents to ~/.claude.

Usage:
    python scripts/install.py global [--profile default]
        Installs hooks, skills, agents, and CLAUDE.md into ~/.claude.
        Also creates /app → <agentihooks root> symlink (needs write access to /).
        --profile selects which profile's CLAUDE.md to link (default: 'default').
        Available profiles are listed from profiles/ (excluding _base).

    python scripts/install.py project <path> [--profile default]
        Installs a profile's .mcp.json into a target project directory.

    python scripts/install.py --mcp /path/to/.mcp.json
        Merge MCP servers from the given file into user scope (~/.claude.json).
        Servers become available in every project without per-repo .mcp.json files.
        The file path is recorded in ~/.agentihooks/state.json for future syncs.

    python scripts/install.py --mcp /path/to/.mcp.json --uninstall
        Remove those MCP servers from user scope (~/.claude.json) and
        remove the file path from ~/.agentihooks/state.json.

    python scripts/install.py --sync
        Re-apply all MCP files previously registered via --mcp.
        Use this after a fresh install to restore all custom MCPs at once.
        `install global` calls --sync automatically when state.json exists.

Re-run `python scripts/install.py global` after any changes to
settings.base.json to keep ~/.claude/settings.json up to date.
The script is idempotent.

The /app symlink is the canonical root used by all hook log paths
(/app/logs/hooks.log, /app/logs/agent.log). If install can't create it
due to permissions, it prints a sudo command to run manually.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections.abc import Callable
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

# Persistent state directory for user-level agentihooks configuration.
AGENTIHOOKS_STATE_DIR = Path.home() / ".agentihooks"
STATE_JSON = AGENTIHOOKS_STATE_DIR / "state.json"

# Repeated path fragment constants (avoids S1192 duplicate-literal warnings)
_CLAUDE_SUBDIR = ".claude"
_CLAUDE_MD_NAME = "CLAUDE.md"
_MCP_JSON_NAME = ".mcp.json"

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
# State helpers (~/.agentihooks/state.json)
# ---------------------------------------------------------------------------


def _load_state() -> dict:
    if STATE_JSON.exists():
        try:
            return load_json(STATE_JSON)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_state(state: dict) -> None:
    AGENTIHOOKS_STATE_DIR.mkdir(parents=True, exist_ok=True)
    save_json(STATE_JSON, state)


def _state_add_mcp(mcp_path: Path) -> None:
    """Record *mcp_path* in state.json so --sync can restore it."""
    state = _load_state()
    paths: list[str] = state.get("mcpFiles", [])
    path_str = str(mcp_path)
    if path_str not in paths:
        paths.append(path_str)
        state["mcpFiles"] = paths
        _save_state(state)


def _state_remove_mcp(mcp_path: Path) -> None:
    """Remove *mcp_path* from state.json."""
    state = _load_state()
    paths: list[str] = state.get("mcpFiles", [])
    path_str = str(mcp_path)
    if path_str in paths:
        paths.remove(path_str)
        state["mcpFiles"] = paths
        _save_state(state)


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
    return sorted(d.name for d in PROFILES_DIR.iterdir() if d.is_dir() and not d.name.startswith("_"))


def _read_profile_description(profile_dir: Path) -> str:
    """Return the description field from profile.yml, or '' if absent."""
    yml = profile_dir / "profile.yml"
    if not yml.exists():
        return ""
    for line in yml.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("description:"):
            value = stripped[len("description:") :].strip().strip('"').strip("'")
            return value
    return ""


def query_active_profile() -> None:
    """Print the currently installed global profile and exit."""
    claude_md = CLAUDE_HOME / _CLAUDE_MD_NAME
    if not claude_md.exists():
        print("not installed")
        return
    if not claude_md.is_symlink():
        print("unmanaged  (CLAUDE.md is not a symlink — installed manually)")
        return
    target = claude_md.resolve()
    try:
        # Expect: <root>/profiles/<name>/.claude/CLAUDE.md
        rel = target.relative_to(PROFILES_DIR)
        profile_name = rel.parts[0]
        print(profile_name)
    except ValueError:
        print(f"unknown  (symlink points outside profiles/: {target})")


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
        claude_md = PROFILES_DIR / name / _CLAUDE_SUBDIR / _CLAUDE_MD_NAME
        if not claude_md.exists():
            marker = f"  [no {_CLAUDE_MD_NAME}]"
        mcp = PROFILES_DIR / name / _MCP_JSON_NAME
        if not mcp.exists():
            marker += f"  [no {_MCP_JSON_NAME}]"
        desc_str = f"  — {desc}" if desc else ""
        print(f"  {name}{desc_str}{marker}")
    print()


# ---------------------------------------------------------------------------
# Settings helpers
# ---------------------------------------------------------------------------


def _preserve_personal_keys(existing_path: Path) -> dict:
    """Return personal keys from an existing unmanaged settings file."""
    personal: dict = {}
    if not existing_path.exists():
        return personal
    try:
        existing = load_json(existing_path)
        if existing.get(MANAGED_BY_KEY) == MANAGED_BY_VALUE:
            return personal  # Already managed — don't re-import
        for key in PERSONAL_KEYS:
            if key in existing:
                personal[key] = existing[key]
        if personal:
            print(f"Preserving personal keys from existing settings: {sorted(personal)}")
    except json.JSONDecodeError:
        print("WARNING: existing settings.json is invalid JSON – skipping preservation.")
    return personal


def _backup_settings(existing_path: Path) -> None:
    """Back up an existing unmanaged settings file (skips if already managed)."""
    if not existing_path.exists():
        return
    existing_raw = load_json(existing_path)
    if existing_raw.get(MANAGED_BY_KEY) == MANAGED_BY_VALUE:
        return
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = existing_path.with_suffix(f".json.bak.{timestamp}")
    shutil.copy2(existing_path, backup_path)
    print(f"Backed up existing settings → {backup_path}")


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
    rendered: dict = substitute_paths(raw_settings)  # NOSONAR — intentional object→dict cast
    rendered = substitute_paths(rendered, "__PYTHON__", sys.executable)  # NOSONAR

    # --- 2. Merge personal keys from existing settings ---
    existing_settings_path = CLAUDE_HOME / "settings.json"
    personal = _preserve_personal_keys(existing_settings_path)
    merged: dict = deepcopy(personal)
    merged.update(rendered)
    merged[MANAGED_BY_KEY] = MANAGED_BY_VALUE

    # --- 3. Backup + write ---
    _backup_settings(existing_settings_path)
    CLAUDE_HOME.mkdir(parents=True, exist_ok=True)
    save_json(existing_settings_path, merged)
    print(f"[OK] Wrote {existing_settings_path}")

    # --- 4. Symlink skills (directories only) ---
    _symlink_dir_contents(
        AGENTIHOOKS_ROOT / _CLAUDE_SUBDIR / "skills",
        CLAUDE_HOME / "skills",
        label="skill",
        filter_fn=lambda p: p.is_dir(),
    )

    # --- 5. Symlink agents (.md files only, excluding README.md) ---
    _symlink_dir_contents(
        AGENTIHOOKS_ROOT / _CLAUDE_SUBDIR / "agents",
        CLAUDE_HOME / "agents",
        label="agent",
        filter_fn=lambda p: p.suffix == ".md" and p.name != "README.md",
    )

    # --- 6. Symlink commands (.md files only, excluding README.md) ---
    _symlink_dir_contents(
        AGENTIHOOKS_ROOT / _CLAUDE_SUBDIR / "commands",
        CLAUDE_HOME / "commands",
        label="command",
        filter_fn=lambda p: p.suffix == ".md" and p.name != "README.md",
    )

    # --- 7. Symlink CLAUDE.md from the chosen profile ---
    profile_claude_md = PROFILES_DIR / profile_name / _CLAUDE_SUBDIR / _CLAUDE_MD_NAME
    claude_md_dst = CLAUDE_HOME / _CLAUDE_MD_NAME
    _install_claude_md(profile_claude_md, claude_md_dst, profile_name)

    # --- 8. Create /app → AGENTIHOOKS_ROOT symlink ---
    _install_app_symlink(AGENTIHOOKS_ROOT)

    # --- 9. Install profile MCP servers to user scope (~/.claude.json) ---
    _install_user_mcp(profile_name)

    # --- 10. Re-apply any custom MCPs tracked in state.json ---
    if STATE_JSON.exists():
        print()
        sync_user_mcp()

    # --- Done ---
    print()
    print("Installation complete.")
    print()
    print("Verification steps:")
    print(f"  ls -la {existing_settings_path}")
    print(f"  ls -la {claude_md_dst}")
    print("  ls -la /app  →  should point to agentihooks root")
    print("  Open Claude Code in any project → run /status (hooks should be active)")
    print("  Run /skills to list installed skills")
    print()
    print("To update after settings.base.json changes:")
    print(f"  python scripts/install.py global --profile {profile_name}")


# ---------------------------------------------------------------------------
# User-scope MCP install (~/.claude.json)
# ---------------------------------------------------------------------------

_CLAUDE_JSON = Path.home() / ".claude.json"


def _merge_mcp_to_user_scope(servers: dict) -> None:
    """Merge *servers* into the top-level mcpServers of ~/.claude.json."""
    existing: dict = load_json(_CLAUDE_JSON) if _CLAUDE_JSON.exists() else {}
    existing_servers: dict = existing.get("mcpServers", {})
    added, updated = [], []
    for name, config in servers.items():
        if name in existing_servers:
            if existing_servers[name] != config:
                updated.append(name)
        else:
            added.append(name)
        existing_servers[name] = config
    existing["mcpServers"] = existing_servers
    save_json(_CLAUDE_JSON, existing)
    if added:
        print(f"  [OK] Added user-scope MCP servers  : {', '.join(added)}")
    if updated:
        print(f"  [OK] Updated user-scope MCP servers: {', '.join(updated)}")
    if not added and not updated:
        print(f"  [--] User-scope MCP servers unchanged: {', '.join(servers.keys())}")


def _remove_mcp_from_user_scope(servers: dict) -> None:
    """Remove *servers* keys from the top-level mcpServers of ~/.claude.json."""
    if not _CLAUDE_JSON.exists():
        print("  [--] ~/.claude.json does not exist — nothing to remove.")
        return
    existing: dict = load_json(_CLAUDE_JSON)
    existing_servers: dict = existing.get("mcpServers", {})
    removed, missing = [], []
    for name in servers:
        if name in existing_servers:
            del existing_servers[name]
            removed.append(name)
        else:
            missing.append(name)
    existing["mcpServers"] = existing_servers
    save_json(_CLAUDE_JSON, existing)
    if removed:
        print(f"  [OK] Removed user-scope MCP servers: {', '.join(removed)}")
    if missing:
        print(f"  [--] Not found (already removed?)  : {', '.join(missing)}")


def _install_user_mcp(profile_name: str) -> None:
    """Merge profile's .mcp.json servers into ~/.claude.json top-level mcpServers.

    This installs MCP servers at user scope so they are available in every
    project without needing a per-project .mcp.json.
    """
    mcp_src = PROFILES_DIR / profile_name / _MCP_JSON_NAME
    if not mcp_src.exists():
        print(f"  (no {_MCP_JSON_NAME} in profile '{profile_name}', skipping user-scope MCP)")
        return

    raw_mcp = load_json(mcp_src)
    rendered_mcp: dict = substitute_paths(raw_mcp)  # NOSONAR
    profile_servers: dict = rendered_mcp.get("mcpServers", {})

    if not profile_servers:
        print(f"  (profile '{profile_name}' .mcp.json has no mcpServers, skipping)")
        return

    _merge_mcp_to_user_scope(profile_servers)


def manage_user_mcp(mcp_path: Path, *, uninstall: bool = False) -> None:
    """Install or uninstall MCP servers from an external file into user scope.

    Reads *mcp_path* (must contain a ``mcpServers`` dict) and either merges
    all servers into ``~/.claude.json`` (install) or removes them (uninstall).
    No path substitution is applied — the file is used as-is.
    """
    if not mcp_path.exists():
        print(f"ERROR: MCP file not found: {mcp_path}", file=sys.stderr)
        sys.exit(1)
    try:
        raw = load_json(mcp_path)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"ERROR: Cannot read {mcp_path}: {exc}", file=sys.stderr)
        sys.exit(1)

    servers: dict = raw.get("mcpServers", {})
    if not servers:
        print(f"  [--] No mcpServers found in {mcp_path} — nothing to do.")
        return

    action = "Uninstalling" if uninstall else "Installing"
    print(f"{action} MCP servers from {mcp_path}:")
    print(f"  Servers: {', '.join(servers.keys())}")
    print()
    if uninstall:
        _remove_mcp_from_user_scope(servers)
        _state_remove_mcp(mcp_path)
    else:
        _merge_mcp_to_user_scope(servers)
        _state_add_mcp(mcp_path)


def sync_user_mcp() -> None:
    """Re-apply all MCP files tracked in ~/.agentihooks/state.json.

    Skips paths that no longer exist (with a warning) so a missing
    repo doesn't abort the whole sync.
    """
    state = _load_state()
    paths: list[str] = state.get("mcpFiles", [])
    if not paths:
        print(f"  [--] No MCP files tracked in {STATE_JSON} — nothing to sync.")
        return

    print(f"Syncing {len(paths)} tracked MCP file(s) from {STATE_JSON}:")
    for path_str in paths:
        p = Path(path_str)
        if not p.exists():
            print(f"  [!!] Skipping missing file: {path_str}")
            continue
        try:
            raw = load_json(p)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"  [!!] Cannot read {path_str}: {exc}")
            continue
        servers: dict = raw.get("mcpServers", {})
        if not servers:
            print(f"  [--] No mcpServers in {path_str} — skipping.")
            continue
        print(f"  From {p.name}: {', '.join(servers.keys())}")
        _merge_mcp_to_user_scope(servers)


# ---------------------------------------------------------------------------
# Symlink helpers
# ---------------------------------------------------------------------------


def _cleanup_stale_links(dst_dir: Path, src_dir: Path, filter_fn: Callable[[Path], bool] | None) -> None:
    """Remove broken symlinks and symlinks that no longer pass *filter_fn*."""
    if not dst_dir.exists():
        return
    for link in sorted(dst_dir.iterdir()):
        if not link.is_symlink():
            continue
        target = link.resolve()
        if not link.exists():
            link.unlink()
            print(f"  [RM] Removed broken symlink: {link.name}")
        elif target.parent.resolve() == src_dir.resolve() and filter_fn and not filter_fn(target):
            link.unlink()
            print(f"  [RM] Removed stale symlink: {link.name}")


def _link_item(item: Path, link: Path, label: str) -> None:
    """Create or update a single symlink *link* → *item*."""
    if link.is_symlink():
        if link.resolve() == item.resolve():
            print(f"  [--] {label} '{item.name}' already linked → {item}")
        else:
            link.unlink()
            link.symlink_to(item)
            print(f"  [OK] Re-linked {label} '{item.name}' → {item}")
    elif link.exists():
        print(f"  [!!] {label} '{item.name}' exists at {link} and is not a symlink – skipping (remove manually)")
    else:
        link.symlink_to(item)
        print(f"  [OK] Linked {label} '{item.name}' → {item}")


def _symlink_dir_contents(
    src_dir: Path,
    dst_dir: Path,
    *,
    label: str,
    filter_fn: Callable[[Path], bool] | None = None,
) -> None:
    """Symlink filtered children of *src_dir* into *dst_dir*.

    Stale symlinks (broken or pointing to items that no longer pass the filter)
    are removed automatically before new links are created.
    """
    if not src_dir.exists():
        print(f"  (no {label}s directory at {src_dir}, skipping)")
        return

    _cleanup_stale_links(dst_dir, src_dir, filter_fn)

    children = [c for c in src_dir.iterdir() if not filter_fn or filter_fn(c)]
    if not children:
        print(f"  (no valid {label}s found in {src_dir} after filtering, skipping)")
        return

    dst_dir.mkdir(parents=True, exist_ok=True)
    for item in sorted(children):
        if not item.name.startswith("."):
            _link_item(item, dst_dir / item.name, label)


def _install_app_symlink(target: Path) -> None:
    """Create /app → *target* symlink so hooks can always use /app as canonical root.

    Requires write permission to /. If permission is denied, prints the sudo
    command the user can run manually.
    """
    app = Path("/app")
    if app.is_symlink():
        if app.resolve() == target.resolve():
            print(f"  [--] /app already linked → {target}")
        else:
            try:
                app.unlink()
                app.symlink_to(target)
                print(f"  [OK] Re-linked /app → {target}")
            except PermissionError:
                print("  [!!] Cannot update /app (permission denied). Run manually:")
                print(f"       sudo ln -sfn {target} /app")
        return

    if app.exists():
        print("  [!!] /app exists but is not a symlink — skipping (remove manually).")
        return

    try:
        app.symlink_to(target)
        print(f"  [OK] Linked /app → {target}")
    except PermissionError:
        print("  [!!] Cannot create /app (permission denied). Run manually:")
        print(f"       sudo ln -sfn {target} /app")


def _install_claude_md(src: Path, dst: Path, profile_name: str) -> None:
    """Symlink *dst* (~/.claude/CLAUDE.md) → *src* (profile CLAUDE.md)."""
    if not src.exists():
        print(f"  [!!] Profile {_CLAUDE_MD_NAME} not found at {src} — skipping.")
        print(f"       Available profiles: {_available_profiles()}")
        return

    if dst.is_symlink():
        if dst.resolve() == src.resolve():
            print(f"  [--] {_CLAUDE_MD_NAME} already linked → {src}")
        else:
            dst.unlink()
            dst.symlink_to(src)
            print(f"  [OK] Re-linked {_CLAUDE_MD_NAME} → {src}")
        return

    if dst.exists():
        print(f"\nA {_CLAUDE_MD_NAME} already exists at {dst}.")
        answer = (
            input(f"Replace with symlink to profiles/{profile_name}/{_CLAUDE_SUBDIR}/{_CLAUDE_MD_NAME}? [y/N] ")
            .strip()
            .lower()
        )
        if answer == "y":
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup = dst.with_suffix(f".md.bak.{timestamp}")
            shutil.copy2(dst, backup)
            print(f"  Backed up existing {_CLAUDE_MD_NAME} → {backup}")
            dst.unlink()
            dst.symlink_to(src)
            print(f"  [OK] Linked {_CLAUDE_MD_NAME} → {src}")
        else:
            print(f"  [--] Skipped {_CLAUDE_MD_NAME} linking.")
        return

    dst.symlink_to(src)
    print(f"  [OK] Linked {_CLAUDE_MD_NAME} → {src}")


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

    mcp_src = PROFILES_DIR / profile_name / _MCP_JSON_NAME
    if not mcp_src.exists():
        print(f"ERROR: Profile '{_MCP_JSON_NAME}' not found: {mcp_src}", file=sys.stderr)
        print(f"Available profiles: {_available_profiles()}", file=sys.stderr)
        sys.exit(1)

    raw_mcp = load_json(mcp_src)
    rendered_mcp: dict = substitute_paths(raw_mcp)  # NOSONAR — intentional object→dict cast

    mcp_dst = project_path / _MCP_JSON_NAME
    if mcp_dst.exists():
        answer = input(f"{_MCP_JSON_NAME} already exists at {mcp_dst}. Overwrite? [y/N] ").strip().lower()
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
    parser.add_argument(
        "--query",
        action="store_true",
        help="Print the currently active global profile name and exit",
    )
    parser.add_argument(
        "--mcp",
        metavar="PATH",
        help="Path to a .mcp.json file to install into (or remove from) user scope",
    )
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="Remove MCP servers listed in --mcp from user scope (requires --mcp)",
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help=f"Re-apply all MCP files tracked in {STATE_JSON}",
    )
    sub = parser.add_subparsers(dest="command")

    glob_p = sub.add_parser("global", help="Install hooks + skills + agents into ~/.claude")
    glob_p.add_argument(
        "--profile",
        default="default",
        help=f"Profile whose CLAUDE.md to link (default: 'default'). Available: {', '.join(_available_profiles())}",
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

    if args.query:
        query_active_profile()
        return

    if args.mcp:
        manage_user_mcp(Path(args.mcp).expanduser().resolve(), uninstall=args.uninstall)
        return

    if args.uninstall and not args.mcp:
        parser.error("--uninstall requires --mcp <path>")

    if args.sync:
        sync_user_mcp()
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
