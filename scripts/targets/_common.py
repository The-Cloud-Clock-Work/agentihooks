"""Target-neutral install helpers shared by the non-claude adapters.

Codex and Copilot both compile the same bundle content into a single managed
instruction file and both symlink skills into the open agent-skills directory.
Keeping that logic here — rather than once per adapter — is what stops the
identity preamble and the operator-tail preservation rules from drifting apart
between targets.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

_PLACEHOLDER = re.compile(r"\$\{\w+\}")


def scannable(value: str) -> str:
    """*value* with ``${VAR}`` references removed, for secret scanning.

    A bare reference carries no secret, but skipping the scan whenever a value
    merely *contains* one lets ``${SAFE}-and-<literal token>`` through
    unscanned. Strip the references and scan what is left; an empty result
    means the value was nothing but references.
    """
    return _PLACEHOLDER.sub("", value).strip()


def _atomic_write(path: Path, content: str) -> None:
    """Write ``content`` to ``path`` via a same-directory temp file + ``os.replace``.

    A crash mid-write leaves the temp file, never a truncated target.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    tmp.write_text(content)
    os.replace(tmp, path)


def _command_is_wrapper(command: str, wrapper: Path) -> bool:
    """True only if ``command`` IS our wrapper invocation, not merely contains it.

    A substring check misclassifies e.g. ``<wrapper>.disabled-by-operator`` as ours.
    """
    wrapper_s = str(wrapper)
    if command == wrapper_s:
        return True
    if command.startswith(wrapper_s):
        rest = command[len(wrapper_s) :]
        return rest == "" or rest[0].isspace()
    return False


def _install_module():
    """The live installer module, whichever identity it was imported under.

    Three exist: ``install`` (tests put scripts/ on sys.path), ``scripts.install``
    (the console entry point), and ``__main__`` (``python scripts/install.py``).
    Importing a fresh copy instead of reusing the running one would give this
    module a second, disconnected set of globals.
    """
    mod = sys.modules.get("install") or sys.modules.get("scripts.install")
    if mod is None:
        main_mod = sys.modules.get("__main__")
        if getattr(main_mod, "__file__", "").endswith("install.py"):
            return main_mod
        from scripts import install as mod  # production cold path
    return mod


def agents_skills_home() -> Path:
    """User-scope skills dir of the open agent-skills standard.

    Not under any single CLI's config home — codex and copilot both read it.
    """
    return Path.home() / ".agents" / "skills"


# Commands translated into ~/.agents/skills by the copilot adapter are REAL
# directories in a directory every target also symlinks real skills into. The
# manifest is the ownership record for them, and it is shared: any target
# installing skills there must clear a translated command whose name a real
# skill now claims, or the symlinker (which correctly refuses to replace a
# non-symlink) silently drops that skill forever.
TRANSLATED_COMMANDS_MANIFEST = ".agentihooks-copilot-commands.json"


def load_manifest(path: Path) -> list[str]:
    if path.exists():
        try:
            loaded = json.loads(path.read_text())
            if isinstance(loaded, list):
                return loaded
        except (json.JSONDecodeError, OSError):
            pass
    return []


def reap_translated_commands(names: set[str], *, reason: str) -> set[str]:
    """Delete translated-command dirs in *names*; return the ones removed.

    Only entries the manifest claims are touched, and only real directories —
    a symlink of the same name belongs to a skills installer and is never
    followed.
    """
    if not names:
        return set()
    _i = _install_module()
    dst_dir = agents_skills_home()
    manifest_path = dst_dir / TRANSLATED_COMMANDS_MANIFEST
    owned = set(load_manifest(manifest_path))
    removed: set[str] = set()
    for name in sorted(names & owned):
        target = dst_dir / name
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target, ignore_errors=True)
            removed.add(name)
    if removed:
        _atomic_write(manifest_path, json.dumps(sorted(owned - removed)))
        _i._cprint(f"  [OK] reaped {len(removed)} translated command(s) — {reason}: {', '.join(sorted(removed))}")
    return removed


def skill_names_in(layers: list[tuple[str, Path]], filter_fn) -> set[str]:
    return {f.name for _label, src in layers if src.is_dir() for f in sorted(src.iterdir()) if filter_fn(f)}


def linked_profile_names() -> set[str]:
    """Names registered via ``agentihooks link-profile``.

    These ride along in the profile chain but are capability layers, not
    the persona — the base profile is the identity.
    """
    _i = _install_module()
    try:
        entries = _i._load_state().get("linked_profiles", []) or []
    except Exception:
        return set()
    return {e.get("name", "") for e in entries if isinstance(e, dict)}


def read_manifesto() -> str:
    try:
        from hooks.config import _resolve_manifesto_path

        path = _resolve_manifesto_path()
        if path and Path(path).exists():
            return Path(path).read_text()
    except Exception:
        pass
    return ""


