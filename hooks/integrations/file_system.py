#!/usr/bin/env python3
"""File system operations for hooks.

╔══════════════════════════════════════════════════════════════════════════════╗
║  SECURITY RESTRICTION: ALL OPERATIONS ARE LIMITED TO /tmp DIRECTORY ONLY     ║
║  Any path outside /tmp will be REJECTED. Path traversal attacks are blocked. ║
╚══════════════════════════════════════════════════════════════════════════════╝

MCP Tool: filesystem_delete
---------------------------
Securely delete files or directories. ONLY paths within /tmp are allowed.

Parameters:
    paths (str | List[str]): Single path or list of paths to delete.
                             ALL paths MUST be inside /tmp.
    force (bool): If True (default), silently skip non-existent paths.

Returns:
    DeleteResult:
        success (bool): True if all deletions succeeded
        deleted_count (int): Number of paths successfully deleted
        deleted_paths (List[str]): Paths that were deleted
        failed_paths (List[str]): Paths that failed to delete
        errors (List[str]): Error messages for failed paths
        error (str | None): Combined error message if any failures

Security:
    - ONLY /tmp paths allowed - anything else is rejected
    - Path traversal attacks blocked (e.g., /tmp/../etc/passwd → REJECTED)
    - Symlinks outside /tmp are rejected after resolution

Usage Examples:
    # Delete single file
    result = delete("/tmp/my_file.txt")

    # Delete directory recursively (like rm -rf)
    result = delete("/tmp/my_folder")

    # Delete multiple paths at once
    result = delete(["/tmp/file1.txt", "/tmp/file2.txt", "/tmp/my_dir"])

    # These will FAIL (security rejection):
    delete("/etc/passwd")           # Outside /tmp
    delete("/tmp/../etc/passwd")    # Path traversal attack
    delete("/home/user/file.txt")   # Outside /tmp

CLI:
    /app/hooks/integrations/file_system.py delete /tmp/file.txt
    /app/hooks/integrations/file_system.py delete /tmp/file1.txt /tmp/dir1
"""

import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union, List

# Add parent directories to path for direct script execution
_script_dir = Path(__file__).resolve().parent
_app_dir = _script_dir.parent.parent  # /app
if str(_app_dir) not in sys.path:
    sys.path.insert(0, str(_app_dir))

from hooks.common import log

# =============================================================================
# CONSTANTS
# =============================================================================

# Security: Only allow deletions within /tmp
ALLOWED_BASE_PATH = "/tmp"

# =============================================================================
# DATA CLASSES
# =============================================================================


@dataclass
class DeleteResult:
    """Result of a filesystem delete operation.

    Attributes:
        success: True if ALL requested deletions succeeded.
                 False if ANY path was rejected or failed.
        deleted_count: Number of paths successfully deleted.
        deleted_paths: List of absolute paths that were deleted.
        failed_paths: List of paths that could not be deleted
                      (security rejection, permission denied, etc).
        errors: Individual error messages for each failed path.
        error: Combined error message (semicolon-separated) or None if success.

    Example:
        >>> result = delete(["/tmp/file1.txt", "/etc/passwd"])
        >>> result.success
        False
        >>> result.deleted_count
        1
        >>> result.deleted_paths
        ['/tmp/file1.txt']
        >>> result.failed_paths
        ['/etc/passwd']
        >>> result.errors
        ['Path must be inside /tmp: /etc/passwd']
    """

    success: bool
    deleted_count: int = 0
    deleted_paths: List[str] = field(default_factory=list)
    failed_paths: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    error: Optional[str] = None


# =============================================================================
# PATH VALIDATION
# =============================================================================


