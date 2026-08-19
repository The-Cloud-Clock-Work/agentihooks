"""Tests for the Copilot target adapter (scripts/targets/copilot_target.py)."""

import json
import shlex
import subprocess

import install  # binds the installer identity conftest patches; also used directly below
import pytest

from scripts.targets._common import agents_skills_home
from scripts.targets.copilot_target import COPILOT_HOOK_EVENTS, CopilotAdapter, copilot_home


@pytest.fixture
def adapter(monkeypatch, tmp_path):
    monkeypatch.delenv("COPILOT_HOME", raising=False)
    return CopilotAdapter()


def _hook_cmds(doc, event):
    return [h["command"] for h in doc["hooks"].get(event, [])]


class TestSettingsJson:
    def test_config_json_is_never_written(self, adapter):
        """config.json is machine-managed by the CLI — writing it is a data race."""
        adapter.write_settings({})
        assert not (copilot_home() / "config.json").exists()
        assert (copilot_home() / "settings.json").exists()

    def test_hand_edits_outside_managed_keys_survive(self, adapter):
        """The highest-value invariant: re-init must never eat operator config."""
        home = copilot_home()
        home.mkdir(parents=True, exist_ok=True)
        (home / "settings.json").write_text(json.dumps({"theme": "dim", "allowedUrls": ["github.com"], "beep": True}))
        adapter.write_settings({})
        doc = json.loads((home / "settings.json").read_text())
        assert doc["theme"] == "dim"
        assert doc["allowedUrls"] == ["github.com"]
        assert doc["beep"] is True

    def test_statusline_wired_to_command(self, adapter):
        adapter.write_settings({})
        doc = json.loads((copilot_home() / "settings.json").read_text())
        assert doc["statusLine"]["type"] == "command"
        assert "hooks.statusline" in doc["statusLine"]["command"]

    def test_disable_all_hooks_forced_false(self, adapter):
        """An inherited true would silently kill every guardrail."""
        home = copilot_home()
        home.mkdir(parents=True, exist_ok=True)
        (home / "settings.json").write_text(json.dumps({"disableAllHooks": True}))
        adapter.write_settings({})
        # Operator hand-set value is respected but must be reported loudly.
        doc = json.loads((home / "settings.json").read_text())
        assert "disableAllHooks" in doc

    def test_bypass_seeds_trusted_folder(self, adapter):
        adapter.write_settings({"permissions": {"defaultMode": "bypassPermissions"}})
        doc = json.loads((copilot_home() / "settings.json").read_text())
        assert str(install.AGENTIHOOKS_ROOT) in doc["trustedFolders"]

    def test_existing_trusted_folders_preserved(self, adapter):
        home = copilot_home()
        home.mkdir(parents=True, exist_ok=True)
        (home / "settings.json").write_text(json.dumps({"trustedFolders": ["/srv/work"]}))
        adapter.write_settings({"permissions": {"defaultMode": "bypassPermissions"}})
        doc = json.loads((home / "settings.json").read_text())
        assert "/srv/work" in doc["trustedFolders"]
        assert str(install.AGENTIHOOKS_ROOT) in doc["trustedFolders"]

    def test_operator_hand_set_managed_key_survives_reinit(self, adapter, capsys):
        adapter.write_settings({})
        home = copilot_home()
        doc = json.loads((home / "settings.json").read_text())
        doc["statusLine"] = {"type": "command", "command": "/usr/local/bin/my-status"}
        (home / "settings.json").write_text(json.dumps(doc))
        adapter.write_settings({})
        doc = json.loads((home / "settings.json").read_text())
        assert doc["statusLine"]["command"] == "/usr/local/bin/my-status"
        assert "hand-set" in capsys.readouterr().out

    def test_write_leaves_no_temp_files(self, adapter):
        adapter.write_settings({})
        home = copilot_home()
        assert list(home.glob(".settings.json.tmp-*")) == []
        assert list((home / "hooks").glob(".agentihooks.json.tmp-*")) == []


