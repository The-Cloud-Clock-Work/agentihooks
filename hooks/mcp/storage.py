"""S3 storage & filesystem MCP tools."""

import json

from hooks.common import log


def register(mcp):
    @mcp.tool()
    def storage_upload_path(
        session_id: str,
        path: str,
        prefix: str = "",
        match_uuid: bool = False,
    ) -> str:
        """Upload a local path to S3 storage with session prefix.

        Uploads file or directory to S3 under sessions/<session_id>/ or custom prefix.

        Args:
            session_id: Session ID for S3 prefix
            path: Local file or directory path to upload
            prefix: S3 key prefix (default: sessions/<session_id>/)
            match_uuid: If True, extract UUID from filename and use as prefix (default: False)

        Returns:
            JSON with success status, s3_url, uploaded file count
        """
        try:
            from hooks.integrations.storage import upload_path

            result = upload_path(
                session_id,
                path=path,
                prefix=prefix if prefix else None,
                match_uuid=match_uuid,
            )

            return json.dumps({
                "success": result.success,
                "s3_url": result.s3_url,
                "files_uploaded": result.files_uploaded,
                "error": result.error,
            })

        except Exception as e:
            log("MCP storage_upload_path failed", {"path": path, "error": str(e)})
            return json.dumps({"success": False, "error": str(e)})

    @mcp.tool()
    def filesystem_delete(
        paths: str,
        force: bool = True,
    ) -> str:
        """Delete files or directories - RESTRICTED TO /tmp ONLY.

        Operations:
            - Single file: rm equivalent
            - Directory: rm -rf equivalent (recursive deletion)
            - Multiple paths: Batch deletion

        Args:
            paths: Path(s) to delete. MUST be inside /tmp.
                   - Single path: "/tmp/file.txt"
                   - Multiple paths (JSON array): '[\"/tmp/file1.txt\", \"/tmp/dir1\"]'
                   - Comma-separated: "/tmp/file1.txt,/tmp/dir1"
            force: If True (default), silently skip non-existent paths.
                   If False, report non-existent paths as errors.

        Returns:
            JSON with deleted_count, deleted_paths, failed_paths, errors
        """
        try:
            from hooks.integrations.file_system import delete

            path_list: list[str] = []

            if paths.strip().startswith("["):
                try:
                    path_list = json.loads(paths)
                except json.JSONDecodeError:
                    pass

            if not path_list:
                path_list = [p.strip() for p in paths.split(",") if p.strip()]

            result = delete(path_list, force=force)

            return json.dumps({
                "success": result.success,
                "deleted_count": result.deleted_count,
                "deleted_paths": result.deleted_paths,
                "failed_paths": result.failed_paths,
                "errors": result.errors,
            })

        except Exception as e:
            log("MCP filesystem_delete failed", {"paths": paths, "error": str(e)})
            return json.dumps({"success": False, "error": str(e)})