def _is_safe_path(path: str) -> bool:
    """Check if path is within allowed base path (/tmp).

    Resolves the path to its absolute form to prevent path traversal attacks.
    For example, /tmp/../etc/passwd resolves to /etc/passwd and is rejected.

    Args:
        path: Path string to validate (can be relative or absolute)

    Returns:
        True if resolved path is within /tmp, False otherwise
    """
    try:
        # Resolve to absolute path and normalize
        resolved = Path(path).resolve()

        # Check if path starts with /tmp
        # Using os.path.commonpath to handle edge cases like /tmp/../etc
        allowed = Path(ALLOWED_BASE_PATH).resolve()

        # Verify the resolved path is under /tmp
        return str(resolved).startswith(str(allowed) + os.sep) or resolved == allowed
    except (ValueError, OSError):
        return False


def _validate_path(path: str) -> tuple[bool, str]:
    """Validate path for deletion with security checks.

    Performs:
        1. Empty path check
        2. Security check (must be within /tmp)

    Args:
        path: Path string to validate

    Returns:
        tuple[bool, str]: (is_valid, error_message)
            - (True, "") if path is safe to delete
            - (False, "error description") if path is rejected
    """
    if not path:
        return False, "Path cannot be empty"

    if not _is_safe_path(path):
        return False, f"Path must be inside {ALLOWED_BASE_PATH}: {path}"

    return True, ""


# =============================================================================
# CONTEXT DIRECTORY OPERATIONS
# =============================================================================


def set_context_dir(session_id: str) -> tuple[bool, str]:
    """Create a session-specific context directory in /tmp.

    Creates /tmp/<session_id>/ directory for the agent session to use
    as a working space for temporary files, artifacts, etc.

    This function is called automatically on SessionStart hook.

    Args:
        session_id: UUID session identifier from the hook payload.
                    Must be a valid UUID string.

    Returns:
        tuple[bool, str]: (success, path_or_error)
            - (True, "/tmp/<session_id>") if directory created or exists
            - (False, "error message") if creation failed

    Example:
        >>> success, path = set_context_dir("abc123-def456-789")
        >>> success
        True
        >>> path
        '/tmp/abc123-def456-789'

    Security:
        - Directory is created inside /tmp (safe location)
        - Session ID is validated to prevent path traversal
    """
    if not session_id:
        return False, "session_id cannot be empty"

    # Validate session_id doesn't contain path traversal attempts
    if "/" in session_id or "\\" in session_id or ".." in session_id:
        log("Invalid session_id (path traversal attempt)", {"session_id": session_id})
        return False, f"Invalid session_id: {session_id}"

    try:
        context_path = Path(ALLOWED_BASE_PATH) / session_id
        context_path.mkdir(parents=True, exist_ok=True)

        log("Context directory created", {"path": str(context_path), "session_id": session_id})
        return True, str(context_path)

    except PermissionError as e:
        log("Failed to create context directory - permission denied", {"error": str(e)})
        return False, f"Permission denied: {e}"

    except OSError as e:
        log("Failed to create context directory - OS error", {"error": str(e)})
        return False, f"OS error: {e}"

    except Exception as e:
        log("Failed to create context directory", {"error": str(e)})
        return False, str(e)


def get_context_dir(session_id: str) -> Optional[str]:
    """Get the context directory path for a session if it exists.

    Args:
        session_id: UUID session identifier

    Returns:
        str: Path to context directory if it exists, None otherwise

    Example:
        >>> path = get_context_dir("abc123-def456-789")
        >>> path
        '/tmp/abc123-def456-789'
    """
    if not session_id or "/" in session_id or "\\" in session_id or ".." in session_id:
        return None

    context_path = Path(ALLOWED_BASE_PATH) / session_id
    return str(context_path) if context_path.exists() else None