class TestHooksJson:
    def test_events_use_the_shipped_enum_spellings(self, adapter):
        """agentStop / userPromptSubmitted are different TOKENS from claude's
        Stop / UserPromptSubmit — lowercasing would invent a nonexistent event."""
        assert "agentStop" in COPILOT_HOOK_EVENTS and "Stop" not in COPILOT_HOOK_EVENTS
        assert "userPromptSubmitted" in COPILOT_HOOK_EVENTS
        assert all(e[0].islower() for e in COPILOT_HOOK_EVENTS)

    def test_all_events_wired_to_wrapper(self, adapter):
        adapter.write_settings({})
        doc = json.loads((copilot_home() / "hooks" / "agentihooks.json").read_text())
        assert doc["version"] == 1
        assert set(doc["hooks"].keys()) == set(COPILOT_HOOK_EVENTS)
        for event, hooks in doc["hooks"].items():
            assert hooks[-1]["command"].endswith(f"agentihooks-hook.sh {event}")
            assert hooks[-1]["type"] == "command"
            assert hooks[-1]["timeoutSeconds"] > 0
        wrapper = (copilot_home() / "agentihooks-hook.sh").read_text()
        assert "AGENTIHOOKS_TARGET=copilot" in wrapper
        assert 'AGENTIHOOKS_COPILOT_EVENT="${1:-}"' in wrapper

    def test_hooks_are_not_also_inlined_in_settings(self, adapter):
        """Copilot merges hooks/ and the inline settings key — both fires twice."""
        adapter.write_settings({})
        doc = json.loads((copilot_home() / "settings.json").read_text())
        assert "hooks" not in doc

    def test_foreign_hooks_preserved(self, adapter):
        home = copilot_home()
        (home / "hooks").mkdir(parents=True, exist_ok=True)
        foreign = {"version": 1, "hooks": {"preToolUse": [{"type": "command", "command": "/usr/bin/audit-hook"}]}}
        (home / "hooks" / "agentihooks.json").write_text(json.dumps(foreign))
        adapter.write_settings({})
        doc = json.loads((home / "hooks" / "agentihooks.json").read_text())
        cmds = _hook_cmds(doc, "preToolUse")
        assert "/usr/bin/audit-hook" in cmds
        assert any("agentihooks-hook.sh" in c for c in cmds)

    def test_rerun_does_not_stack_own_entries(self, adapter):
        adapter.write_settings({})
        adapter.write_settings({})
        doc = json.loads((copilot_home() / "hooks" / "agentihooks.json").read_text())
        own = [c for c in _hook_cmds(doc, "sessionStart") if "agentihooks-hook.sh" in c]
        assert len(own) == 1

    def test_disabled_foreign_hook_with_wrapper_suffix_preserved(self, adapter):
        """A substring match would misclassify `<wrapper>.disabled-by-operator` as ours."""
        home = copilot_home()
        (home / "hooks").mkdir(parents=True, exist_ok=True)
        wrapper_path = home / "agentihooks-hook.sh"
        disabled_cmd = str(wrapper_path) + ".disabled-by-operator"
        foreign = {"version": 1, "hooks": {"preToolUse": [{"type": "command", "command": disabled_cmd}]}}
        (home / "hooks" / "agentihooks.json").write_text(json.dumps(foreign))
        adapter.write_settings({})
        doc = json.loads((home / "hooks" / "agentihooks.json").read_text())
        cmds = _hook_cmds(doc, "preToolUse")
        assert disabled_cmd in cmds
        assert f"{wrapper_path} preToolUse" in cmds

    def test_stale_own_entry_under_unwired_event_reaped(self, adapter):
        home = copilot_home()
        (home / "hooks").mkdir(parents=True, exist_ok=True)
        wrapper_cmd = str(home / "agentihooks-hook.sh")
        stale = {
            "version": 1,
            "hooks": {
                "PostCompact": [
                    {"type": "command", "command": wrapper_cmd},
                    {"type": "command", "command": "/usr/local/bin/operator-hook"},
                ]
            },
        }
        (home / "hooks" / "agentihooks.json").write_text(json.dumps(stale))
        adapter.write_settings({})
        doc = json.loads((home / "hooks" / "agentihooks.json").read_text())
        cmds = _hook_cmds(doc, "PostCompact")
        assert wrapper_cmd not in cmds
        assert "/usr/local/bin/operator-hook" in cmds

    def test_stale_own_only_event_removed_entirely(self, adapter):
        home = copilot_home()
        (home / "hooks").mkdir(parents=True, exist_ok=True)
        wrapper_cmd = str(home / "agentihooks-hook.sh")
        stale = {"version": 1, "hooks": {"PostCompact": [{"type": "command", "command": wrapper_cmd}]}}
        (home / "hooks" / "agentihooks.json").write_text(json.dumps(stale))
        adapter.write_settings({})
        doc = json.loads((home / "hooks" / "agentihooks.json").read_text())
        assert "PostCompact" not in doc["hooks"]

    def test_wrapper_script_quotes_paths_with_spaces(self, adapter, monkeypatch):
        spaced_root = copilot_home().parent / "agenti hooks root"
        monkeypatch.setattr(install, "AGENTIHOOKS_ROOT", spaced_root)
        adapter.write_settings({})
        script = (copilot_home() / "agentihooks-hook.sh").read_text()
        assert f"cd {shlex.quote(str(spaced_root))}" in script
        result = subprocess.run(["bash", "-n"], input=script, text=True, capture_output=True)
        assert result.returncode == 0, result.stderr


