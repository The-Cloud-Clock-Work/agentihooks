---
title: Storage
nav_order: 7
---

# Storage Tools
{: .no_toc }

The Storage category provides S3 uploads and local filesystem cleanup. Filesystem operations are restricted to `/tmp` for security.

## Table of contents
{: .no_toc .text-delta }

1. TOC
{:toc}

---

## Tools

| Tool | Description |
|------|-------------|
| `storage_upload_path()` | Upload a file or directory to S3 |
| `filesystem_delete()` | Delete local files or directories (restricted to `/tmp`) |

---

## Tool reference

### `storage_upload_path`

```python
storage_upload_path(
    session_id: str,
    path: str,
    prefix: str = "",
    match_uuid: bool = False
) -> str
```

Uploads a file or entire directory to S3 under the key prefix `sessions/<session_id>/`. An optional `prefix` is appended after the session path. When `match_uuid=True`, only uploads files whose names contain a UUID pattern.

**Returns:** JSON with `success` (bool), `s3_url`, `files_uploaded`, `error`

---

### `filesystem_delete`

```python
filesystem_delete(paths: str, force: bool = True) -> str
```

Deletes files or directories. The `paths` argument accepts:
- A single path string
- A JSON array of paths: `'["/tmp/a", "/tmp/b"]'`
- Comma-separated paths: `"/tmp/a,/tmp/b"`

{: .warning }
**Restricted to `/tmp` only.** Any path outside `/tmp` is rejected with an error. This prevents accidental deletion of source code or system files.

**Returns:** JSON with `deleted_count`, `deleted_paths` (list), `failed_paths` (list), `errors`

---

## Notes

### S3 path structure

Uploaded files are stored at:

```
s3://<bucket>/sessions/<session_id>/<prefix>/<filename>
```

The `STORAGE_URL` environment variable determines the bucket and endpoint.

### Why `/tmp` restriction?

Agents frequently work in `/tmp/<session_id>/` directories. The `filesystem_delete` tool is designed for cleanup after uploads or task completion. Restricting to `/tmp` ensures agents cannot accidentally delete repo checkouts, installed packages, or system files.

---

## Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `STORAGE_URL` | Yes | — | S3 URL or endpoint (e.g., `s3://my-bucket`) |
| `IS_EVALUATION` | No | `false` | Evaluation mode flag (skips actual upload) |
