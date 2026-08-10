"""Tests for the Codex target adapter (scripts/targets/codex_target.py)."""

import json

import install  # noqa: F401  — binds the installer identity conftest patches
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

    def test_skills_symlinked_to_agents_dir(self, adapter, tmp_path):
        src = tmp_path / "skills"
        (src / "my-skill").mkdir(parents=True)
        (src / "my-skill" / "SKILL.md").write_text("---\nname: my-skill\n---\nbody")
        adapter.install_features("skills", [("skill", src)], lambda p: p.is_dir())
        from scripts.targets.codex_target import agents_skills_home

        assert (agents_skills_home() / "my-skill").exists()