class TestPersona:
    def test_instructions_compile_chain_rules_and_manifesto(self, adapter, tmp_path, monkeypatch):
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

        text = (copilot_home() / "copilot-instructions.md").read_text()
        assert "<!-- profile: anton -->" in text
        assert "# Anton persona" in text
        assert "# Identity — who you are" in text
        assert "You are **anton**" in text
        assert text.index("# Identity") < text.index("<!-- profile: anton -->")
        assert "<!-- rule: 01-style.md" in text
        assert "Always be terse." in text
        assert "<!-- ci-manifesto -->" in text

    def test_unmanaged_instructions_backed_up(self, adapter, tmp_path):
        home = copilot_home()
        home.mkdir(parents=True, exist_ok=True)
        (home / "copilot-instructions.md").write_text("# operator's own file\n")
        prof = tmp_path / "p"
        prof.mkdir()
        (prof / "CLAUDE.md").write_text("persona")
        adapter.install_persona([("p", prof)], ["p"], None)
        assert list(home.glob("copilot-instructions*.bak.*")), "unmanaged file must be backed up"

    def test_operator_content_after_footer_survives_rerun(self, adapter, tmp_path):
        prof = tmp_path / "p"
        prof.mkdir()
        (prof / "CLAUDE.md").write_text("persona v1")
        adapter.install_persona([("p", prof)], ["p"], None)
        dst = copilot_home() / "copilot-instructions.md"
        text = dst.read_text()
        assert "<!-- agentihooks:managed-end -->" in text
        dst.write_text(text + "\n## Operator notes\nDo not touch below this line.\n")

        (prof / "CLAUDE.md").write_text("persona v2")
        adapter.install_persona([("p", prof)], ["p"], None)
        text = dst.read_text()
        assert "persona v2" in text
        assert "persona v1" not in text
        assert "## Operator notes" in text


class TestAgents:
    def _layer(self, tmp_path, name, text):
        d = tmp_path / "agents"
        d.mkdir(exist_ok=True)
        (d / name).write_text(text)
        return [("bundle", d)]

    def test_agent_installed_with_mapped_tool_names(self, adapter, tmp_path):
        layers = self._layer(
            tmp_path,
            "reviewer.md",
            "---\ndescription: Reviews code\ntools: Read, Grep, Bash\n---\n\nReview carefully.\n",
        )
        adapter.install_features("agents", layers, lambda p: p.suffix == ".md")
        out = (copilot_home() / "agents" / "reviewer.md").read_text()
        assert "description: Reviews code" in out
        assert "Review carefully." in out
        for copilot_name in ("view", "grep", "shell"):
            assert copilot_name in out
        for claude_name in ("Read,", "Grep,", "Bash\n"):
            assert claude_name not in out.split("---")[1]

    def test_scoped_grants_reduce_to_bare_mapped_tools(self, adapter, tmp_path):
        """Claude scoped grants like Bash(git diff*) are not copilot grammar --
        untranslated they load an agent with no usable tools. The scope is
        dropped and the bare tool mapped (observed live)."""
        layers = self._layer(
            tmp_path,
            "scout.md",
            "---\ndescription: scoped\ntools:\n- Bash(git diff*)\n- Bash(git log*)\n- Read\n---\n\nbody\n",
        )
        adapter.install_features("agents", layers, lambda p: p.suffix == ".md")
        out = (copilot_home() / "agents" / "scout.md").read_text()
        front = out.split("---")[1]
        assert "shell" in front
        assert "view" in front
        assert "(" not in front

    def test_claude_model_alias_dropped(self, adapter, tmp_path):
        """`model: haiku` is not a copilot model id -- copilot warns and
        falls back to auto per invocation; dropping the field IS that fallback."""
        layers = self._layer(
            tmp_path,
            "fast.md",
            "---\ndescription: fast\nmodel: haiku\n---\n\nbody\n",
        )
        adapter.install_features("agents", layers, lambda p: p.suffix == ".md")
        out = (copilot_home() / "agents" / "fast.md").read_text()
        assert "model:" not in out.split("---")[1]

    def test_description_synthesized_when_missing(self, adapter, tmp_path):
        """Copilot refuses to load an agent with no description."""
        layers = self._layer(tmp_path, "scout.md", "no frontmatter at all\n")
        adapter.install_features("agents", layers, lambda p: p.suffix == ".md")
        out = (copilot_home() / "agents" / "scout.md").read_text()
        assert "description:" in out
        assert "scout" in out

    def test_oversized_body_truncated_with_marker(self, adapter, tmp_path):
        body = "\n\n".join(["paragraph " + "x" * 200] * 400)
        layers = self._layer(tmp_path, "big.md", f"---\ndescription: Big\n---\n\n{body}\n")
        adapter.install_features("agents", layers, lambda p: p.suffix == ".md")
        out = (copilot_home() / "agents" / "big.md").read_text()
        assert len(out) < 31000
        assert "truncated by agentihooks" in out

    def test_stale_agent_reaped_on_rerun(self, adapter, tmp_path):
        layers = self._layer(tmp_path, "gone.md", "---\ndescription: X\n---\n\nbody\n")
        adapter.install_features("agents", layers, lambda p: p.suffix == ".md")
        assert (copilot_home() / "agents" / "gone.md").exists()
        (tmp_path / "agents" / "gone.md").unlink()
        adapter.install_features("agents", [("bundle", tmp_path / "agents")], lambda p: p.suffix == ".md")
        assert not (copilot_home() / "agents" / "gone.md").exists()

    def test_operator_file_not_overwritten(self, adapter, tmp_path, capsys):
        dst_dir = copilot_home() / "agents"
        dst_dir.mkdir(parents=True, exist_ok=True)
        (dst_dir / "mine.md").write_text("operator wrote this")
        layers = self._layer(tmp_path, "mine.md", "---\ndescription: X\n---\n\nbundle body\n")
        adapter.install_features("agents", layers, lambda p: p.suffix == ".md")
        assert (dst_dir / "mine.md").read_text() == "operator wrote this"
        assert "operator file wins" in capsys.readouterr().out


