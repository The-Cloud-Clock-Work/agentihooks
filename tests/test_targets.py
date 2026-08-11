"""Tests for the install-target abstraction (scripts/targets/).

Covers: resolve_target precedence, the legacy→keyed state.json shape
migration, per-target coexistence in state, and the codex not-yet-installable
rejection. The claude-byte-identical regression bar is exercised operationally
(tar-diff in the milestone evidence), not here.
"""

import json

import install
import pytest

from scripts.targets import DEFAULT_TARGET, get_adapter, resolve_target


class TestResolveTarget:
    def test_cli_flag_wins(self, monkeypatch):
        monkeypatch.setenv("AGENTIHOOKS_TARGET", "claude")
        assert resolve_target("codex", "claude", (), interactive_ok=False) == "codex"

    def test_env_beats_stored(self, monkeypatch):
        monkeypatch.setenv("AGENTIHOOKS_TARGET", "codex")
        assert resolve_target(None, "claude", (), interactive_ok=False) == "codex"

    def test_stored_alone_no_longer_wins_noninteractive(self, monkeypatch):
        # `stored` is now only the interactive prompt's default — with no
        # installed-target match and no TTY, it must NOT hijack resolution.
        monkeypatch.delenv("AGENTIHOOKS_TARGET", raising=False)
        assert resolve_target(None, "codex", (), interactive_ok=False) == DEFAULT_TARGET

    def test_single_installed_target_wins_noninteractive(self, monkeypatch):
        monkeypatch.delenv("AGENTIHOOKS_TARGET", raising=False)
        assert resolve_target(None, "", ("codex",), interactive_ok=False) == "codex"

    def test_multiple_installed_targets_warn_and_default_noninteractive(self, monkeypatch, capsys):
        monkeypatch.delenv("AGENTIHOOKS_TARGET", raising=False)
        result = resolve_target(None, "codex", ("claude", "codex"), interactive_ok=False)
        assert result == DEFAULT_TARGET
        err = capsys.readouterr().err
        assert "multiple" in err.lower()
        assert "--target" in err

    def test_default_is_claude(self, monkeypatch):
        monkeypatch.delenv("AGENTIHOOKS_TARGET", raising=False)
        assert resolve_target(None, "", (), interactive_ok=False) == DEFAULT_TARGET

    def test_unknown_target_exits(self, monkeypatch):
        monkeypatch.delenv("AGENTIHOOKS_TARGET", raising=False)
        with pytest.raises(SystemExit):
            resolve_target("emacs", "", (), interactive_ok=False)

    def test_case_insensitive(self, monkeypatch):
        monkeypatch.delenv("AGENTIHOOKS_TARGET", raising=False)
        assert resolve_target("Claude", "", (), interactive_ok=False) == "claude"


class TestStateShapeMigration:
    def test_legacy_flat_record_rewrapped_under_claude(self):
        state = {
            "targets": {
                "global": {
                    "path": "/home/x/.claude",
                    "profile": "anton",
                    "installed_at": "2026-01-01T00:00:00+00:00",
                }
            }
        }
        assert install._migrate_targets_shape(state) is True
        assert state["targets"]["global"]["claude"]["profile"] == "anton"
        # Idempotent: second pass is a no-op
        assert install._migrate_targets_shape(state) is False

    def test_new_shape_untouched(self):
        state = {"targets": {"global": {"claude": {"profile": "anton", "path": "/x"}}}}
        assert install._migrate_targets_shape(state) is False

    def test_empty_state_untouched(self):
        state: dict = {}
        assert install._migrate_targets_shape(state) is False

    def test_load_state_migrates_on_disk(self):
        legacy = {"targets": {"global": {"path": "/h/.claude", "profile": "smith"}}}
        install.STATE_JSON.parent.mkdir(parents=True, exist_ok=True)
        install.STATE_JSON.write_text(json.dumps(legacy))
        state = install._load_state()
        assert state["targets"]["global"]["claude"]["profile"] == "smith"
        on_disk = json.loads(install.STATE_JSON.read_text())
        assert on_disk["targets"]["global"]["claude"]["profile"] == "smith"

    def test_mixed_shape_preserves_codex_and_nests_claude_fields(self):
        # A version-skewed pre-multi-target binary writes flat claude fields
        # back onto an already-migrated targets.global that also holds a
        # keyed codex record. The codex record must survive.
        state = {
            "targets": {
                "global": {
                    "path": "/home/x/.claude",
                    "profile": "anton",
                    "installed_at": "2026-01-01T00:00:00+00:00",
                    "codex": {"path": "/home/x/.codex", "profile": "smith"},
                }
            }
        }
        assert install._migrate_targets_shape(state) is True
        assert state["targets"]["global"]["codex"]["profile"] == "smith"
        assert state["targets"]["global"]["claude"]["profile"] == "anton"
        assert state["targets"]["global"]["claude"]["path"] == "/home/x/.claude"
        # Idempotent
        assert install._migrate_targets_shape(state) is False


