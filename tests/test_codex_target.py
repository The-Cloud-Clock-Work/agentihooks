"""Tests for the Codex target adapter (scripts/targets/codex_target.py)."""

import json
import shlex
import subprocess

import install  # binds the installer identity conftest patches; also used directly below
import pytest

from scripts.targets.codex_target import CODEX_HOOK_EVENTS, CodexAdapter, codex_home


@pytest.fixture
def adapter(monkeypatch, tmp_path):
    monkeypatch.delenv("CODEX_HOME", raising=False)
    return CodexAdapter()


class TestConfigToml:
    def test_hand_edits_outside_managed_keys_survive(self, adapter):
        """The highest-value invariant: re-init must never eat operator config."""
        home = codex_home()
        home.mkdir(parents=True, exist_ok=True)
        (home / "config.toml").write_text(
            '# operator comment\nmodel = "gpt-5.6"\n\n[model_providers.litellm]\nname = "Gateway"\n'
        )
        adapter.write_settings({"permissions": {"defaultMode": "auto"}})
        text = (home / "config.toml").read_text()
        assert "# operator comment" in text
        assert 'model = "gpt-5.6"' in text
        assert 'name = "Gateway"' in text
        assert "hooks = true" in text

    def test_bypass_permissions_translation(self, adapter):
        adapter.write_settings({"permissions": {"defaultMode": "bypassPermissions"}})
        text = (codex_home() / "config.toml").read_text()
        assert 'approval_policy = "never"' in text
        assert 'sandbox_mode = "danger-full-access"' in text

    def test_default_translation_does_not_override_operator_choice(self, adapter):
        home = codex_home()
        home.mkdir(parents=True, exist_ok=True)
        (home / "config.toml").write_text('approval_policy = "untrusted"\n')
        adapter.write_settings({})
        assert 'approval_policy = "untrusted"' in (home / "config.toml").read_text()

    def test_bypass_then_default_restores_managed_values(self, adapter):
        """Bypass → default must downgrade sandboxing back, not stick forever."""
        adapter.write_settings({"permissions": {"defaultMode": "bypassPermissions"}})
        text = (codex_home() / "config.toml").read_text()
        assert 'approval_policy = "never"' in text
        adapter.write_settings({"permissions": {"defaultMode": "default"}})
        text = (codex_home() / "config.toml").read_text()
        assert 'approval_policy = "on-request"' in text
        assert 'sandbox_mode = "workspace-write"' in text

    def test_operator_hand_set_approval_policy_survives_reinit(self, adapter, capsys):
        adapter.write_settings({})
        home = codex_home()
        # Operator hand-edits the live key only — not our internal [agentihooks.managed]
        # record, which they don't know exists. count=1 hits the first (top-level)
        # occurrence; the managed-table copy is left as our own record.
        text = (
            (home / "config.toml")
            .read_text()
            .replace('approval_policy = "on-request"', 'approval_policy = "untrusted"', 1)
        )
        (home / "config.toml").write_text(text)
        adapter.write_settings({"permissions": {"defaultMode": "bypassPermissions"}})
        text = (home / "config.toml").read_text()
        assert 'approval_policy = "untrusted"' in text
        assert "hand-set" in capsys.readouterr().out