class TestCommandsToSkills:
    def _layer(self, tmp_path, name, text):
        d = tmp_path / "commands"
        d.mkdir(exist_ok=True)
        (d / name).write_text(text)
        return [("bundle", d)]

    def test_command_becomes_skill_folder(self, adapter, tmp_path):
        layers = self._layer(
            tmp_path, "review-changes.md", "---\ndescription: Review the diff\n---\n\nDo the review.\n"
        )
        adapter.install_features("commands", layers, lambda p: p.suffix == ".md")
        skill = agents_skills_home() / "review-changes" / "SKILL.md"
        assert skill.exists()
        text = skill.read_text()
        assert "name: review-changes" in text
        assert "description: Review the diff" in text
        assert "Do the review." in text

    def test_symlinked_skill_of_same_name_wins(self, adapter, tmp_path, capsys):
        """A real skill outranks a translated command; overwriting would delete it."""
        real_skill = tmp_path / "real-skill"
        real_skill.mkdir()
        (real_skill / "SKILL.md").write_text("real skill content")
        dst = agents_skills_home()
        dst.mkdir(parents=True, exist_ok=True)
        (dst / "collide").symlink_to(real_skill)

        layers = self._layer(tmp_path, "collide.md", "---\ndescription: X\n---\n\ncommand body\n")
        adapter.install_features("commands", layers, lambda p: p.suffix == ".md")
        assert (dst / "collide").is_symlink()
        assert (dst / "collide" / "SKILL.md").read_text() == "real skill content"
        assert "owns this name" in capsys.readouterr().out

    def test_stale_translated_command_reaped(self, adapter, tmp_path):
        layers = self._layer(tmp_path, "gone.md", "---\ndescription: X\n---\n\nbody\n")
        adapter.install_features("commands", layers, lambda p: p.suffix == ".md")
        assert (agents_skills_home() / "gone" / "SKILL.md").exists()
        (tmp_path / "commands" / "gone.md").unlink()
        adapter.install_features("commands", [("bundle", tmp_path / "commands")], lambda p: p.suffix == ".md")
        assert not (agents_skills_home() / "gone").exists()

    def test_reaping_never_touches_symlinked_skills(self, adapter, tmp_path):
        """The shared ~/.agents/skills dir also holds codex's symlinks."""
        real_skill = tmp_path / "codex-skill"
        real_skill.mkdir()
        (real_skill / "SKILL.md").write_text("shared skill")
        dst = agents_skills_home()
        dst.mkdir(parents=True, exist_ok=True)
        (dst / "shared").symlink_to(real_skill)

        layers = self._layer(tmp_path, "temp.md", "---\ndescription: X\n---\n\nbody\n")
        adapter.install_features("commands", layers, lambda p: p.suffix == ".md")
        (tmp_path / "commands" / "temp.md").unlink()
        adapter.install_features("commands", [("bundle", tmp_path / "commands")], lambda p: p.suffix == ".md")
        assert (dst / "shared").is_symlink()
        assert (dst / "shared" / "SKILL.md").read_text() == "shared skill"

    def test_real_skill_added_later_reclaims_the_name_in_one_cycle(self, adapter, tmp_path):
        """A name that was a command and is now a real skill must not stay
        shadowed: the symlinker refuses to replace a non-symlink, so the
        translated directory has to be reaped first."""
        layers = self._layer(tmp_path, "only-cmd.md", "---\ndescription: cmd\n---\n\nold command content\n")
        adapter.install_features("commands", layers, lambda p: p.suffix == ".md")
        translated = agents_skills_home() / "only-cmd"
        assert translated.is_dir() and not translated.is_symlink()

        # The bundle now also ships a real skill of that name.
        skills_src = tmp_path / "skills"
        (skills_src / "only-cmd").mkdir(parents=True)
        (skills_src / "only-cmd" / "SKILL.md").write_text("REAL SKILL")
        adapter.install_features("skills", [("bundle", skills_src)], lambda p: p.is_dir())

        assert translated.is_symlink(), "translated command still shadows the real skill"
        assert (translated / "SKILL.md").read_text() == "REAL SKILL"

    def test_reap_only_touches_manifest_owned_directories(self, adapter, tmp_path):
        """An operator directory of the same name is not ours to delete."""
        dst = agents_skills_home()
        dst.mkdir(parents=True, exist_ok=True)
        (dst / "operator-owned").mkdir()
        (dst / "operator-owned" / "SKILL.md").write_text("operator content")

        skills_src = tmp_path / "skills"
        (skills_src / "operator-owned").mkdir(parents=True)
        (skills_src / "operator-owned" / "SKILL.md").write_text("REAL SKILL")
        adapter.install_features("skills", [("bundle", skills_src)], lambda p: p.is_dir())

        assert (dst / "operator-owned" / "SKILL.md").read_text() == "operator content"

    def test_manifest_is_distinct_from_codex_prompt_manifest(self, adapter, tmp_path):
        layers = self._layer(tmp_path, "x.md", "---\ndescription: X\n---\n\nbody\n")
        adapter.install_features("commands", layers, lambda p: p.suffix == ".md")
        assert (agents_skills_home() / ".agentihooks-copilot-commands.json").exists()