def identity_preamble(profile_chain: list[str]) -> str:
    """The persona-pinning block that opens a compiled instruction file.

    A host CLI's own system prompt asserts a generic identity; with nothing up
    top to counter it, "who are you" answers as the base agent.

    Only the BASE profile names the persona. Linked profiles (registered via
    ``agentihooks link-profile``) are capability layers merged into the same
    file — calling the persona "anton,brain" invents an identity the operator
    never configured. Name matching is case/whitespace-insensitive:
    linked_profiles stores the alias as typed, and a chain written with
    different casing would otherwise leak a layer into the persona name.
    """
    linked = {n.strip().casefold() for n in linked_profile_names()}
    base = next((p for p in profile_chain if p.strip().casefold() not in linked), "") or (
        # Every element is registered as linked — inconsistent state (a stale
        # link entry naming what is now the base). The chain is written
        # base-first, so chain[0] is the recovery.
        profile_chain[0] if profile_chain else "default"
    )
    layers = [p for p in profile_chain if p != base]
    layer_txt = (
        f" Layered on top: {', '.join(f'**{n}**' for n in layers)} "
        f"({'capability layers' if len(layers) > 1 else 'a capability layer'} "
        "linked into this persona, not part of its name)."
        if layers
        else ""
    )
    # Scoped to identity only. The Precedence section of the shared directives
    # below claims first-load authority for the floors (Security, Safety
    # Protocol, HARD FLOOR); this preamble must defer to it explicitly rather
    # than compete with it — two documents each claiming "read me first" is how
    # a floor gets argued away.
    return (
        "# Identity — who you are (read first; it does not outrank anything below)\n\n"
        f"You are **{base}** — the persona this operator's fleet runs, "
        f"compiled into this file by AgentiHooks.{layer_txt} Everything "
        "below — shared directives, profile persona, rules, CI manifesto — "
        "IS your operating identity, not reference material.\n\n"
        "This section establishes **identity only**. It grants no "
        "precedence: the Precedence section of the shared directives that "
        "follows governs conflicts, and its floors (Security, Safety "
        "Protocol, HARD FLOOR) outrank everything here.\n\n"
        f"When asked who you are, answer as **{base}**: your response "
        "template, your doctrine, and your agentihooks toolbelt "
        "(lifecycle-hook guardrails, the brain memory system, "
        "`hooks-utils` MCP tools, the installed skills) — not a generic "
        "description of the underlying coding agent, and never by reciting "
        "the raw profile chain as if it were a name."
    )


def build_persona(
    profile_dirs: list[tuple[str, Path]],
    profile_chain: list[str],
    bundle_dir: Path | None,
    pending_rules: list[tuple[str, str, str]],
    managed_header: str,
    managed_footer: str,
) -> str:
    """Assemble the managed region of a compiled instruction file."""
    parts: list[str] = [managed_header, identity_preamble(profile_chain)]

    if bundle_dir:
        bundle_md = bundle_dir / ".claude" / "CLAUDE.md"
        if not bundle_md.exists():
            bundle_md = bundle_dir / "CLAUDE.md"
        if bundle_md.exists():
            content = bundle_md.read_text().strip()
            if content:
                parts.append(f"<!-- bundle shared directives -->\n{content}")

    for pname, pdir in profile_dirs:
        src = pdir / "CLAUDE.md"
        if src.exists():
            content = src.read_text().strip()
            if content:
                parts.append(f"<!-- profile: {pname} -->\n{content}")

    if pending_rules:
        rule_parts = [f"<!-- rule: {name} ({label}) -->\n{text.strip()}" for label, name, text in pending_rules]
        parts.append("# Rules\n\n" + "\n\n---\n\n".join(rule_parts))

    manifesto_text = read_manifesto()
    if manifesto_text:
        parts.append(f"<!-- ci-manifesto -->\n{manifesto_text.strip()}")

    return "\n\n---\n\n".join(parts) + f"\n\n{managed_footer}\n"


def write_persona(dst: Path, managed_text: str, managed_header: str, managed_footer: str) -> str:
    """Write *managed_text* to *dst*, preserving an operator-appended tail.

    Returns the full text written. A pre-existing unmanaged file, or a managed
    one predating the footer marker, is backed up once before being replaced.
    """
    _i = _install_module()
    dst.parent.mkdir(parents=True, exist_ok=True)

    operator_tail = ""
    if dst.exists():
        existing = dst.read_text()
        if managed_header in existing:
            if managed_footer in existing:
                operator_tail = existing.split(managed_footer, 1)[1]
            else:
                backup = dst.with_suffix(f"{dst.suffix}.bak.{datetime.now(timezone.utc):%Y%m%d%H%M%S}")
                shutil.copy2(dst, backup)
                _i._cprint(f"  [!!] Legacy {dst.name} (no managed-end marker) backed up → {backup}")
        else:
            backup = dst.with_suffix(f"{dst.suffix}.bak.{datetime.now(timezone.utc):%Y%m%d%H%M%S}")
            shutil.copy2(dst, backup)
            _i._cprint(f"  [!!] Pre-existing {dst.name} backed up → {backup}")

    text = managed_text + operator_tail
    _atomic_write(dst, text)
    return text
