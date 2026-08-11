"""Shared test fixtures for agentihooks."""

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


@pytest.fixture(autouse=True)
def _isolate_real_user_paths(tmp_path, monkeypatch):
    """Redirect every real-home path away from the developer's machine.

    `install.py` reaches the real home through more routes than the obvious
    globals, and they are hit transitively — `_install_system_prompt` →
    `_record_managed_claude_md` → `_save_state` — so a test that never mentions
    any of them still writes real files. This has already destroyed a real
    `~/.claude/CLAUDE.md` and uninstalled the real CLI once each.

    `Path.home` itself is patched, not just the derived symbols. That is the only
    thing that closes call sites which build the path inline — notably
    `_migrate_profile_rename`, which does `Path.home() / ".claude.json"` as a raw
    literal and so cannot be neutralised by patching module attributes. The
    derived globals are then re-pointed for the modules that bound them at import.

    Autouse and suite-wide on purpose: opting in per file is how the gap
    reappeared last time.
    """
    real_home = Path.home()
    fake_home = tmp_path / "_home"
    (fake_home / ".claude").mkdir(parents=True)
    (fake_home / ".agentihooks").mkdir(parents=True)
    (fake_home / ".codex").mkdir(parents=True)
    (fake_home / ".agents" / "skills").mkdir(parents=True)

    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    # CODEX_HOME is read BEFORE Path.home() by targets.codex_target.codex_home,
    # so patching Path.home does not cover it. Unset today on the developer's
    # machine, which is luck, not isolation — an operator who exports it (the
    # installer supports a comma list) would have the whole suite writing into
    # their real codex install.
    monkeypatch.delenv("CODEX_HOME", raising=False)

    try:
        import install
    except Exception:  # suite runs fine without the installer importable
        yield
        return

    monkeypatch.setattr(install, "CLAUDE_HOME", fake_home / ".claude", raising=False)
    monkeypatch.setattr(install, "AGENTIHOOKS_STATE_DIR", fake_home / ".agentihooks", raising=False)
    monkeypatch.setattr(install, "STATE_JSON", fake_home / ".agentihooks" / "state.json", raising=False)
    monkeypatch.setattr(install, "_CLAUDE_JSON", fake_home / ".claude.json", raising=False)
    monkeypatch.setattr(install, "_BASHRC", fake_home / ".bashrc", raising=False)
    # AGENTIHOOKS_ROOT is `Path(__file__).parent.parent` — the real checkout. It
    # feeds `_managed_roots()`, so leaving it real means every ownership test runs
    # with the developer's own repo silently trusted as a source. Nothing collides
    # with it today, which is luck, not isolation.
    monkeypatch.setattr(install, "AGENTIHOOKS_ROOT", tmp_path / "_repo", raising=False)
    # Same reasoning for the env-var bundle: `_managed_roots()` takes it verbatim,
    # so a developer with it exported would run a different suite than CI.
    monkeypatch.delenv("AGENTIHOOKS_BUNDLE_PATH", raising=False)

    for name in ("CLAUDE_HOME", "AGENTIHOOKS_STATE_DIR", "STATE_JSON", "_CLAUDE_JSON", "_BASHRC", "AGENTIHOOKS_ROOT"):
        if not hasattr(install, name):
            continue
        value = Path(getattr(install, name))
        assert real_home not in value.parents and value != real_home, (
            f"install.{name} still resolves under the real home ({value}) — refusing to run"
        )
    assert Path.home() != real_home, "Path.home() still returns the real home — refusing to run"

    # Codex writes through its own resolvers, not install.py globals, so the
    # loop above cannot see them. Assert the same refusal bar.
    try:
        from targets.codex_target import agents_skills_home, codex_home
    except Exception:
        yield
        return
    for label, value in (("codex_home", codex_home()), ("agents_skills_home", agents_skills_home())):
        assert real_home not in value.parents and value != real_home, (
            f"{label}() still resolves under the real home ({value}) — refusing to run"
        )
    yield


@pytest.fixture
def mock_env():
    """Provide a clean environment for tests."""
    env = {
        "CLAUDE_HOOK_LOG_ENABLED": "true",
        "CLAUDE_HOOK_LOG_FILE": "/tmp/test-hooks.log",
    }
    with patch.dict(os.environ, env, clear=False):
        yield env


@pytest.fixture
def tmp_log_file(tmp_path):
    """Provide a temporary log file path."""
    return tmp_path / "test.log"


@pytest.fixture
def sample_transcript_entry():
    """A sample transcript JSONL entry."""
    return {
        "type": "user",
        "message": {"content": [{"type": "text", "text": "Hello Claude"}]},
        "timestamp": "2026-01-15T10:00:00Z",
        "uuid": "test-uuid-001",
    }


@pytest.fixture
def sample_tool_use_event():
    """A sample PreToolUse hook event."""
    return {
        "session_id": "test-session",
        "tool_name": "Write",
        "tool_input": {"file_path": "/tmp/test.txt", "content": "hello"},
    }