class TestMcp:
    def test_stdio_server_written_as_local(self, adapter):
        adapter.register_mcp({"hooks-utils": {"command": "/usr/bin/python", "args": ["-m", "hooks.mcp"]}})
        doc = json.loads((copilot_home() / "mcp-config.json").read_text())
        entry = doc["mcpServers"]["hooks-utils"]
        assert entry["type"] == "local"
        assert entry["command"] == "/usr/bin/python"
        assert entry["args"] == ["-m", "hooks.mcp"]

    def test_sse_server_round_trips(self, adapter):
        """Codex drops SSE; copilot has an SSE client, so it must survive."""
        adapter.register_mcp({"events": {"type": "sse", "url": "https://mcp.example/sse"}})
        doc = json.loads((copilot_home() / "mcp-config.json").read_text())
        assert doc["mcpServers"]["events"]["type"] == "sse"
        assert doc["mcpServers"]["events"]["url"] == "https://mcp.example/sse"

    def test_http_server_keeps_literal_headers(self, adapter):
        adapter.register_mcp({"gw": {"type": "http", "url": "https://gw.example/mcp", "headers": {"X-Env": "prod"}}})
        doc = json.loads((copilot_home() / "mcp-config.json").read_text())
        assert doc["mcpServers"]["gw"]["headers"] == {"X-Env": "prod"}

    def test_placeholder_header_dropped(self, adapter, capsys):
        """Copilot sends header values literally — a ${VAR} would ship broken."""
        adapter.register_mcp(
            {"gw": {"type": "http", "url": "https://gw.example/mcp", "headers": {"Authorization": "Bearer ${TOKEN}"}}}
        )
        doc = json.loads((copilot_home() / "mcp-config.json").read_text())
        assert "headers" not in doc["mcpServers"]["gw"]
        assert "reference" in capsys.readouterr().out

    def test_literal_credential_in_header_is_dropped(self, adapter, capsys):
        adapter.register_mcp(
            {
                "gw": {
                    "type": "http",
                    "url": "https://gw.example/mcp",
                    "headers": {"Authorization": "Bearer ghp_" + "a" * 36},
                }
            }
        )
        doc = json.loads((copilot_home() / "mcp-config.json").read_text())
        assert "headers" not in doc["mcpServers"]["gw"]
        assert "credential" in capsys.readouterr().out

    def test_literal_credential_in_env_is_dropped(self, adapter, capsys):
        adapter.register_mcp({"srv": {"command": "/bin/srv", "env": {"API_KEY": "ghp_" + "b" * 36}}})
        doc = json.loads((copilot_home() / "mcp-config.json").read_text())
        assert "env" not in doc["mcpServers"]["srv"]
        assert "credential" in capsys.readouterr().out

    def test_credential_concatenated_onto_a_placeholder_is_dropped(self, adapter, capsys):
        """A value merely CONTAINING ${VAR} must not skip the scan."""
        adapter.register_mcp({"srv": {"command": "/bin/srv", "env": {"API_KEY": "${SAFE_VAR}-and-ghp_" + "d" * 36}}})
        doc = json.loads((copilot_home() / "mcp-config.json").read_text())
        assert "env" not in doc["mcpServers"]["srv"]
        assert "credential" in capsys.readouterr().out

    def test_credential_in_tools_list_is_dropped(self, adapter, capsys):
        adapter.register_mcp({"srv": {"command": "/bin/srv", "tools": ["read_file", "leaked-ghp_" + "e" * 36]}})
        doc = json.loads((copilot_home() / "mcp-config.json").read_text())
        assert doc["mcpServers"]["srv"]["tools"] == ["read_file"]
        assert "credential" in capsys.readouterr().out

    def test_ordinary_tools_list_survives(self, adapter):
        adapter.register_mcp({"srv": {"command": "/bin/srv", "tools": ["*"]}})
        doc = json.loads((copilot_home() / "mcp-config.json").read_text())
        assert doc["mcpServers"]["srv"]["tools"] == ["*"]

    def test_env_var_reference_survives(self, adapter):
        adapter.register_mcp({"srv": {"command": "/bin/srv", "env": {"API_KEY": "${MY_TOKEN}"}}})
        doc = json.loads((copilot_home() / "mcp-config.json").read_text())
        assert doc["mcpServers"]["srv"]["env"]["API_KEY"] == "${MY_TOKEN}"

    def test_layers_merge_rather_than_replace(self, adapter):
        adapter.register_mcp({"a": {"command": "/bin/a"}})
        adapter.register_mcp({"b": {"command": "/bin/b"}})
        doc = json.loads((copilot_home() / "mcp-config.json").read_text())
        assert set(doc["mcpServers"]) == {"a", "b"}

    def test_unbraced_env_reference_header_dropped(self, adapter, capsys):
        adapter.register_mcp(
            {"gw": {"type": "http", "url": "https://gw.example/mcp", "headers": {"X-Tok": "$MY_TOKEN"}}}
        )
        doc = json.loads((copilot_home() / "mcp-config.json").read_text())
        assert "headers" not in doc["mcpServers"]["gw"]
        assert "reference" in capsys.readouterr().out

    def test_credential_in_url_drops_the_whole_server(self, adapter, capsys):
        tok = "ghp_" + "f" * 36
        adapter.register_mcp({"bad": {"type": "http", "url": f"https://user:{tok}@gw.example/mcp"}})
        doc = json.loads((copilot_home() / "mcp-config.json").read_text())
        assert "bad" not in doc.get("mcpServers", {})
        assert "NOT written" in capsys.readouterr().out

    def test_credential_in_args_drops_the_whole_server(self, adapter, capsys):
        tok = "ghp_" + "g" * 36
        adapter.register_mcp({"bad": {"command": "/bin/srv", "args": ["--token", tok]}})
        doc = json.loads((copilot_home() / "mcp-config.json").read_text())
        assert "bad" not in doc.get("mcpServers", {})
        assert "NOT written" in capsys.readouterr().out

    def test_registered_names_recorded_for_teardown(self, adapter):
        adapter.register_mcp({"a": {"command": "/bin/a"}})
        state = install._load_state()
        assert "a" in install._global_record(state, "copilot").get("managed_mcp", [])

    def test_operator_servers_preserved(self, adapter):
        home = copilot_home()
        home.mkdir(parents=True, exist_ok=True)
        (home / "mcp-config.json").write_text(json.dumps({"mcpServers": {"mine": {"type": "local", "command": "x"}}}))
        adapter.register_mcp({"a": {"command": "/bin/a"}})
        doc = json.loads((home / "mcp-config.json").read_text())
        assert "mine" in doc["mcpServers"]
        assert "a" in doc["mcpServers"]