class TestHooksJson:
    def test_all_events_wired_to_wrapper(self, adapter):
        adapter.write_settings({})
        doc = json.loads((codex_home() / "hooks.json").read_text())
        assert set(doc["hooks"].keys()) == set(CODEX_HOOK_EVENTS)
        for groups in doc["hooks"].values():
            cmd = groups[-1]["hooks"][0]["command"]
            assert cmd.endswith("agentihooks-hook.sh")
        wrapper = (codex_home() / "agentihooks-hook.sh").read_text()
        assert "AGENTIHOOKS_TARGET=codex" in wrapper

    def test_foreign_hooks_preserved(self, adapter):
        home = codex_home()
        home.mkdir(parents=True, exist_ok=True)
        foreign = {"hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": "/usr/bin/audit-hook"}]}]}}
        (home / "hooks.json").write_text(json.dumps(foreign))
        adapter.write_settings({})
        doc = json.loads((home / "hooks.json").read_text())
        pretool_cmds = [h["command"] for g in doc["hooks"]["PreToolUse"] for h in g["hooks"]]
        assert "/usr/bin/audit-hook" in pretool_cmds
        assert any(c.endswith("agentihooks-hook.sh") for c in pretool_cmds)

    def test_rerun_does_not_stack_own_entries(self, adapter):
        adapter.write_settings({})
        adapter.write_settings({})
        doc = json.loads((codex_home() / "hooks.json").read_text())
        own = [
            h for g in doc["hooks"]["SessionStart"] for h in g["hooks"] if h["command"].endswith("agentihooks-hook.sh")
        ]
        assert len(own) == 1

    def test_disabled_foreign_hook_with_wrapper_suffix_preserved(self, adapter):
        """A substring match would misclassify `<wrapper>.disabled-by-operator` as ours."""
        home = codex_home()
        home.mkdir(parents=True, exist_ok=True)
        wrapper_path = home / "agentihooks-hook.sh"
        disabled_cmd = str(wrapper_path) + ".disabled-by-operator"
        foreign = {"hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": disabled_cmd}]}]}}
        (home / "hooks.json").write_text(json.dumps(foreign))
        adapter.write_settings({})
        doc = json.loads((home / "hooks.json").read_text())
        pretool_cmds = [h["command"] for g in doc["hooks"]["PreToolUse"] for h in g["hooks"]]
        assert disabled_cmd in pretool_cmds
        assert str(wrapper_path) in pretool_cmds

    def test_stale_own_entry_under_unwired_event_reaped(self, adapter):
        """Our wrapper under an event we no longer wire (e.g. PostCompact from an
        earlier install) is reaped; a foreign group under that event survives."""
        home = codex_home()
        home.mkdir(parents=True, exist_ok=True)
        wrapper_cmd = str(home / "agentihooks-hook.sh")
        stale = {
            "hooks": {
                "PostCompact": [
                    {"hooks": [{"type": "command", "command": wrapper_cmd}]},
                    {"hooks": [{"type": "command", "command": "/usr/local/bin/operator-hook"}]},
                ]
            }
        }
        (home / "hooks.json").write_text(json.dumps(stale))
        adapter.write_settings({})
        doc = json.loads((home / "hooks.json").read_text())
        postcompact_cmds = [h["command"] for g in doc["hooks"].get("PostCompact", []) for h in g["hooks"]]
        assert wrapper_cmd not in postcompact_cmds
        assert "/usr/local/bin/operator-hook" in postcompact_cmds

    def test_stale_own_only_event_removed_entirely(self, adapter):
        home = codex_home()
        home.mkdir(parents=True, exist_ok=True)
        wrapper_cmd = str(home / "agentihooks-hook.sh")
        stale = {"hooks": {"PostCompact": [{"hooks": [{"type": "command", "command": wrapper_cmd}]}]}}
        (home / "hooks.json").write_text(json.dumps(stale))
        adapter.write_settings({})
        doc = json.loads((home / "hooks.json").read_text())
        assert "PostCompact" not in doc["hooks"]

    def test_wrapper_script_quotes_paths_with_spaces(self, adapter, monkeypatch):
        spaced_root = codex_home().parent / "agenti hooks root"
        monkeypatch.setattr(install, "AGENTIHOOKS_ROOT", spaced_root)
        adapter.write_settings({})
        script = (codex_home() / "agentihooks-hook.sh").read_text()
        assert f"cd {shlex.quote(str(spaced_root))}" in script
        result = subprocess.run(["bash", "-n"], input=script, text=True, capture_output=True)
        assert result.returncode == 0, result.stderr

    def test_config_toml_and_hooks_json_writes_leave_no_temp_files(self, adapter):
        adapter.write_settings({})
        home = codex_home()
        assert list(home.glob(".config.toml.tmp-*")) == []
        assert list(home.glob(".hooks.json.tmp-*")) == []
        assert (home / "config.toml").exists()
        assert (home / "hooks.json").exists()


