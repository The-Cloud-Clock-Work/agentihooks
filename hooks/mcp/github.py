"""GitHub & Git MCP tools."""

import json

from hooks.common import log


def _validate_clone_target_dir(target_dir: str) -> tuple[bool, str]:
    """Validate target_dir follows /tmp/<uuid>/<repo-name> pattern."""
    from pathlib import Path
    from uuid import UUID

    if not target_dir or not target_dir.strip():
        return False, "target_dir is REQUIRED"

    path = Path(target_dir.strip())
    parts = path.parts

    if len(parts) < 4:
        return False, f"Invalid path structure. Expected /tmp/<uuid>/<repo-name>, got: {target_dir}"

    if parts[0] != "/" or parts[1] != "tmp":
        return False, f"Path must start with /tmp/. Got: {target_dir}"

    try:
        UUID(parts[2])
    except ValueError:
        return False, f"Path must contain UUID after /tmp/. Expected /tmp/<uuid>/<repo>, got invalid UUID: '{parts[2]}'"

    return True, ""


def register(mcp):
    @mcp.tool()
    def github_get_token(force_refresh: bool = False) -> str:
        """Get a valid GitHub installation access token.

        Tokens are cached and auto-refreshed. Uses GitHub App authentication
        with credentials from AWS Secrets Manager.

        Args:
            force_refresh: Force token regeneration even if cached token is valid

        Returns:
            JSON with token and expiration info, or error
        """
        try:
            from hooks.integrations.github import GitHubAuth

            token = GitHubAuth.get_token(force_refresh=force_refresh)

            return json.dumps(
                {
                    "success": True,
                    "token": token,
                    "expires_at": GitHubAuth._token_expires_at.isoformat() if GitHubAuth._token_expires_at else None,
                }
            )

        except Exception as e:
            log("MCP github_get_token failed", {"error": str(e)})
            return json.dumps({"success": False, "error": str(e)})

    @mcp.tool()
    def github_clone_repo(
        url: str,
        target_dir: str,
        depth: int = 1,
    ) -> str:
        """Clone a git repository with token authentication.

        If the repository already exists at target_dir, pulls latest changes instead.

        Args:
            url: Git repository URL (HTTPS or SSH format)
            target_dir: REQUIRED. Path must follow pattern: /tmp/<uuid>/<repo-name>
                        The UUID identifies the session/context for isolation.
                        Example: /tmp/550e8400-e29b-41d4-a716-446655440000/my-repo
                        NO DEFAULT - caller MUST provide this path explicitly.
            depth: Clone depth (default: 1 for shallow clone, 0 for full)

        Returns:
            JSON with path, status (cloned/updated), and repo_name
        """
        try:
            from hooks.integrations.github import GitHubAuth, clone_repo

            GitHubAuth.get_token()

            is_valid, error_msg = _validate_clone_target_dir(target_dir)
            if not is_valid:
                return json.dumps(
                    {
                        "success": False,
                        "error": f"{error_msg}. Example: /tmp/550e8400-e29b-41d4-a716-446655440000/my-repo",
                    }
                )

            result = clone_repo(
                url=url,
                target_dir=target_dir,
                depth=depth,
            )

            return json.dumps(
                {
                    "success": True,
                    "path": result.path,
                    "status": result.status,
                    "repo_name": result.repo_name,
                }
            )

        except Exception as e:
            log("MCP github_clone_repo failed", {"url": url, "error": str(e)})
            return json.dumps({"success": False, "error": str(e)})

    @mcp.tool()
    def github_create_pr(
        repo_path: str,
        title: str,
        body: str,
        branch_prefix: str,
        files_to_stage: str = "",
        commit_message: str = "",
    ) -> str:
        """Create a pull request for changes in a repository.

        Stages files, commits, pushes to a new branch, and creates a PR.

        Args:
            repo_path: Path to the git repository
            title: PR title
            body: PR body (markdown)
            branch_prefix: Branch name prefix (timestamp will be appended)
            files_to_stage: Comma-separated files to stage or list (default: all changes)
            commit_message: Commit message (default: derived from title)

        Returns:
            JSON with PR url, branch, title, and repo
        """
        try:
            from hooks.integrations.github import GitHubAuth, create_pr

            GitHubAuth.get_token()

            if isinstance(files_to_stage, list):
                files = [f.strip() for f in files_to_stage if f.strip()]
            elif files_to_stage:
                files = [f.strip() for f in files_to_stage.split(",") if f.strip()]
            else:
                files = None

            result = create_pr(
                repo_path=repo_path,
                title=title,
                body=body,
                branch_prefix=branch_prefix,
                files_to_stage=files,
                commit_message=commit_message if commit_message else None,
            )

            return json.dumps(
                {
                    "success": True,
                    "url": result.url,
                    "branch": result.branch,
                    "title": result.title,
                    "repo": result.repo,
                }
            )

        except Exception as e:
            log("MCP github_create_pr failed", {"repo_path": repo_path, "error": str(e)})
            return json.dumps({"success": False, "error": str(e)})

    @mcp.tool()
    def github_get_repo_info(url: str) -> str:
        """Parse a git URL to extract org and repo name.

        Supports SSH (git@github.com:org/repo.git) and HTTPS formats.

        Args:
            url: Git repository URL

        Returns:
            JSON with org, name, and full_name (org/name)
        """
        try:
            from hooks.integrations.github import GitOperations

            info = GitOperations.parse_repo_url(url)

            return json.dumps(
                {
                    "success": True,
                    "org": info.org,
                    "name": info.name,
                    "full_name": info.full_name,
                }
            )

        except Exception as e:
            log("MCP github_get_repo_info failed", {"url": url, "error": str(e)})
            return json.dumps({"success": False, "error": str(e)})

    @mcp.tool()
    def git_summary(repo_path: str, num_commits: int = 10) -> str:
        """Get commit history and diff stats for a repository.

        Args:
            repo_path: Path to the git repository
            num_commits: Number of commits to include (default: 10)

        Returns:
            Text summary of commits and file changes
        """
        try:
            from hooks.integrations.git_diff import get_git_summary

            result = get_git_summary(repo_path, num_commits)
            return result

        except Exception as e:
            log("MCP git_summary failed", {"repo_path": repo_path, "error": str(e)})
            return f"Error: {e}"