def delete_context_dir(session_id: str) -> tuple[bool, str]:
    """Delete the session-specific context directory from /tmp.

    Removes /tmp/<session_id>/ directory and all its contents.
    This function is called automatically on SessionEnd hook.

    Args:
        session_id: UUID session identifier from the hook payload.

    Returns:
        tuple[bool, str]: (success, message)
            - (True, "deleted") if directory was deleted
            - (True, "not_found") if directory didn't exist (not an error)
            - (False, "error message") if deletion failed

    Example:
        >>> success, msg = delete_context_dir("abc123-def456-789")
        >>> success
        True
        >>> msg
        'deleted'

    Security:
        - Only deletes from /tmp (safe location)
        - Session ID validated to prevent path traversal
    """
    if not session_id:
        return False, "session_id cannot be empty"

    # Validate session_id doesn't contain path traversal attempts
    if "/" in session_id or "\\" in session_id or ".." in session_id:
        log("Invalid session_id (path traversal attempt)", {"session_id": session_id})
        return False, f"Invalid session_id: {session_id}"

    try:
        context_path = Path(ALLOWED_BASE_PATH) / session_id

        if not context_path.exists():
            log("Context directory not found (already cleaned)", {"session_id": session_id})
            return True, "not_found"

        # Delete directory and all contents
        shutil.rmtree(context_path)
        log("Context directory deleted", {"path": str(context_path), "session_id": session_id})
        return True, "deleted"

    except PermissionError as e:
        log("Failed to delete context directory - permission denied", {"error": str(e)})
        return False, f"Permission denied: {e}"

    except OSError as e:
        log("Failed to delete context directory - OS error", {"error": str(e)})
        return False, f"OS error: {e}"

    except Exception as e:
        log("Failed to delete context directory", {"error": str(e)})
        return False, str(e)


# =============================================================================
# DELETE OPERATIONS
# =============================================================================


def delete(paths: Union[str, List[str]], force: bool = True) -> DeleteResult:
    """Delete file(s) or directory(ies) - RESTRICTED TO /tmp ONLY.

    ⚠️  SECURITY: Only paths within /tmp are allowed.
        Any path outside /tmp will be REJECTED.
        Path traversal attacks (e.g., /tmp/../etc) are blocked.

    This function performs:
        - rm (file deletion) for regular files
        - rm -rf (recursive deletion) for directories
        - Batch deletion for multiple paths

    Args:
        paths (str | List[str]): Path(s) to delete. MUST be inside /tmp.
            - Single path: "/tmp/file.txt"
            - Multiple paths: ["/tmp/file1.txt", "/tmp/dir1"]
        force (bool): If True (default), silently skip non-existent paths.
            If False, report non-existent paths as errors.

    Returns:
        DeleteResult: Result object containing:
            - success (bool): True if ALL operations succeeded
            - deleted_count (int): Number of successfully deleted paths
            - deleted_paths (List[str]): Resolved paths that were deleted
            - failed_paths (List[str]): Paths that failed (security/permission/etc)
            - errors (List[str]): Individual error messages
            - error (str | None): Combined error string if any failures

    Raises:
        No exceptions raised - all errors captured in DeleteResult.

    Examples:
        >>> # Delete single file
        >>> result = delete("/tmp/my_file.txt")
        >>> result.success
        True

        >>> # Delete directory recursively (rm -rf equivalent)
        >>> result = delete("/tmp/my_folder")

        >>> # Delete multiple paths
        >>> result = delete(["/tmp/file1.txt", "/tmp/dir1"])

        >>> # REJECTED - outside /tmp
        >>> result = delete("/etc/passwd")
        >>> result.success
        False
        >>> result.errors
        ['Path must be inside /tmp: /etc/passwd']

        >>> # REJECTED - path traversal attack
        >>> result = delete("/tmp/../etc/passwd")
        >>> result.success
        False
    """
    # Normalize input to list
    if isinstance(paths, str):
        paths = [paths]

    result = DeleteResult(success=True)

    log("Starting delete operation", {"paths": paths, "count": len(paths)})

    for path in paths:
        # Validate path
        is_valid, error_msg = _validate_path(path)
        if not is_valid:
            result.failed_paths.append(path)
            result.errors.append(error_msg)
            result.success = False
            log("Path validation failed", {"path": path, "error": error_msg})
            continue

        try:
            resolved_path = Path(path).resolve()

            # Check if path exists
            if not resolved_path.exists():
                if force:
                    # Silently skip non-existent paths in force mode
                    log("Path does not exist (skipped)", {"path": str(resolved_path)})
                    continue
                else:
                    result.failed_paths.append(path)
                    result.errors.append(f"Path does not exist: {path}")
                    result.success = False
                    continue

            # Delete based on type
            if resolved_path.is_file() or resolved_path.is_symlink():
                # Delete file or symlink
                resolved_path.unlink()
                log("Deleted file", {"path": str(resolved_path)})
            elif resolved_path.is_dir():
                # Delete directory recursively (rm -rf)
                shutil.rmtree(resolved_path)
                log("Deleted directory", {"path": str(resolved_path)})
            else:
                # Unknown type
                result.failed_paths.append(path)
                result.errors.append(f"Unknown path type: {path}")
                result.success = False
                continue

            result.deleted_count += 1
            result.deleted_paths.append(str(resolved_path))

        except PermissionError as e:
            result.failed_paths.append(path)
            result.errors.append(f"Permission denied: {path}")
            result.success = False
            log("Delete failed - permission denied", {"path": path, "error": str(e)})

        except OSError as e:
            result.failed_paths.append(path)
            result.errors.append(f"OS error deleting {path}: {e}")
            result.success = False
            log("Delete failed - OS error", {"path": path, "error": str(e)})

        except Exception as e:
            result.failed_paths.append(path)
            result.errors.append(f"Error deleting {path}: {e}")
            result.success = False
            log("Delete failed - unexpected error", {"path": path, "error": str(e)})

    # Set overall error message if there were failures
    if result.errors:
        result.error = "; ".join(result.errors)

    log(
        "Delete operation completed",
        {
            "success": result.success,
            "deleted_count": result.deleted_count,
            "failed_count": len(result.failed_paths),
        },
    )

    return result