class TestSharedSkillsDir:
    def test_codex_reaps_a_copilot_translated_command_shadowing_a_real_skill(self, adapter, tmp_path):
        """~/.agents/skills is shared: codex must clear copilot's translated
        command when a real skill claims that name, or the skill never links."""
        from scripts.targets._common import TRANSLATED_COMMANDS_MANIFEST, agents_skills_home
        from scripts.targets.copilot_target import CopilotAdapter

        cmds = tmp_path / "commands"
        cmds.mkdir()
        (cmds / "shared-name.md").write_text("---\ndescription: cmd\n---\n\nold command\n")
        CopilotAdapter().install_features("commands", [("bundle", cmds)], lambda p: p.suffix == ".md")
        shared = agents_skills_home() / "shared-name"
        assert shared.is_dir() and not shared.is_symlink()
        assert TRANSLATED_COMMANDS_MANIFEST in [f.name for f in agents_skills_home().iterdir()]

        skills_src = tmp_path / "skills"
        (skills_src / "shared-name").mkdir(parents=True)
        (skills_src / "shared-name" / "SKILL.md").write_text("REAL SKILL")
        adapter.install_features("skills", [("bundle", skills_src)], lambda p: p.is_dir())

        assert shared.is_symlink()
        assert (shared / "SKILL.md").read_text() == "REAL SKILL"


class TestPersona:
    def test_agents_md_compiles_chain_rules_and_manifesto(self, adapter, tmp_path, monkeypatch):
        prof = tmp_path / "prof-anton"
        prof.mkdir()
        (prof / "CLAUDE.md").write_text("# Anton persona\n")
        rules_src = tmp_path / "rules"
        rules_src.mkdir()
        (rules_src / "01-style.md").write_text("Always be terse.")
        manifesto = tmp_path / "MANIFESTO.md"
        manifesto.write_text("# Doctrine\n")
        monkeypatch.setenv("CI_MANIFESTO_PATH", str(manifesto))

        adapter.install_features("rules", [("rule", rules_src)], lambda p: p.suffix == ".md")
        adapter.install_persona([("anton", prof)], ["anton"], None)

        text = (codex_home() / "AGENTS.md").read_text()
        assert "<!-- profile: anton -->" in text
        assert "# Anton persona" in text
        # Identity preamble pins the persona ahead of everything else, naming
        # the chain, so codex's own system-prompt identity doesn't win.
        assert "# Identity — who you are" in text
        assert "You are **anton**" in text
        assert text.index("# Identity") < text.index("<!-- profile: anton -->")
        assert "<!-- rule: 01-style.md" in text
        assert "Always be terse." in text
        assert "<!-- ci-manifesto -->" in text
        # Size ceiling landed in config.toml with margin above the payload.
        cfg = (codex_home() / "config.toml").read_text()
        assert "project_doc_max_bytes" in cfg

    def test_unmanaged_agents_md_backed_up(self, adapter, tmp_path):
        home = codex_home()
        home.mkdir(parents=True, exist_ok=True)
        (home / "AGENTS.md").write_text("# operator's own file\n")
        prof = tmp_path / "p"
        prof.mkdir()
        (prof / "CLAUDE.md").write_text("persona")
        adapter.install_persona([("p", prof)], ["p"], None)
        backups = (
            list(home.glob("AGENTS.md.bak.*")) + list(home.glob("AGENTS.md.*.bak*")) + list(home.glob("AGENTS*.bak.*"))
        )
        assert backups, "pre-existing unmanaged AGENTS.md must be backed up"

    def test_operator_content_after_footer_survives_rerun(self, adapter, tmp_path):
        prof = tmp_path / "p"
        prof.mkdir()
        (prof / "CLAUDE.md").write_text("persona v1")
        adapter.install_persona([("p", prof)], ["p"], None)
        dst = codex_home() / "AGENTS.md"
        text = dst.read_text()
        assert "<!-- agentihooks:managed-end -->" in text

        dst.write_text(text + "\n## Operator notes\nDo not touch below this line.\n")

        (prof / "CLAUDE.md").write_text("persona v2")
        adapter.install_persona([("p", prof)], ["p"], None)
        text = dst.read_text()
        assert "persona v2" in text
        assert "persona v1" not in text
        assert "## Operator notes" in text
        assert "Do not touch below this line." in text

    def test_legacy_managed_header_without_footer_backed_up_once(self, adapter, tmp_path):
        from scripts.targets.codex_target import _MANAGED_HEADER

        home = codex_home()
        home.mkdir(parents=True, exist_ok=True)
        (home / "AGENTS.md").write_text(_MANAGED_HEADER + "\nold content, predates the footer marker\n")
        prof = tmp_path / "p"
        prof.mkdir()
        (prof / "CLAUDE.md").write_text("persona")
        adapter.install_persona([("p", prof)], ["p"], None)
        backups = (
            list(home.glob("AGENTS.md.bak.*")) + list(home.glob("AGENTS.md.*.bak*")) + list(home.glob("AGENTS*.bak.*"))
        )
        assert backups, "legacy managed AGENTS.md without a footer marker must be backed up once"


