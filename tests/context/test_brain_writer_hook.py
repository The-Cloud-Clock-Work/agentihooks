"""brain_writer_hook — outbox buffer + HTTP drain behavior.

Covers the shared-outbox race (concurrent drains of the same file must not
crash the caller), quarantine of unparseable files, refusal retention, and
idempotency-key parity between a live POST and its outbox replay.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import hooks._brain_http as brain_http
from hooks.context.brain_writer_hook import (
    _drain_outbox,
    _marker_request,
    _write_to_outbox,
)

MARKER = {"type": "lesson", "content": "test lesson", "attrs": {"scope": "x"}}


@pytest.fixture
def http_ok(monkeypatch):
    """Stub the HTTP layer to accept every POST, recording calls."""
    calls: list[tuple[dict, str]] = []
    monkeypatch.setattr(brain_http, "brain_http_enabled", lambda: True)
    monkeypatch.setattr(
        brain_http,
        "post",
        lambda path, body=None, idempotency_key=None: (
            calls.append((body, idempotency_key)) or {"ok": True}
        ),
    )
    return calls


def test_drain_posts_and_deletes(tmp_path, http_ok):
    _write_to_outbox([MARKER], "sess-1", str(tmp_path))
    assert _drain_outbox(str(tmp_path)) == 1
    assert not list(tmp_path.glob("*.json"))


def test_drain_key_matches_live_post_key(tmp_path, http_ok):
    _write_to_outbox([MARKER], "sess-1", str(tmp_path))
    _drain_outbox(str(tmp_path))
    _, live_key = _marker_request(MARKER, "sess-1")
    assert http_ok[0][1] == live_key


def test_drain_survives_file_vanishing_after_post(tmp_path, monkeypatch):
    """A concurrent drain unlinking the file first must not raise."""
    _write_to_outbox([MARKER], "sess-1", str(tmp_path))

    def post_and_steal(path, body=None, idempotency_key=None):
        for f in tmp_path.glob("*.json"):
            f.unlink()
        return {"ok": True}

    monkeypatch.setattr(brain_http, "brain_http_enabled", lambda: True)
    monkeypatch.setattr(brain_http, "post", post_and_steal)
    assert _drain_outbox(str(tmp_path)) == 1
    assert not list(tmp_path.glob("*.json"))


def test_drain_quarantines_unparseable(tmp_path, http_ok):
    (tmp_path / "aa-broken.json").write_text("{not json")
    assert _drain_outbox(str(tmp_path)) == 0
    assert (tmp_path / "aa-broken.json.bad").exists()
    assert not list(tmp_path.glob("*.json"))


def test_drain_keeps_files_on_refusal(tmp_path, monkeypatch):
    monkeypatch.setattr(brain_http, "brain_http_enabled", lambda: True)
    monkeypatch.setattr(brain_http, "post", lambda *a, **k: None)
    _write_to_outbox([MARKER], "sess-1", str(tmp_path))
    assert _drain_outbox(str(tmp_path)) == 0
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_drain_noop_when_http_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(brain_http, "brain_http_enabled", lambda: False)
    _write_to_outbox([MARKER], "sess-1", str(tmp_path))
    assert _drain_outbox(str(tmp_path)) == 0
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_outbox_payload_preserves_original_content(tmp_path, http_ok):
    _write_to_outbox([MARKER], "sess-1", str(tmp_path))
    payload = json.loads(next(iter(tmp_path.glob("*.json"))).read_text())
    assert payload["type"] == MARKER["type"]
    assert payload["content"] == MARKER["content"]
    assert payload["session_id"] == "sess-1"