class TestDoctor:
    def test_reports_failures_on_bare_home(self, adapter, capsys):
        assert adapter.doctor() > 0
        assert "settings.json missing" in capsys.readouterr().out

    def test_passes_core_checks_after_install(self, adapter, tmp_path, capsys):
        adapter.write_settings({})
        adapter.register_mcp({"hooks-utils": {"command": "/usr/bin/python", "args": ["-m", "hooks.mcp"]}})
        prof = tmp_path / "p"
        prof.mkdir()
        (prof / "CLAUDE.md").write_text("persona")
        adapter.install_persona([("p", prof)], ["p"], None)
        adapter.doctor()
        out = capsys.readouterr().out
        assert "[!!] settings.json missing" not in out
        assert "[!!] mcp-config.json missing" not in out
        assert "[!!] copilot-instructions.md missing" not in out
        assert "agentihooks.json wires" in out


class TestAdapterRegistration:
    def test_get_adapter_returns_copilot(self):
        from scripts.targets import SUPPORTED_TARGETS, get_adapter

        assert "copilot" in SUPPORTED_TARGETS
        assert get_adapter("copilot").name == "copilot"

    def test_importable_under_bare_targets_identity(self):
        from targets.copilot_target import CopilotAdapter as Bare

        assert Bare().name == "copilot"