class TestPrompts:
    def _layer(self, tmp_path, name, text):
        d = tmp_path / "commands"
        d.mkdir(exist_ok=True)
        (d / name).write_text(text)
        return d

    def test_frontmatter_rewritten(self, adapter, tmp_path):
        src = self._layer(
            tmp_path,
            "deploy.md",
            "---\ndescription: Deploy the stack\nallowed-tools: Bash\n---\n\nDeploy $ARGUMENTS now.\n",
        )
        adapter.install_features("commands", [("command", src)], lambda p: p.suffix == ".md")
        out = (codex_home() / "prompts" / "deploy.md").read_text()
        assert "description: Deploy the stack" in out
        assert "allowed-tools" not in out
        assert "Deploy $ARGUMENTS now." in out

    def test_stale_prompts_removed_on_rerun(self, adapter, tmp_path):
        src = self._layer(tmp_path, "old.md", "body")
        adapter.install_features("commands", [("command", src)], lambda p: p.suffix == ".md")
        assert (codex_home() / "prompts" / "old.md").exists()
        (src / "old.md").unlink()
        (src / "new.md").write_text("body2")
        adapter.install_features("commands", [("command", src)], lambda p: p.suffix == ".md")
        assert not (codex_home() / "prompts" / "old.md").exists()
        assert (codex_home() / "prompts" / "new.md").exists()

    def test_operator_file_not_overwritten_on_first_init(self, adapter, tmp_path):
        """A file the manifest has never claimed is an operator file — it wins."""
        dst_dir = codex_home() / "prompts"
        dst_dir.mkdir(parents=True)
        (dst_dir / "deploy.md").write_text("# operator's own prompt\n")
        src = self._layer(tmp_path, "deploy.md", "body from agentihooks")
        adapter.install_features("commands", [("command", src)], lambda p: p.suffix == ".md")
        assert (dst_dir / "deploy.md").read_text() == "# operator's own prompt\n"

    def test_manifest_owned_prompt_still_overwritten_on_rerun(self, adapter, tmp_path):
        src = self._layer(tmp_path, "deploy.md", "body v1")
        adapter.install_features("commands", [("command", src)], lambda p: p.suffix == ".md")
        assert "body v1" in (codex_home() / "prompts" / "deploy.md").read_text()
        (src / "deploy.md").write_text("body v2")
        adapter.install_features("commands", [("command", src)], lambda p: p.suffix == ".md")
        assert "body v2" in (codex_home() / "prompts" / "deploy.md").read_text()


