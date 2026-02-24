"""Tests for hooks.integrations.file_system module."""

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


# =============================================================================
# _is_safe_path()
# =============================================================================


class TestIsSafePath:
    """Test path security validation."""

    def test_tmp_path_is_safe(self):
        from hooks.integrations.file_system import _is_safe_path

        assert _is_safe_path("/tmp/test.txt") is True

    def test_tmp_subdir_is_safe(self):
        from hooks.integrations.file_system import _is_safe_path

        assert _is_safe_path("/tmp/deep/nested/path/file.txt") is True

    def test_etc_is_unsafe(self):
        from hooks.integrations.file_system import _is_safe_path

        assert _is_safe_path("/etc/passwd") is False

    def test_home_is_unsafe(self):
        from hooks.integrations.file_system import _is_safe_path

        assert _is_safe_path("/home/user/file.txt") is False

    def test_path_traversal_blocked(self):
        from hooks.integrations.file_system import _is_safe_path

        assert _is_safe_path("/tmp/../etc/passwd") is False

    def test_root_is_unsafe(self):
        from hooks.integrations.file_system import _is_safe_path

        assert _is_safe_path("/") is False

    def test_empty_path(self):
        from hooks.integrations.file_system import _is_safe_path

        # Empty resolves to cwd which is unlikely under /tmp
        result = _is_safe_path("")
        # Result depends on cwd; just check it doesn't crash
        assert isinstance(result, bool)


# =============================================================================
# _validate_path()
# =============================================================================


class TestValidatePath:
    """Test path validation."""

    def test_valid_tmp_path(self):
        from hooks.integrations.file_system import _validate_path

        valid, msg = _validate_path("/tmp/test.txt")
        assert valid is True
        assert msg == ""

    def test_empty_path_rejected(self):
        from hooks.integrations.file_system import _validate_path

        valid, msg = _validate_path("")
        assert valid is False
        assert "empty" in msg.lower()

    def test_unsafe_path_rejected(self):
        from hooks.integrations.file_system import _validate_path

        valid, msg = _validate_path("/etc/passwd")
        assert valid is False
        assert "/tmp" in msg


# =============================================================================
# delete()
# =============================================================================


class TestDelete:
    """Test the delete() function."""

    def test_delete_file(self, tmp_path):
        from hooks.integrations.file_system import delete

        f = tmp_path / "test.txt"
        f.write_text("content")
        # Since tmp_path is not under /tmp on all systems, we need to use actual /tmp
        import tempfile

        with tempfile.NamedTemporaryFile(dir="/tmp", delete=False, suffix=".txt") as tf:
            tf.write(b"test content")
            tf_path = tf.name

        result = delete(tf_path)
        assert result.success is True
        assert result.deleted_count == 1
        assert not Path(tf_path).exists()

    def test_delete_directory(self):
        import tempfile

        from hooks.integrations.file_system import delete

        d = tempfile.mkdtemp(dir="/tmp", prefix="agentihooks_test_")
        Path(d, "inner.txt").write_text("hello")

        result = delete(d)
        assert result.success is True
        assert result.deleted_count == 1
        assert not Path(d).exists()

    def test_delete_outside_tmp_rejected(self):
        from hooks.integrations.file_system import delete

        result = delete("/etc/passwd")
        assert result.success is False
        assert len(result.failed_paths) == 1
        assert len(result.errors) == 1
        assert result.error is not None

    def test_delete_path_traversal_rejected(self):
        from hooks.integrations.file_system import delete

        result = delete("/tmp/../etc/passwd")
        assert result.success is False

    def test_delete_nonexistent_force_mode(self):
        from hooks.integrations.file_system import delete

        result = delete("/tmp/nonexistent_file_abc123.txt", force=True)
        assert result.success is True
        assert result.deleted_count == 0

    def test_delete_nonexistent_no_force(self):
        from hooks.integrations.file_system import delete

        result = delete("/tmp/nonexistent_file_abc123.txt", force=False)
        assert result.success is False
        assert "does not exist" in result.errors[0]

    def test_delete_multiple_paths(self):
        import tempfile

        from hooks.integrations.file_system import delete

        f1 = tempfile.NamedTemporaryFile(dir="/tmp", delete=False, suffix=".txt")
        f1.write(b"a")
        f1.close()

        f2 = tempfile.NamedTemporaryFile(dir="/tmp", delete=False, suffix=".txt")
        f2.write(b"b")
        f2.close()

        result = delete([f1.name, f2.name])
        assert result.success is True
        assert result.deleted_count == 2

    def test_delete_mixed_valid_invalid(self):
        import tempfile

        from hooks.integrations.file_system import delete

        f = tempfile.NamedTemporaryFile(dir="/tmp", delete=False, suffix=".txt")
        f.write(b"content")
        f.close()

        result = delete([f.name, "/etc/passwd"])
        assert result.success is False
        assert result.deleted_count == 1
        assert len(result.failed_paths) == 1

    def test_delete_string_input(self):
        """delete() accepts a single string path."""
        from hooks.integrations.file_system import delete

        result = delete("/tmp/nonexistent_xyz.txt", force=True)
        assert result.success is True