class TestGlobalRecord:
    def test_read_missing_returns_empty(self):
        assert install._global_record({}) == {}

    def test_create_materializes(self):
        state: dict = {}
        rec = install._global_record(state, create=True)
        rec["profile"] = "anton"
        assert state["targets"]["global"]["claude"]["profile"] == "anton"

    def test_per_target_isolation(self):
        state: dict = {}
        install._global_record(state, "claude", create=True)["profile"] = "anton"
        install._global_record(state, "codex", create=True)["profile"] = "smith"
        assert install._global_record(state, "claude")["profile"] == "anton"
        assert install._global_record(state, "codex")["profile"] == "smith"


class TestRegisterTargetGlobal:
    def test_register_keys_by_target_and_persists_recall(self):
        install._register_target_global("anton", settings_profile="lean")
        state = install._load_state()
        rec = state["targets"]["global"]["claude"]
        assert rec["profile"] == "anton"
        assert rec["settings_profile"] == "lean"
        assert state["install_target"] == "claude"

    def test_second_target_does_not_clobber_first(self):
        install._register_target_global("anton")
        # Simulate a codex record landing next to it (adapter not needed).
        state = install._load_state()
        state["targets"]["global"]["codex"] = {"path": "/h/.codex", "profile": "smith"}
        install._save_state(state)
        install._register_target_global("anton,brain")
        state = install._load_state()
        assert state["targets"]["global"]["codex"]["profile"] == "smith"
        assert state["targets"]["global"]["claude"]["profile"] == "anton,brain"

    @staticmethod
    def _installed(state: dict) -> tuple:
        """Mirror the installed-target extraction cmd_init_unified performs
        before calling resolve_target."""
        return tuple(t for t, v in state.get("targets", {}).get("global", {}).items() if isinstance(v, dict))

    def test_bare_noninteractive_resolve_after_claude_then_codex_init_stays_claude(self, capsys):
        # This is the HIGH-severity hijack: `init --target codex` used to
        # make every later bare, non-interactive `init` silently reinstall
        # codex via the unscoped `install_target` recall key.
        install._register_target_global("anton")
        install._register_target_global("smith", target="codex")
        state = install._load_state()
        stored = state.get("install_target", "")
        assert stored == "codex"  # last-used, as documented — see next test
        installed = self._installed(state)
        result = resolve_target(None, stored, installed, interactive_ok=False)
        assert result == "claude"
        err = capsys.readouterr().err
        assert "multiple" in err.lower()
        assert "--target" in err

    def test_codex_only_state_bare_noninteractive_resolve_recalls_codex(self):
        install._register_target_global("smith", target="codex")
        state = install._load_state()
        installed = self._installed(state)
        stored = state.get("install_target", "")
        result = resolve_target(None, stored, installed, interactive_ok=False)
        assert result == "codex"

    def test_install_target_is_last_used_but_does_not_drive_noninteractive_resolution(self):
        install._register_target_global("anton")
        install._register_target_global("smith", target="codex")
        state = install._load_state()
        # Recall key is last-writer-wins, as documented at the write site.
        assert state["install_target"] == "codex"
        # But with both records present, resolution is ambiguous and falls
        # to DEFAULT_TARGET rather than trusting `install_target`.
        installed = self._installed(state)
        result = resolve_target(None, state["install_target"], installed, interactive_ok=False)
        assert result == "claude"


class TestGetAdapter:
    def test_claude_adapter_resolves(self):
        adapter = get_adapter("claude")
        assert adapter.name == "claude"
        assert adapter.home() == install.CLAUDE_HOME

    def test_codex_adapter_resolves(self):
        adapter = get_adapter("codex")
        assert adapter.name == "codex"
        assert adapter.home().name == ".codex"


class TestInstalledTargets:
    def test_lists_every_record_in_supported_order(self):
        state = {"targets": {"global": {"codex": {"profile": "a"}, "claude": {"profile": "b"}}}}
        assert install._installed_targets(state) == ("claude", "codex")

    def test_empty_state_defaults_to_claude(self):
        assert install._installed_targets({}) == ("claude",)

    def test_default_is_overridable_for_init(self):
        """init must tell 'nothing installed' from 'claude installed' — the
        first prompts, the second recalls."""
        assert install._installed_targets({}, default=()) == ()

    def test_unknown_target_name_is_kept(self):
        state = {"targets": {"global": {"claude": {"profile": "a"}, "future": {"profile": "z"}}}}
        assert install._installed_targets(state) == ("claude", "future")

    def test_legacy_flat_state_reports_claude(self):
        assert install._installed_targets({"targets": {"global": {"profile": "anton"}}}) == ("claude",)


class TestTargetConstantParity:
    """``hooks/targets`` and ``scripts/targets`` each define DEFAULT_TARGET.

    They cannot share one: the hook runtime must not import the installer
    (``scripts`` is not on the hook process's import path), and the installer
    already imports ``hooks``. A tripwire is cheaper than a refactor and turns
    silent drift — which would send hook-runtime reads to a different record
    than the installer writes — into a loud failure.
    """

    def test_default_target_agrees_across_packages(self):
        from hooks.targets import DEFAULT_TARGET as hooks_default
        from scripts.targets import DEFAULT_TARGET as scripts_default

        assert hooks_default == scripts_default

    def test_default_target_is_a_supported_target(self):
        from hooks.targets import DEFAULT_TARGET as hooks_default
        from scripts.targets import SUPPORTED_TARGETS

        assert hooks_default in SUPPORTED_TARGETS