class TestMcp:
    def test_stdio_and_http_translate_sse_skipped(self, adapter, capsys):
        adapter.register_mcp(
            {
                "hooks-utils": {"command": "/py", "args": ["-m", "hooks.mcp"]},
                "agentibrain": {"type": "sse", "url": "http://localhost:8104/sse"},
                "remote": {"type": "http", "url": "https://x.example/mcp", "headers": {"A": "B"}},
            }
        )
        text = (codex_home() / "config.toml").read_text()
        assert "[mcp_servers.hooks-utils]" in text
        assert "agentibrain" not in text
        assert "[mcp_servers.remote]" in text and "http_headers" in text
        assert "SSE" in capsys.readouterr().out

    def test_bearer_placeholder_maps_to_env_var(self, adapter, capsys):
        adapter.register_mcp(
            {
                "gateway": {
                    "type": "http",
                    "url": "https://g.example/mcp",
                    "headers": {"Authorization": "Bearer ${MCP_GATEWAY_KEY}", "X-Env": "${OTHER}"},
                }
            }
        )
        text = (codex_home() / "config.toml").read_text()
        assert 'bearer_token_env_var = "MCP_GATEWAY_KEY"' in text
        assert "${MCP_GATEWAY_KEY}" not in text, "placeholder must never land literally"
        assert "${OTHER}" not in text
        assert "placeholder" in capsys.readouterr().out

    def test_credential_shaped_header_dropped(self, adapter, capsys):
        # Built by concatenation so the literal secret-shaped string never appears
        # whole anywhere else in this file.
        dummy_key = "AKIA" + "TESTDUMMY0000000"
        adapter.register_mcp(
            {
                "gateway": {
                    "type": "http",
                    "url": "https://g.example/mcp",
                    "headers": {"X-Api-Key": dummy_key},
                }
            }
        )
        text = (codex_home() / "config.toml").read_text()
        assert dummy_key not in text
        out = capsys.readouterr().out
        assert "X-Api-Key" in out
        assert "gateway" in out

    def test_credential_concatenated_onto_a_placeholder_is_dropped(self, adapter, capsys):
        """A value merely CONTAINING ${VAR} must not skip the scan."""
        dummy_key = "AKIA" + "TESTDUMMY0000000"
        adapter.register_mcp({"local": {"command": "/py", "env": {"UPSTREAM_KEY": "${SAFE_VAR}-and-" + dummy_key}}})
        text = (codex_home() / "config.toml").read_text()
        assert dummy_key not in text
        assert "UPSTREAM_KEY" in capsys.readouterr().out

    def test_pure_env_reference_still_survives(self, adapter):
        adapter.register_mcp({"local": {"command": "/py", "env": {"UPSTREAM_KEY": "${MY_TOKEN}"}}})
        assert "${MY_TOKEN}" in (codex_home() / "config.toml").read_text()

    def test_credential_shaped_env_var_dropped(self, adapter, capsys):
        dummy_key = "AKIA" + "TESTDUMMY0000000"
        adapter.register_mcp(
            {
                "local": {
                    "command": "/py",
                    "args": ["-m", "server"],
                    "env": {"UPSTREAM_KEY": dummy_key},
                }
            }
        )
        text = (codex_home() / "config.toml").read_text()
        assert dummy_key not in text
        out = capsys.readouterr().out
        assert "UPSTREAM_KEY" in out
        assert "local" in out

    def test_skills_symlinked_to_agents_dir(self, adapter, tmp_path):
        src = tmp_path / "skills"
        (src / "my-skill").mkdir(parents=True)
        (src / "my-skill" / "SKILL.md").write_text("---\nname: my-skill\n---\nbody")
        adapter.install_features("skills", [("skill", src)], lambda p: p.is_dir())
        from scripts.targets.codex_target import agents_skills_home

        assert (agents_skills_home() / "my-skill").exists()