# =============================================================================
# DeleteResult dataclass
# =============================================================================


class TestDeleteResult:
    """Test DeleteResult dataclass."""

    def test_default_values(self):
        from hooks.integrations.file_system import DeleteResult

        r = DeleteResult(success=True)
        assert r.deleted_count == 0
        assert r.deleted_paths == []
        assert r.failed_paths == []
        assert r.errors == []
        assert r.error is None

    def test_failure_result(self):
        from hooks.integrations.file_system import DeleteResult

        r = DeleteResult(
            success=False,
            failed_paths=["/etc/passwd"],
            errors=["Path must be inside /tmp: /etc/passwd"],
            error="Path must be inside /tmp: /etc/passwd",
        )
        assert r.success is False
        assert len(r.failed_paths) == 1


# =============================================================================
# set_context_dir()
# =============================================================================


class TestSetContextDir:
    """Test set_context_dir() function."""

    def test_create_context_dir(self):
        import uuid

        from hooks.integrations.file_system import set_context_dir

        session_id = f"test-{uuid.uuid4()}"
        success, path = set_context_dir(session_id)
        assert success is True
        assert path == f"/tmp/{session_id}"
        assert Path(path).exists()
        # Cleanup
        Path(path).rmdir()

    def test_empty_session_id(self):
        from hooks.integrations.file_system import set_context_dir

        success, msg = set_context_dir("")
        assert success is False
        assert "empty" in msg.lower()

    def test_path_traversal_session_id(self):
        from hooks.integrations.file_system import set_context_dir

        success, msg = set_context_dir("../etc")
        assert success is False
        assert "Invalid" in msg

    def test_slash_in_session_id(self):
        from hooks.integrations.file_system import set_context_dir

        success, msg = set_context_dir("foo/bar")
        assert success is False

    def test_backslash_in_session_id(self):
        from hooks.integrations.file_system import set_context_dir

        success, msg = set_context_dir("foo\\bar")
        assert success is False


# =============================================================================
# get_context_dir()
# =============================================================================


class TestGetContextDir:
    """Test get_context_dir() function."""

    def test_existing_dir(self):
        import uuid

        from hooks.integrations.file_system import get_context_dir, set_context_dir

        session_id = f"test-{uuid.uuid4()}"
        set_context_dir(session_id)
        result = get_context_dir(session_id)
        assert result == f"/tmp/{session_id}"
        # Cleanup
        Path(result).rmdir()

    def test_nonexistent_dir(self):
        from hooks.integrations.file_system import get_context_dir

        result = get_context_dir("nonexistent-session-id-xyz")
        assert result is None

    def test_empty_session_id(self):
        from hooks.integrations.file_system import get_context_dir

        result = get_context_dir("")
        assert result is None

    def test_invalid_session_id(self):
        from hooks.integrations.file_system import get_context_dir

        result = get_context_dir("../etc")
        assert result is None


# =============================================================================
# delete_context_dir()
# =============================================================================


class TestDeleteContextDir:
    """Test delete_context_dir() function."""

    def test_delete_existing_dir(self):
        import uuid

        from hooks.integrations.file_system import delete_context_dir, set_context_dir

        session_id = f"test-{uuid.uuid4()}"
        set_context_dir(session_id)
        success, msg = delete_context_dir(session_id)
        assert success is True
        assert msg == "deleted"
        assert not Path(f"/tmp/{session_id}").exists()

    def test_delete_nonexistent_dir(self):
        from hooks.integrations.file_system import delete_context_dir

        success, msg = delete_context_dir("nonexistent-session-xyz")
        assert success is True
        assert msg == "not_found"

    def test_delete_empty_session_id(self):
        from hooks.integrations.file_system import delete_context_dir

        success, msg = delete_context_dir("")
        assert success is False

    def test_delete_invalid_session_id(self):
        from hooks.integrations.file_system import delete_context_dir

        success, msg = delete_context_dir("../etc")
        assert success is False
