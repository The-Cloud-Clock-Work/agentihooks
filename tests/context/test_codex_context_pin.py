"""Tests for hooks.context.codex_context_pin."""

import json
import stat

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture
def codex(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    (tmp_path / "codex").mkdir()
    monkeypatch.setattr("hooks.config.AGENTIHOOKS_HOME", tmp_path / "state")
    return tmp_path / "codex" / "models_cache.json"


def _write(path, **windows):
    path.write_text(json.dumps({"models": [{"slug": s, "max_context_window": w} for s, w in windows.items()]}))


def _windows(path):
    return {m["slug"]: m["max_context_window"] for m in json.loads(path.read_text())["models"]}


class TestCodexContextPin:
    def test_restores_a_window_the_catalog_walked_back(self, codex):
        from hooks.context.codex_context_pin import pin

        _write(codex, **{"gpt-5.6-sol": 872000})
        pin()

        codex.chmod(0o644)
        _write(codex, **{"gpt-5.6-sol": 272000})
        raised, _ = pin()

        assert raised == 1
        assert _windows(codex) == {"gpt-5.6-sol": 872000}

    def test_never_inflates_a_model_from_a_larger_sibling(self, codex):
        from hooks.context.codex_context_pin import pin

        _write(codex, **{"gpt-5.6-sol": 272000, "gpt-5.4": 1000000})
        pin()

        assert _windows(codex) == {"gpt-5.6-sol": 272000, "gpt-5.4": 1000000}

    def test_locks_the_cache_against_codex(self, codex):
        from hooks.context.codex_context_pin import pin

        _write(codex, **{"gpt-5.6-sol": 872000})
        pin()

        assert stat.S_IMODE(codex.stat().st_mode) == 0o444

    def test_unpin_restores_write_access(self, codex):
        from hooks.context.codex_context_pin import pin, unpin

        _write(codex, **{"gpt-5.6-sol": 872000})
        pin()

        assert unpin() is True
        assert stat.S_IMODE(codex.stat().st_mode) == 0o644

    def test_steady_state_raises_nothing(self, codex):
        from hooks.context.codex_context_pin import pin

        _write(codex, **{"gpt-5.6-sol": 872000})
        pin()

        assert pin()[0] == 0

    def test_missing_cache_is_not_an_error(self, codex):
        from hooks.context.codex_context_pin import pin, unpin

        codex.unlink(missing_ok=True)

        assert pin() is None
        assert unpin() is False