# =============================================================================
# CLI INTERFACE
# =============================================================================


def main():
    """CLI entry point for file system operations."""
    import json as json_module

    if len(sys.argv) < 2:
        print("Usage: /app/hooks/integrations/file_system.py <command> [args]")
        print("")
        print("Commands:")
        print("  delete <path> [path2] [path3] ...")
        print("      Delete files or directories (restricted to /tmp)")
        print("")
        print("Security:")
        print(f"  All paths must be within {ALLOWED_BASE_PATH}")
        print("  Paths outside /tmp will be rejected")
        print("")
        print("Examples:")
        print("  # Delete single file")
        print("  /app/hooks/integrations/file_system.py delete /tmp/file.txt")
        print("")
        print("  # Delete multiple paths")
        print("  /app/hooks/integrations/file_system.py delete /tmp/file1.txt /tmp/dir1 /tmp/file2.txt")
        print("")
        print("  # This will FAIL (outside /tmp)")
        print("  /app/hooks/integrations/file_system.py delete /etc/passwd  # REJECTED")
        sys.exit(1)

    command = sys.argv[1]

    if command == "delete":
        if len(sys.argv) < 3:
            print("Error: At least one path is required")
            print("Usage: /app/hooks/integrations/file_system.py delete <path> [path2] ...")
            sys.exit(1)

        paths = sys.argv[2:]

        try:
            result = delete(paths)

            output = {
                "success": result.success,
                "deleted_count": result.deleted_count,
                "deleted_paths": result.deleted_paths,
                "failed_paths": result.failed_paths,
                "errors": result.errors,
            }

            print(json_module.dumps(output, indent=2))
            sys.exit(0 if result.success else 1)

        except Exception as e:
            print(json_module.dumps({"success": False, "error": str(e)}))
            sys.exit(1)

    else:
        print(f"Error: Unknown command '{command}'")
        print("Usage: /app/hooks/integrations/file_system.py <command> [args]")
        sys.exit(1)


if __name__ == "__main__":
    main()