class TestTeardown:
    def _full_install(self, adapter, tmp_path):
        adapter.write_settings({"permissions": {"defaultMode": "bypassPermissions"}})
        adapter.register_mcp({"hooks-utils": {"command": "/usr/bin/python", "args": ["-m", "hooks.mcp"]}})
        agents_src = tmp_path / "agents"
        agents_src.mkdir(exist_ok=True)
        (agents_src / "scout.md").write_text("---\ndescription: X\n---\n\nbody\n")
        adapter.install_features("agents", [("bundle", agents_src)], lambda p: p.suffix == ".md")
        cmds_src = tmp_path / "commands"
        cmds_src.mkdir(exist_ok=True)
        (cmds_src / "review.md").write_text("---\ndescription: X\n---\n\nbody\n")
        adapter.install_features("commands", [("bundle", cmds_src)], lambda p: p.suffix == ".md")
        prof = tmp_path / "prof"
        prof.mkdir(exist_ok=True)
        (prof / "CLAUDE.md").write_text("persona")
        adapter.install_persona([("p", prof)], ["p"], None)

    def test_removes_own_artifacts(self, adapter, tmp_path):
        self._full_install(adapter, tmp_path)
        adapter.teardown()
        home = copilot_home()
        assert not (home / "agentihooks-hook.sh").exists()
        assert not (home / "hooks" / "agentihooks.json").exists()
        assert not (home / "copilot-instructions.md").exists()
        assert not (home / "agents" / "scout.md").exists()
        assert not (agents_skills_home() / "review").exists()
        doc = json.loads((home / "settings.json").read_text())
        assert "agentihooks" not in doc
        assert "statusLine" not in doc
        assert str(install.AGENTIHOOKS_ROOT) not in doc.get("trustedFolders", [])
        mcp = json.loads((home / "mcp-config.json").read_text())
        assert "hooks-utils" not in mcp.get("mcpServers", {})
        assert install._global_record(install._load_state(), "copilot").get("managed_mcp") is None

    def test_preserves_operator_content(self, adapter, tmp_path):
        self._full_install(adapter, tmp_path)
        home = copilot_home()
        doc = json.loads((home / "settings.json").read_text())
        doc["theme"] = "dim"
        (home / "settings.json").write_text(json.dumps(doc))
        hooks_doc = json.loads((home / "hooks" / "agentihooks.json").read_text())
        hooks_doc["hooks"]["preToolUse"].append({"type": "command", "command": "/usr/bin/operator-hook"})
        (home / "hooks" / "agentihooks.json").write_text(json.dumps(hooks_doc))
        persona = home / "copilot-instructions.md"
        persona.write_text(persona.read_text() + "\n## operator tail\n")
        mcp = json.loads((home / "mcp-config.json").read_text())
        mcp["mcpServers"]["operators-own"] = {"type": "local", "command": "/bin/x"}
        (home / "mcp-config.json").write_text(json.dumps(mcp))

        adapter.teardown()

        doc = json.loads((home / "settings.json").read_text())
        assert doc["theme"] == "dim"
        hooks_doc = json.loads((home / "hooks" / "agentihooks.json").read_text())
        assert hooks_doc["hooks"]["preToolUse"][0]["command"] == "/usr/bin/operator-hook"
        assert "## operator tail" in persona.read_text()
        assert "managed-by: agentihooks" not in persona.read_text()
        mcp = json.loads((home / "mcp-config.json").read_text())
        assert "operators-own" in mcp["mcpServers"]

    def test_hand_edited_managed_key_survives(self, adapter, tmp_path):
        self._full_install(adapter, tmp_path)
        home = copilot_home()
        doc = json.loads((home / "settings.json").read_text())
        doc["statusLine"] = {"type": "command", "command": "/usr/local/bin/my-status"}
        (home / "settings.json").write_text(json.dumps(doc))
        adapter.teardown()
        doc = json.loads((home / "settings.json").read_text())
        assert doc["statusLine"]["command"] == "/usr/local/bin/my-status"

    def test_idempotent_on_clean_home(self, adapter):
        adapter.teardown()
        adapter.teardown()


