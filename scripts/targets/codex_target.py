"""OpenAI Codex CLI target adapter.

Writes the Codex-shaped install surface (CODEX-COMPAT.md §5):

- ``~/.codex/config.toml`` — managed keys only, via tomlkit round-trip so
  operator hand-edits outside the managed key set survive every re-init
  (the TOML analogue of ``_preserve_personal_keys``).
- ``~/.codex/hooks.json`` + wrapper script — all supported lifecycle events
  routed to ``python -m hooks`` with ``AGENTIHOOKS_TARGET=codex``.
- ``~/.codex/AGENTS.md`` — persona: bundle CLAUDE.md ⊕ profile-chain
  CLAUDE.mds ⊕ compiled rules (codex has no rules dir) ⊕ CI manifesto.
- ``~/.agents/skills/`` — skills symlinks (open agent-skills standard dir).
- ``~/.codex/prompts/`` — commands translated to custom prompts.
- ``[mcp_servers.*]`` — MCP registration (stdio + http url; SSE entries are
  skipped with a warning until the server side exposes streamable HTTP).

Codex facts this file encodes were verified against codex-cli 0.147.0 on
2026-08-10 (CODEX-COMPAT.md §10 evidence table).
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

_MANAGED_HEADER = "<!-- managed-by: agentihooks — regenerate with: agentihooks init --target codex -->"
_MANAGED_FOOTER = "<!-- agentihooks:managed-end -->"


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


# Events supported by both codex hooks.json and our hook_manager dispatch.
CODEX_HOOK_EVENTS = (
    "SessionStart",
    "SessionEnd",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "Stop",
    "SubagentStart",
    "SubagentStop",
    "PreCompact",
    "PermissionRequest",
)


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


def codex_home() -> Path:
    """Resolve CODEX_HOME (first entry when the env var is a comma list)."""
    raw = os.environ.get("CODEX_HOME", "").split(",")[0].strip()
    return Path(raw).expanduser() if raw else Path.home() / ".codex"


def agents_skills_home() -> Path:
    """User-scope skills dir of the open agent-skills standard (not under .codex)."""
    return Path.home() / ".agents" / "skills"


class CodexAdapter:
    name = "codex"

    def __init__(self) -> None:
        # Rules collected by install_features("rules", ...) and compiled into
        # AGENTS.md by install_persona — the features loop runs first.
        self._pending_rules: list[tuple[str, str, str]] = []  # (layer_label, name, text)

    def home(self) -> Path:
        return codex_home()

    # ------------------------------------------------------------------
    # settings: config.toml managed keys + hooks.json + wrapper
    # ------------------------------------------------------------------

    def write_settings(self, rendered: dict) -> Path:
        _i = self._i = _install_module()
        home = self.home()
        home.mkdir(parents=True, exist_ok=True)

        config_path = home / "config.toml"
        doc = self._load_toml(config_path)

        # [features] hooks must be on or the whole hook layer is dead weight.
        features = doc.setdefault("features", {})
        features["hooks"] = True

        # Permission translation (claude settings → codex posture). We record the
        # values we last wrote under [agentihooks.managed] so a later downgrade
        # (bypass → default) can restore them — but only while the operator hasn't
        # hand-edited the key since our last write. A hand-edit differs from our
        # own record and is left alone.
        default_mode = (rendered.get("permissions") or {}).get("defaultMode", "")
        if default_mode == "bypassPermissions":
            wanted = {"approval_policy": "never", "sandbox_mode": "danger-full-access"}
        else:
            wanted = {"approval_policy": "on-request", "sandbox_mode": "workspace-write"}
        managed = doc.setdefault("agentihooks", {}).setdefault("managed", {})
        for key, value in wanted.items():
            current = doc.get(key)
            recorded = managed.get(key)
            if current is None or current == recorded:
                doc[key] = value
                managed[key] = value
            else:
                _i._cprint(
                    f"  [!!] config.toml '{key}' hand-set to {current!r} (managed value would be "
                    f"{value!r}) — leaving operator value in place"
                )

        # Statusline degrade: no command-backed statusline on codex (upstream
        # openai/codex #20140) — configure the closest built-in items. The
        # `ah:` profile line is emitted as a SessionStart banner instead.
        tui = doc.setdefault("tui", {})
        tui.setdefault(
            "status_line",
            [
                "model-with-reasoning",
                "current-dir",
                "context-usage",
                "used-tokens",
                "five-hour-limit",
                "weekly-limit",
            ],
        )

        # Notification degrade: codex has no Notification hook — the fixed
        # `notify` mechanism (agent-turn-complete, JSON as argv[1]) is bridged
        # into the normal Notification handler by the shim module.
        python_bin = str(_i._detect_venv() or sys.executable)
        doc.setdefault("notify", [python_bin, "-m", "hooks.targets.notify_shim"])

        self._dump_toml(config_path, doc)
        _i._cprint(f"[OK] Wrote managed keys into {config_path}")

        self._write_hooks_json(home)
        return config_path

    def _write_hooks_json(self, home: Path) -> None:
        _i = _install_module()
        wrapper = home / "agentihooks-hook.sh"
        python_bin = str(_i._detect_venv() or sys.executable)
        wrapper.write_text(
            "#!/usr/bin/env bash\n"
            "# managed-by: agentihooks — regenerate with: agentihooks init --target codex\n"
            "set -euo pipefail\n"
            f"cd {shlex.quote(str(_i.AGENTIHOOKS_ROOT))}\n"
            f"AGENTIHOOKS_TARGET=codex exec {shlex.quote(python_bin)} -m hooks\n"
        )
        wrapper.chmod(0o755)

        hooks_path = home / "hooks.json"
        entry = {"hooks": [{"type": "command", "command": str(wrapper)}]}
        desired = {e: [entry] for e in CODEX_HOOK_EVENTS}

        existing: dict = {}
        if hooks_path.exists():
            try:
                existing = json.loads(hooks_path.read_text())
            except (json.JSONDecodeError, OSError):
                backup = hooks_path.with_suffix(f".json.bak.{datetime.now(timezone.utc):%Y%m%d%H%M%S}")
                shutil.copy2(hooks_path, backup)
                _i._cprint(f"  [!!] Unparseable hooks.json backed up → {backup}")
                existing = {}

        # Preserve foreign matchers/hooks per event; replace only entries that
        # point at our wrapper (identified by path).
        merged = existing.get("hooks", {}) if isinstance(existing.get("hooks"), dict) else {}
        for event, groups in desired.items():
            prior = merged.get(event, [])
            foreign = [
                g
                for g in prior
                if not any(_command_is_wrapper(h.get("command", ""), wrapper) for h in g.get("hooks", []))
            ]
            merged[event] = foreign + groups
        # Reap our own entries under events we no longer wire (e.g. a stale
        # PostCompact from an earlier install) — foreign groups there survive.
        for event in [e for e in merged if e not in desired]:
            foreign = [
                g
                for g in merged[event]
                if not any(_command_is_wrapper(h.get("command", ""), wrapper) for h in g.get("hooks", []))
            ]
            if foreign:
                merged[event] = foreign
            else:
                del merged[event]
        _atomic_write(hooks_path, json.dumps({"hooks": merged}, indent=2))
        _i._cprint(f"[OK] Wrote {hooks_path} ({len(CODEX_HOOK_EVENTS)} events)")
        _i._cprint(
            "  [!!] Codex trusts hooks by content hash: run /hooks inside codex once to "
            "trust these (or launch automation with --dangerously-bypass-hook-trust). "
            "Until trusted, codex SILENTLY skips them."
        )

    # ------------------------------------------------------------------
    # features: skills / agents / commands / rules
    # ------------------------------------------------------------------

    def install_features(self, subdir: str, layers: list[tuple[str, Path]], filter_fn) -> None:
        _i = _install_module()
        if subdir == "skills":
            dst = agents_skills_home()
            for label, src in layers:
                _i._symlink_dir_contents(src, dst, label=f"codex {label}", filter_fn=filter_fn)
        elif subdir == "commands":
            self._translate_prompts(layers, filter_fn)
        elif subdir == "rules":
            # Codex has no auto-loaded rules dir — compile into AGENTS.md.
            collected: dict[str, tuple[str, str, str]] = {}
            for label, src in layers:
                if not src.is_dir():
                    continue
                for f in sorted(src.iterdir()):
                    if filter_fn(f):
                        try:
                            collected[f.name] = (label, f.name, f.read_text())
                        except OSError:
                            pass
            self._pending_rules = list(collected.values())
            _i._cprint(f"  [OK] {len(self._pending_rules)} rule(s) queued for AGENTS.md compilation")
        elif subdir == "agents":
            _i._cprint("  [--] Codex has no custom-subagent registry — agents skipped (CODEX-COMPAT.md §3 row 16).")

    def _translate_prompts(self, layers: list[tuple[str, Path]], filter_fn) -> None:
        """commands/*.md → ~/.codex/prompts/*.md (flat, frontmatter rewritten).

        Real files, not symlinks — the frontmatter differs from the source.
        Later layers override earlier ones by filename, mirroring the claude
        symlink semantics. Files we wrote previously but that no source layer
        provides anymore are removed (tracked via a manifest sidecar).
        """
        import yaml

        _i = _install_module()
        dst_dir = self.home() / "prompts"
        dst_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = dst_dir / ".agentihooks-manifest.json"
        previous: list[str] = []
        if manifest_path.exists():
            try:
                previous = json.loads(manifest_path.read_text())
            except (json.JSONDecodeError, OSError):
                previous = []

        sources: dict[str, Path] = {}
        for _label, src in layers:
            if not src.is_dir():
                continue
            for f in sorted(src.iterdir()):
                if filter_fn(f):
                    sources[f.name] = f

        written: list[str] = []
        for name, src in sources.items():
            dst_file = dst_dir / name
            if dst_file.exists() and name not in previous:
                _i._cprint(f"  [!!] {dst_file} exists and is not agentihooks-managed — skipping (operator file wins)")
                continue
            try:
                text = src.read_text()
            except OSError:
                continue
            front: dict = {}
            body = text
            if text.startswith("---"):
                parts = text.split("---", 2)
                if len(parts) == 3:
                    try:
                        front = yaml.safe_load(parts[1]) or {}
                    except yaml.YAMLError:
                        front = {}
                    body = parts[2].lstrip("\n")
            out_front: dict = {}
            if isinstance(front, dict):
                if front.get("description"):
                    out_front["description"] = front["description"]
                if front.get("argument-hint") or front.get("argument_hint"):
                    out_front["argument-hint"] = front.get("argument-hint") or front.get("argument_hint")
            out = ""
            if out_front:
                out += "---\n" + yaml.safe_dump(out_front, sort_keys=False).strip() + "\n---\n\n"
            out += body
            dst_file.write_text(out)
            written.append(name)

        for stale in set(previous) - set(written):
            (dst_dir / stale).unlink(missing_ok=True)
        _atomic_write(manifest_path, json.dumps(sorted(written)))
        _i._cprint(f"  [OK] {len(written)} command(s) translated → {dst_dir} (invoke with /prompts:<name>)")

    # ------------------------------------------------------------------
    # persona: AGENTS.md
    # ------------------------------------------------------------------

    @staticmethod
    def _linked_profile_names() -> set[str]:
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

    def install_persona(
        self,
        profile_dirs: list[tuple[str, Path]],
        profile_chain: list[str],
        bundle_dir: Path | None,
    ) -> None:
        _i = _install_module()
        parts: list[str] = [_MANAGED_HEADER]

        # Codex's own system prompt asserts a generic identity; with nothing
        # up top to counter it, "who are you" answers as the base agent. The
        # preamble pins the persona before any shared directives load.
        #
        # Only the BASE profile names the persona. Linked profiles (registered
        # via `agentihooks link-profile`) are capability layers merged into the
        # same file — calling the persona "anton,brain" invents an identity the
        # operator never configured.
        # Name matching is case/whitespace-insensitive: linked_profiles stores
        # the alias as typed, and a chain written with different casing would
        # otherwise leak a layer into the persona name.
        linked = {n.strip().casefold() for n in self._linked_profile_names()}
        base = next((p for p in profile_chain if p.strip().casefold() not in linked), "") or (
            # Every element is registered as linked — inconsistent state (a
            # stale link entry naming what is now the base). The chain is
            # written base-first, so chain[0] is the recovery.
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
        # Scoped to identity only. The Precedence section of the shared
        # directives below claims first-load authority for the floors
        # (Security, Safety Protocol, HARD FLOOR); this preamble must defer to
        # it explicitly rather than compete with it — two documents each
        # claiming "read me first" is how a floor gets argued away.
        parts.append(
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

        if self._pending_rules:
            rule_parts = [
                f"<!-- rule: {name} ({label}) -->\n{text.strip()}" for label, name, text in self._pending_rules
            ]
            parts.append("# Rules\n\n" + "\n\n---\n\n".join(rule_parts))

        manifesto_text = self._read_manifesto()
        if manifesto_text:
            parts.append(f"<!-- ci-manifesto -->\n{manifesto_text.strip()}")

        managed_text = "\n\n---\n\n".join(parts) + f"\n\n{_MANAGED_FOOTER}\n"
        dst = self.home() / "AGENTS.md"
        dst.parent.mkdir(parents=True, exist_ok=True)

        operator_tail = ""
        if dst.exists():
            existing = dst.read_text()
            if _MANAGED_HEADER in existing:
                if _MANAGED_FOOTER in existing:
                    # Preserve whatever the operator appended after our managed region.
                    operator_tail = existing.split(_MANAGED_FOOTER, 1)[1]
                else:
                    # Legacy managed file predating the footer marker — one-time backup.
                    backup = dst.with_suffix(f".md.bak.{datetime.now(timezone.utc):%Y%m%d%H%M%S}")
                    shutil.copy2(dst, backup)
                    _i._cprint(f"  [!!] Legacy AGENTS.md (no managed-end marker) backed up → {backup}")
            else:
                backup = dst.with_suffix(f".md.bak.{datetime.now(timezone.utc):%Y%m%d%H%M%S}")
                shutil.copy2(dst, backup)
                _i._cprint(f"  [!!] Pre-existing AGENTS.md backed up → {backup}")

        text = managed_text + operator_tail
        _atomic_write(dst, text)

        # Codex caps the combined instruction doc (project_doc_max_bytes,
        # default 32 KiB). v0.147.0 loaded a 415 KB global AGENTS.md in full,
        # but the ceiling is raised defensively anyway — a silently truncated
        # persona is the worst failure mode this file can have.
        size = len(text.encode())
        ceiling = max(65536, int(size * 1.25))
        config_path = self.home() / "config.toml"
        doc = self._load_toml(config_path)
        doc["project_doc_max_bytes"] = ceiling
        self._dump_toml(config_path, doc)
        _i._cprint(
            f"[OK] Wrote {dst} ({size} bytes; {len(profile_chain)} profile(s), "
            f"{len(self._pending_rules)} rule(s); project_doc_max_bytes={ceiling})"
        )

    def _read_manifesto(self) -> str:
        try:
            from hooks.config import _resolve_manifesto_path

            path = _resolve_manifesto_path()
            if path and Path(path).exists():
                return Path(path).read_text()
        except Exception:
            pass
        return ""

    # ------------------------------------------------------------------
    # MCP registration
    # ------------------------------------------------------------------

    def register_hooks_utils(self, profile_name: str) -> None:
        _i = _install_module()
        python_bin = str(_i._detect_venv() or sys.executable)
        # Same transport resolver as the claude path — it reads
        # AGENTIHOOKS_MCP_TRANSPORT and ~/.agentihooks/.env, which a bare
        # os.environ["MCP_TRANSPORT"] read does not, so the two targets could
        # otherwise disagree about whether the daemon is even in use.
        transport = _i._resolve_installer_mcp_transport()
        if transport == "stdio":
            entry: dict = {"command": python_bin, "args": ["-m", "hooks.mcp"]}
        else:
            # Reuse the claude-side builder rather than re-deriving the URL: it
            # validates MCP_PORT and honours MCP_SCHEME (the daemon serves
            # plaintext on its loopback bind, but an operator fronting it with
            # TLS or moving it off loopback needs https) and picks the path per
            # transport. Re-deriving it here is how this adapter shipped a
            # hardcoded http:// that the claude path had already fixed.
            # Codex takes the url alone — it infers the type itself.
            entry = {"url": _i._build_mcp_config("")["mcpServers"]["hooks-utils"]["url"]}
        self.register_mcp({"hooks-utils": entry})

    def register_mcp(self, servers: dict) -> None:
        """Merge a layer of MCP servers into [mcp_servers.*] in config.toml.

        Claude ``.mcp.json`` entries translate almost 1:1; SSE transports are
        skipped with a warning — codex has no SSE client (CODEX-COMPAT.md §7).
        """
        _i = _install_module()
        config_path = self.home() / "config.toml"
        doc = self._load_toml(config_path)
        table = doc.setdefault("mcp_servers", {})
        added: list[str] = []
        for name, spec in servers.items():
            spec = dict(spec)
            stype = spec.get("type", "stdio" if spec.get("command") else "http")
            if stype == "sse":
                _i._cprint(
                    f"  [!!] MCP '{name}' uses SSE — codex has no SSE transport; skipped. "
                    "Expose a streamable-HTTP endpoint and re-run init."
                )
                continue
            from hooks.secrets import scan as _scan_secrets

            entry: dict = {}
            if spec.get("command"):
                entry["command"] = spec["command"]
                if spec.get("args"):
                    entry["args"] = list(spec["args"])
                if spec.get("env"):
                    clean_env: dict = {}
                    for ek, ev in dict(spec["env"]).items():
                        ev_s = str(ev)
                        if "${" in ev_s:
                            # Reference, not a literal value — nothing to scan.
                            clean_env[ek] = ev
                            continue
                        hits = _scan_secrets(ev_s, mode="strict")
                        if hits:
                            _i._cprint(
                                f"  [!!] MCP '{name}' env var '{ek}' looks like a credential "
                                f"({', '.join(hits)}) — dropped from config.toml. Export it in "
                                "the shell environment instead of writing it to disk."
                            )
                            continue
                        clean_env[ek] = ev
                    if clean_env:
                        entry["env"] = clean_env
            elif spec.get("url"):
                entry["url"] = spec["url"]
                # Claude Code expands ${VAR} placeholders in header values at
                # connect time; codex sends them LITERALLY (verified: gateway
                # 401 on the raw placeholder). Authorization Bearer ${VAR}
                # maps to codex's native bearer_token_env_var; any other
                # placeholder-bearing header is dropped with a warning.
                import re as _re

                clean_headers: dict = {}
                for hk, hv in dict(spec.get("headers") or {}).items():
                    hv_s = str(hv)
                    bearer = _re.fullmatch(r"Bearer\s+\$\{(\w+)\}", hv_s)
                    if hk.lower() == "authorization" and bearer:
                        entry["bearer_token_env_var"] = bearer.group(1)
                    elif "${" in hv_s:
                        _i._cprint(
                            f"  [!!] MCP '{name}' header '{hk}' uses a ${{VAR}} placeholder — "
                            "codex does not expand these; header dropped. Use a literal value "
                            "or an Authorization Bearer ${VAR} (mapped to bearer_token_env_var)."
                        )
                    else:
                        hits = _scan_secrets(hv_s, mode="strict")
                        if hits:
                            _i._cprint(
                                f"  [!!] MCP '{name}' header '{hk}' looks like a credential "
                                f"({', '.join(hits)}) — dropped from config.toml. Reference it via "
                                "Authorization Bearer ${VAR} (mapped to bearer_token_env_var) "
                                "instead of a literal value."
                            )
                        else:
                            clean_headers[hk] = hv
                if clean_headers:
                    entry["http_headers"] = clean_headers
            else:
                continue
            table[name] = entry
            added.append(name)
        self._dump_toml(config_path, doc)
        if added:
            _i._cprint(f"  [OK] Codex MCP servers: {', '.join(added)}")

    def post_install_reconcile(self, profile_chain: list[str], persisted_profile: str) -> None:
        _i = _install_module()
        _i._cprint(
            "  [--] Codex install complete. First run: open codex and run /hooks to trust "
            "the agentihooks hooks (they are silently skipped until trusted)."
        )

    # ------------------------------------------------------------------
    # doctor
    # ------------------------------------------------------------------

    def doctor(self) -> int:
        """Print codex-install health; return count of failed checks."""
        home = self.home()
        checks: list[tuple[bool, str]] = []

        config_path = home / "config.toml"
        doc = None
        if config_path.exists():
            try:
                import tomlkit

                doc = tomlkit.parse(config_path.read_text())
                checks.append((True, f"config.toml parses ({config_path})"))
            except Exception as exc:
                checks.append((False, f"config.toml unparseable: {exc}"))
        else:
            checks.append((False, "config.toml missing — run: agentihooks init --target codex"))

        if doc is not None:
            checks.append((bool((doc.get("features") or {}).get("hooks")), "[features] hooks = true"))
            servers = list((doc.get("mcp_servers") or {}).keys())
            checks.append((bool(servers), f"mcp_servers registered: {', '.join(servers) or 'NONE'}"))

        hooks_path = home / "hooks.json"
        wrapper = home / "agentihooks-hook.sh"
        if hooks_path.exists():
            try:
                hooks_doc = json.loads(hooks_path.read_text())
                events = list(hooks_doc.get("hooks", {}).keys())
                ours = sum(
                    1
                    for groups in hooks_doc.get("hooks", {}).values()
                    for g in groups
                    for h in g.get("hooks", [])
                    if _command_is_wrapper(h.get("command", ""), wrapper)
                )
                checks.append(
                    (
                        ours >= len(CODEX_HOOK_EVENTS),
                        f"hooks.json wires {ours} agentihooks entries across {len(events)} events",
                    )
                )
            except json.JSONDecodeError as exc:
                checks.append((False, f"hooks.json unparseable: {exc}"))
        else:
            checks.append((False, "hooks.json missing"))
        checks.append((wrapper.exists() and os.access(wrapper, os.X_OK), f"hook wrapper executable ({wrapper})"))

        agents_md = home / "AGENTS.md"
        if agents_md.exists():
            size = len(agents_md.read_bytes())
            ceiling = int((doc or {}).get("project_doc_max_bytes", 32768) or 32768)
            checks.append((size < ceiling, f"AGENTS.md {size}B < project_doc_max_bytes {ceiling}"))
            checks.append((_MANAGED_HEADER in agents_md.read_text(), "AGENTS.md is agentihooks-managed"))
        else:
            checks.append((False, "AGENTS.md missing"))

        skills = agents_skills_home()
        n_skills = len(list(skills.iterdir())) if skills.is_dir() else 0
        checks.append((n_skills > 0, f"{n_skills} skill(s) in {skills}"))

        failed = 0
        for ok, msg in checks:
            print(f"  [{'OK' if ok else '!!'}] {msg}")
            if not ok:
                failed += 1
        print(
            "  [--] Hook trust cannot be verified from outside codex — run /hooks in a "
            "codex session to confirm; untrusted hooks are SILENTLY skipped."
        )
        return failed

    # ------------------------------------------------------------------
    # TOML round-trip (operator hand-edits outside managed keys survive)
    # ------------------------------------------------------------------

    @staticmethod
    def _load_toml(path: Path):
        import tomlkit

        if path.exists():
            try:
                return tomlkit.parse(path.read_text())
            except Exception:
                backup = path.with_suffix(f".toml.bak.{datetime.now(timezone.utc):%Y%m%d%H%M%S}")
                shutil.copy2(path, backup)
                print(f"  [!!] Unparseable config.toml backed up → {backup}")
        import tomlkit

        return tomlkit.document()

    @staticmethod
    def _dump_toml(path: Path, doc) -> None:
        import tomlkit

        _atomic_write(path, tomlkit.dumps(doc))
