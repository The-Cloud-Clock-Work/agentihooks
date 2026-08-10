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
        assert resolve_target("codex", "claude", interactive_ok=False) == "codex"

    def test_env_beats_stored(self, monkeypatch):
        monkeypatch.setenv("AGENTIHOOKS_TARGET", "codex")
        assert resolve_target(None, "claude", interactive_ok=False) == "codex"

    def test_stored_beats_default(self, monkeypatch):
        monkeypatch.delenv("AGENTIHOOKS_TARGET", raising=False)
        assert resolve_target(None, "codex", interactive_ok=False) == "codex"

    def test_default_is_claude(self, monkeypatch):
        monkeypatch.delenv("AGENTIHOOKS_TARGET", raising=False)
        assert resolve_target(None, "", interactive_ok=False) == DEFAULT_TARGET

    def test_unknown_target_exits(self, monkeypatch):
        monkeypatch.delenv("AGENTIHOOKS_TARGET", raising=False)
        with pytest.raises(SystemExit):
            resolve_target("emacs", "", interactive_ok=False)

    def test_case_insensitive(self, monkeypatch):
        monkeypatch.delenv("AGENTIHOOKS_TARGET", raising=False)
        assert resolve_target("Claude", "", interactive_ok=False) == "claude"


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


class TestGetAdapter:
    def test_claude_adapter_resolves(self):
        adapter = get_adapter("claude")
        assert adapter.name == "claude"
        assert adapter.home() == install.CLAUDE_HOME

    def test_codex_rejected_not_yet_installable(self):
        with pytest.raises(SystemExit) as exc:
            get_adapter("codex")
        assert exc.value.code == 2