class TestPersonaIdentityNaming:
    """A linked profile is a capability layer, not part of the persona name."""

    def _profile(self, tmp_path, name):
        d = tmp_path / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "CLAUDE.md").write_text(f"# {name} persona")
        return d

    def test_linked_profile_is_a_layer_not_the_name(self, adapter, tmp_path, monkeypatch):
        monkeypatch.setattr(install, "_load_state", lambda: {"linked_profiles": [{"name": "brain"}]})
        dirs = [("anton", self._profile(tmp_path, "anton")), ("brain", self._profile(tmp_path, "brain"))]
        adapter.install_persona(dirs, ["anton", "brain"], None)
        text = (codex_home() / "AGENTS.md").read_text()
        assert "You are **anton**" in text
        assert "**anton,brain**" not in text
        assert "Layered on top: **brain**" in text

    def test_no_linked_profiles_names_the_base(self, adapter, tmp_path, monkeypatch):
        monkeypatch.setattr(install, "_load_state", lambda: {"linked_profiles": []})
        adapter.install_persona([("anton", self._profile(tmp_path, "anton"))], ["anton"], None)
        text = (codex_home() / "AGENTS.md").read_text()
        assert "You are **anton**" in text
        assert "Layered on top" not in text

    def test_preamble_defers_to_the_precedence_floors(self, adapter, tmp_path, monkeypatch):
        """Two sections each claiming 'read me first' is how a floor gets
        argued away — the identity preamble must yield to Precedence."""
        monkeypatch.setattr(install, "_load_state", lambda: {"linked_profiles": []})
        adapter.install_persona([("anton", self._profile(tmp_path, "anton"))], ["anton"], None)
        text = (codex_home() / "AGENTS.md").read_text()
        assert "It grants no precedence" in text.replace("\n", " ")
        assert "HARD FLOOR) outrank everything here" in text.replace("\n", " ")

    def test_case_mismatch_does_not_leak_a_layer_into_the_name(self, adapter, tmp_path, monkeypatch):
        """linked_profiles stores the alias as typed; a chain written with
        different casing must still treat it as a layer."""
        monkeypatch.setattr(install, "_load_state", lambda: {"linked_profiles": [{"name": "Brain"}]})
        dirs = [("anton", self._profile(tmp_path, "anton")), ("brain", self._profile(tmp_path, "brain"))]
        adapter.install_persona(dirs, ["anton", "brain"], None)
        text = (codex_home() / "AGENTS.md").read_text()
        assert "You are **anton**" in text
        assert "Layered on top: **brain**" in text

    def test_all_linked_chain_recovers_to_the_first_element(self, adapter, tmp_path, monkeypatch):
        """Inconsistent state (every chain entry also registered as linked):
        the chain is written base-first, so chain[0] is the recovery and the
        rest are still described as layers."""
        monkeypatch.setattr(install, "_load_state", lambda: {"linked_profiles": [{"name": "anton"}, {"name": "brain"}]})
        dirs = [("anton", self._profile(tmp_path, "anton")), ("brain", self._profile(tmp_path, "brain"))]
        adapter.install_persona(dirs, ["anton", "brain"], None)
        text = (codex_home() / "AGENTS.md").read_text()
        assert "You are **anton**" in text
        assert "**anton,brain**" not in text

    def test_install_module_accepts_the_main_identity(self, monkeypatch):
        """`python scripts/install.py` registers the installer as __main__."""
        import sys

        from scripts.targets import codex_target

        monkeypatch.delitem(sys.modules, "install", raising=False)
        monkeypatch.delitem(sys.modules, "scripts.install", raising=False)
        fake = type(sys)("__main__")
        fake.__file__ = "/somewhere/scripts/install.py"
        fake.MARKER = "from-main"
        monkeypatch.setitem(sys.modules, "__main__", fake)
        assert codex_target._install_module().MARKER == "from-main"


class TestHooksUtilsTransport:
    """The url form must never hardcode a scheme, and the transport must be
    resolved the same way the claude path resolves it (sonar S5332 flagged the
    hardcoded http:// here after the claude path had already fixed it)."""

    def _entry(self, monkeypatch, **env):
        import install as _i
        from targets.codex_target import CodexAdapter

        for k, v in env.items():
            monkeypatch.setenv(k, v)
        captured: dict = {}
        adapter = CodexAdapter()
        monkeypatch.setattr(adapter, "register_mcp", lambda servers: captured.update(servers))
        monkeypatch.setattr(_i, "_detect_venv", lambda: None)
        adapter.register_hooks_utils("default")
        return captured["hooks-utils"]

    def test_stdio_is_a_command_entry(self, monkeypatch):
        entry = self._entry(monkeypatch, AGENTIHOOKS_MCP_TRANSPORT="stdio")
        assert entry["args"] == ["-m", "hooks.mcp"]
        assert "url" not in entry

    def test_url_mode_defaults_to_http_on_loopback(self, monkeypatch):
        entry = self._entry(monkeypatch, AGENTIHOOKS_MCP_TRANSPORT="streamable-http")
        assert entry["url"] == "http://localhost:8642/mcp"

    def test_url_mode_honours_mcp_scheme(self, monkeypatch):
        """An operator fronting the daemon with TLS needs https — the scheme is
        a knob on both targets, not a literal on one of them."""
        entry = self._entry(
            monkeypatch,
            AGENTIHOOKS_MCP_TRANSPORT="streamable-http",
            MCP_SCHEME="https",
            MCP_HOST="mcp.internal",
            MCP_PORT="9443",
        )
        assert entry["url"] == "https://mcp.internal:9443/mcp"