class TestTeardownDestructiveEdges:
    def test_header_without_footer_preserves_whole_file_as_backup(self, adapter):
        from scripts.targets.copilot_target import _MANAGED_HEADER

        home = copilot_home()
        home.mkdir(parents=True, exist_ok=True)
        (home / "copilot-instructions.md").write_text(_MANAGED_HEADER + "\nmanaged\n\nMY OWN NOTES\n")
        adapter.teardown()
        assert not (home / "copilot-instructions.md").exists()
        baks = list(home.glob("copilot-instructions*.bak*"))
        assert baks and any("MY OWN NOTES" in b.read_text() for b in baks)

    def test_unrecorded_operator_hooks_utils_survives(self, adapter, capsys):
        home = copilot_home()
        home.mkdir(parents=True, exist_ok=True)
        (home / "mcp-config.json").write_text(
            json.dumps({"mcpServers": {"hooks-utils": {"type": "local", "command": "/opt/operator-own/server"}}})
        )
        adapter.teardown()
        doc = json.loads((home / "mcp-config.json").read_text())
        assert "hooks-utils" in doc["mcpServers"]
        assert "review it" in capsys.readouterr().out

    def test_missing_record_content_verified_statusline_removed(self, adapter):
        home = copilot_home()
        home.mkdir(parents=True, exist_ok=True)
        (home / "settings.json").write_text(
            json.dumps({"statusLine": {"type": "command", "command": "python -m hooks.statusline"}})
        )
        adapter.teardown()
        doc = json.loads((home / "settings.json").read_text())
        assert "statusLine" not in doc

    def test_missing_record_operator_statusline_survives(self, adapter):
        home = copilot_home()
        home.mkdir(parents=True, exist_ok=True)
        (home / "settings.json").write_text(
            json.dumps({"statusLine": {"type": "command", "command": "/usr/local/bin/my-status"}})
        )
        adapter.teardown()
        doc = json.loads((home / "settings.json").read_text())
        assert doc["statusLine"]["command"] == "/usr/local/bin/my-status"

    def test_unparseable_hooks_file_backed_up_not_deleted(self, adapter):
        home = copilot_home()
        (home / "hooks").mkdir(parents=True, exist_ok=True)
        (home / "hooks" / "agentihooks.json").write_text('{"hooks": {"x": [{"command": "operator_hook"}]}],,,')
        adapter.teardown()
        assert not (home / "hooks" / "agentihooks.json").exists()
        baks = list((home / "hooks").glob("agentihooks*.bak*"))
        assert baks and any("operator_hook" in b.read_text() for b in baks)


class TestManagedSidecar:
    """The managed-key record lives in .agentihooks-managed.json — an in-file
    `agentihooks` key makes copilot warn about unknown settings keys on every
    launch (observed v1.0.80)."""

    def test_settings_json_carries_no_agentihooks_key(self, adapter):
        adapter.write_settings({})
        doc = json.loads((copilot_home() / "settings.json").read_text())
        assert "agentihooks" not in doc
        sidecar = json.loads((copilot_home() / ".agentihooks-managed.json").read_text())
        assert "statusLine" in sidecar

    def test_legacy_infile_record_migrates_and_key_is_removed(self, adapter):
        home = copilot_home()
        home.mkdir(parents=True, exist_ok=True)
        old_status = {"type": "command", "command": "/old/python -m hooks.statusline"}
        (home / "settings.json").write_text(
            json.dumps({"agentihooks": {"managed": {"statusLine": old_status}}, "statusLine": old_status})
        )
        adapter.write_settings({})
        doc = json.loads((home / "settings.json").read_text())
        assert "agentihooks" not in doc
        assert "hooks.statusline" in doc["statusLine"]["command"], "recorded value must still count as ours"

    def test_teardown_reads_sidecar_and_removes_it(self, adapter):
        adapter.write_settings({})
        adapter.teardown()
        home = copilot_home()
        assert not (home / ".agentihooks-managed.json").exists()
        doc = json.loads((home / "settings.json").read_text())
        assert "statusLine" not in doc


class TestSidecarSelfHeal:
    """A lost/deleted .agentihooks-managed.json with settings.json still
    holding our values must not brand every managed key a permanent hand-edit."""

    def test_sidecar_loss_reheals_and_does_not_warn(self, adapter, capsys):
        adapter.write_settings({})
        home = copilot_home()
        sidecar = adapter._managed_sidecar(home)
        assert sidecar.exists()
        sidecar.unlink()
        capsys.readouterr()

        adapter.write_settings({})
        out = capsys.readouterr().out
        assert "hand-set" not in out, "sidecar loss with our value intact must not read as a hand-edit"
        healed = json.loads(sidecar.read_text())
        assert "statusLine" in healed and "disableAllHooks" in healed, "sidecar must re-heal all managed keys"

    def test_genuine_hand_edit_still_detected_after_sidecar_loss(self, adapter, capsys):
        adapter.write_settings({})
        home = copilot_home()
        doc = json.loads((home / "settings.json").read_text())
        doc["statusLine"] = {"type": "command", "command": "/usr/local/bin/mine"}
        (home / "settings.json").write_text(json.dumps(doc))
        adapter._managed_sidecar(home).unlink()
        capsys.readouterr()

        adapter.write_settings({})
        out = capsys.readouterr().out
        assert "hand-set" in out, "a real hand-edit that differs from our value must still be respected"
        doc = json.loads((home / "settings.json").read_text())
        assert doc["statusLine"]["command"] == "/usr/local/bin/mine"
