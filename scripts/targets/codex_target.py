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
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

_MANAGED_HEADER = "<!-- managed-by: agentihooks — regenerate with: agentihooks init --target codex -->"

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
    mod = sys.modules.get("install") or sys.modules.get("scripts.install")
    if mod is None:
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

        # Permission translation (claude settings → codex posture).
        default_mode = (rendered.get("permissions") or {}).get("defaultMode", "")
        if default_mode == "bypassPermissions":
            doc["approval_policy"] = "never"
            doc["sandbox_mode"] = "danger-full-access"
        else:
            doc.setdefault("approval_policy", "on-request")
            doc.setdefault("sandbox_mode", "workspace-write")

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
            f"cd {_i.AGENTIHOOKS_ROOT}\n"
            f"AGENTIHOOKS_TARGET=codex exec {python_bin} -m hooks\n"
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
            foreign = [g for g in prior if not any(str(wrapper) in h.get("command", "") for h in g.get("hooks", []))]
            merged[event] = foreign + groups
        json.dump({"hooks": merged}, hooks_path.open("w"), indent=2)
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
            (dst_dir / name).write_text(out)
            written.append(name)

        for stale in set(previous) - set(written):
            (dst_dir / stale).unlink(missing_ok=True)
        json.dump(sorted(written), manifest_path.open("w"))
        _i._cprint(f"  [OK] {len(written)} command(s) translated → {dst_dir} (invoke with /prompts:<name>)")

    # ------------------------------------------------------------------
    # persona: AGENTS.md
    # ------------------------------------------------------------------

    def install_persona(
        self,
        profile_dirs: list[tuple[str, Path]],
        profile_chain: list[str],
        bundle_dir: Path | None,
    ) -> None:
        _i = _install_module()
        parts: list[str] = [_MANAGED_HEADER]

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

        text = "\n\n---\n\n".join(parts) + "\n"
        dst = self.home() / "AGENTS.md"
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists() and _MANAGED_HEADER not in dst.read_text():
            backup = dst.with_suffix(f".md.bak.{datetime.now(timezone.utc):%Y%m%d%H%M%S}")
            shutil.copy2(dst, backup)
            _i._cprint(f"  [!!] Pre-existing AGENTS.md backed up → {backup}")
        dst.write_text(text)

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
        transport = os.environ.get("MCP_TRANSPORT", "stdio").strip() or "stdio"
        if transport == "stdio":
            entry: dict = {"command": python_bin, "args": ["-m", "hooks.mcp"]}
        else:
            host = os.environ.get("MCP_HOST", "localhost")
            port = os.environ.get("MCP_PORT", "8642")
            entry = {"url": f"http://{host}:{port}/mcp"}
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
            entry: dict = {}
            if spec.get("command"):
                entry["command"] = spec["command"]
                if spec.get("args"):
                    entry["args"] = list(spec["args"])
                if spec.get("env"):
                    entry["env"] = dict(spec["env"])
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
                    if str(wrapper) in h.get("command", "")
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

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(tomlkit.dumps(doc))
