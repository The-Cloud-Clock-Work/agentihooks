"""Tests for hooks.context.codex_context_pin."""

import json

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture
def codex(tmp_path, monkeypatch):
    (tmp_path / "codex").mkdir()
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    monkeypatch.setattr("hooks.config.AGENTIHOOKS_HOME", tmp_path / "state")
    (tmp_path / "state").mkdir()
    return tmp_path / "codex" / "models_cache.json"


def _write(path, **windows):
    path.write_text(json.dumps({"models": [{"slug": s, "max_context_window": w} for s, w in windows.items()]}))


def _catalog_windows():
    from hooks.context.codex_context_pin import catalog_path

    return {m["slug"]: m["max_context_window"] for m in json.loads(catalog_path().read_text())["models"]}


class TestCodexContextPin:
    def test_keeps_a_window_the_catalog_walked_back(self, codex):
        from hooks.context.codex_context_pin import refresh

        _write(codex, **{"gpt-5.6-sol": 872000})
        refresh()

        _write(codex, **{"gpt-5.6-sol": 272000})
        restored, _ = refresh()

        assert restored == 1
        assert _catalog_windows() == {"gpt-5.6-sol": 872000}

    def test_never_inflates_a_model_from_a_larger_sibling(self, codex):
        from hooks.context.codex_context_pin import refresh

        _write(codex, **{"gpt-5.6-sol": 272000, "gpt-5.4": 1000000})
        refresh()

        assert _catalog_windows() == {"gpt-5.6-sol": 272000, "gpt-5.4": 1000000}

    def test_adopts_a_genuinely_raised_ceiling(self, codex):
        from hooks.context.codex_context_pin import refresh

        _write(codex, **{"gpt-5.6-sol": 272000})
        refresh()

        _write(codex, **{"gpt-5.6-sol": 1000000})
        refresh()

        assert _catalog_windows() == {"gpt-5.6-sol": 1000000}

    def test_releases_a_lock_left_by_the_earlier_build(self, codex):
        import stat

        from hooks.context.codex_context_pin import refresh

        _write(codex, **{"gpt-5.6-sol": 872000})
        codex.chmod(0o444)
        refresh()

        assert stat.S_IMODE(codex.stat().st_mode) == 0o644

    def test_survives_a_live_cache_codex_has_not_written_yet(self, codex):
        from hooks.context.codex_context_pin import catalog_path, refresh

        _write(codex, **{"gpt-5.6-sol": 872000})
        refresh()
        codex.unlink()

        assert refresh()[0] == 0
        assert json.loads(catalog_path().read_text())["models"]

    def test_no_catalog_anywhere_is_not_an_error(self, codex):
        from hooks.context.codex_context_pin import refresh

        assert refresh() is None
