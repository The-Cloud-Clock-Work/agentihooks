"""Tests for hooks.context.codex_context_pin."""

import json
import stat

import pytest

pytestmark = pytest.mark.unit


def _catalog(tmp_path, **windows):
    models = [{"slug": slug, "max_context_window": w} for slug, w in windows.items()]
    (tmp_path / "models_cache.json").write_text(json.dumps({"models": models}))
    return tmp_path / "models_cache.json"


class TestCodexContextPin:
    def test_raises_capped_entries_to_the_advertised_ceiling(self, tmp_path, monkeypatch):
        from hooks.context.codex_context_pin import pin

        path = _catalog(tmp_path, sol=272000, terra=872000)
        monkeypatch.setenv("CODEX_HOME", str(tmp_path))

        assert pin() == (1, 872000)
        windows = {m["slug"]: m["max_context_window"] for m in json.loads(path.read_text())["models"]}
        assert windows == {"sol": 872000, "terra": 872000}

    def test_locks_the_cache_against_codex(self, tmp_path, monkeypatch):
        from hooks.context.codex_context_pin import pin

        path = _catalog(tmp_path, sol=272000, terra=872000)
        monkeypatch.setenv("CODEX_HOME", str(tmp_path))
        pin()

        assert stat.S_IMODE(path.stat().st_mode) == 0o444

    def test_unpin_restores_write_access(self, tmp_path, monkeypatch):
        from hooks.context.codex_context_pin import pin, unpin

        path = _catalog(tmp_path, sol=272000, terra=872000)
        monkeypatch.setenv("CODEX_HOME", str(tmp_path))
        pin()

        assert unpin() is True
        assert stat.S_IMODE(path.stat().st_mode) == 0o644

    def test_second_pin_raises_nothing(self, tmp_path, monkeypatch):
        from hooks.context.codex_context_pin import pin

        _catalog(tmp_path, sol=272000, terra=872000)
        monkeypatch.setenv("CODEX_HOME", str(tmp_path))
        pin()

        assert pin() == (0, 872000)

    def test_missing_cache_is_not_an_error(self, tmp_path, monkeypatch):
        from hooks.context.codex_context_pin import pin, unpin

        monkeypatch.setenv("CODEX_HOME", str(tmp_path))

        assert pin() is None
        assert unpin() is False
