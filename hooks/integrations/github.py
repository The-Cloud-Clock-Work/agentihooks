"""GitHub integration: App authentication + git operations.

Provides centralized GitHub token management and git operations.

Authentication Methods (priority order):
    1. GITHUB_TOKEN (environment variable) - Simple token-based auth
    2. GitHub App (environment variables) - Advanced installation token auth

Environment Variables:
    GITHUB_TOKEN: Personal access token (optional, bypasses GitHub App if set)
    GITHUB_APP_ID: GitHub App ID (required for App auth)
    GITHUB_INSTALLATION_ID: Installation ID (required for App auth)
    GITHUB_SECRET_ID: AWS Secrets Manager secret ID (required for App auth)
    GITHUB_API_BASE: GitHub API base URL (default: https://api.github.com)
    GITHUB_TOKEN_REFRESH_BUFFER: Token refresh buffer in seconds (default: 300)
    GITHUB_JWT_EXPIRY: JWT expiry in seconds (default: 600)

Note: Clone operations require an explicit target_dir. No default path is used.

Usage:
    from hooks.integrations.github import GitHubAuth, GitOperations

    # Authentication (automatic method selection)
    token = GitHubAuth.get_token()
    url = GitHubAuth.embed_in_url("https://github.com/org/repo.git")

    # Git operations
    path = GitOperations.clone_repo("https://github.com/org/repo.git")
    pr_url = GitOperations.create_pr("/path/to/repo", "PR Title", "PR Body")

    # Decorator usage (sets os.environ["GITHUB_TOKEN"])
    @requires_github_token
    def my_git_operation():
        pass
"""

import os
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Callable, TypeVar

import boto3
import jwt
import requests

from hooks.common import log

# =============================================================================
# CONFIGURATION
# =============================================================================

# GitHub Authentication Configuration (loaded from environment)
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_APP_ID = os.getenv("GITHUB_APP_ID", "")
GITHUB_INSTALLATION_ID = os.getenv("GITHUB_INSTALLATION_ID", "")
GITHUB_SECRET_ID = os.getenv("GITHUB_SECRET_ID", "")
GITHUB_API_BASE = os.getenv("GITHUB_API_BASE", "https://api.github.com")

# Token refresh buffer (refresh 5 minutes before expiry)
TOKEN_REFRESH_BUFFER_SECONDS = int(os.getenv("GITHUB_TOKEN_REFRESH_BUFFER", "300"))

# JWT validity (GitHub allows max 10 minutes)
JWT_EXPIRY_SECONDS = int(os.getenv("GITHUB_JWT_EXPIRY", "600"))


# =============================================================================
# DATA CLASSES
# =============================================================================


@dataclass
class CloneResult:
    """Result of a clone operation."""

    path: str
    status: str  # "cloned" or "updated"
    repo_name: str


@dataclass
class PRResult:
    """Result of a PR creation."""

    url: str
    branch: str
    title: str
    repo: str


@dataclass
class RepoInfo:
    """Parsed repository information."""

    org: str
    name: str
    full_name: str  # org/name


# =============================================================================
# GITHUB AUTH CLASS
# =============================================================================


class GitHubAuth:
    """Centralized GitHub App token management with caching."""

    _token: str | None = None
    _token_expires_at: datetime | None = None
    _pem_key: str | None = None

    @classmethod
    def get_token(cls, force_refresh: bool = False) -> str:
        """
        Get a valid GitHub token.

        Priority:
            1. GITHUB_TOKEN from environment (if set, bypasses GitHub App)
            2. GitHub App authentication (generates installation token)

        Args:
            force_refresh: Force token regeneration (only applies to GitHub App flow)

        Returns:
            Valid GitHub token

        Raises:
            RuntimeError: If token is unavailable and GitHub App config is incomplete
        """
        # PRIORITY 1: Use GITHUB_TOKEN if provided in environment
        if GITHUB_TOKEN and GITHUB_TOKEN.strip():
            log("GitHubAuth: Using GITHUB_TOKEN from environment")
            os.environ["GITHUB_TOKEN"] = GITHUB_TOKEN
            return GITHUB_TOKEN

        # PRIORITY 2: Use GitHub App authentication
        if not force_refresh and cls._is_token_valid():
            return cls._token

        log("GitHubAuth: Generating new token via GitHub App")

        # Validate GitHub App configuration
        if not GITHUB_APP_ID or not GITHUB_INSTALLATION_ID or not GITHUB_SECRET_ID:
            raise RuntimeError(
                "GitHub App authentication requires GITHUB_APP_ID, "
                "GITHUB_INSTALLATION_ID, and GITHUB_SECRET_ID environment variables. "
                "Alternatively, provide GITHUB_TOKEN for simple token-based auth."
            )

        try:
            pem_key = cls._get_pem_key()
            jwt_token = cls._generate_jwt(pem_key)
            token, expires_at = cls._exchange_for_token(jwt_token)

            cls._token = token
            cls._token_expires_at = expires_at
            os.environ["GITHUB_TOKEN"] = token

            log(
                "GitHubAuth: Token generated successfully",
                {"expires_at": expires_at.isoformat()},
            )

            return token

        except Exception as e:
            log("GitHubAuth: Token generation failed", {"error": str(e)})
            raise RuntimeError(f"Failed to generate GitHub token: {e}") from e

    @classmethod
    def embed_in_url(cls, url: str) -> str:
        """
        Embed authentication token in a git URL.

        Converts:
            https://github.com/org/repo.git → https://x-access-token:TOKEN@github.com/org/repo.git
            git@github.com:org/repo.git → https://x-access-token:TOKEN@github.com/org/repo.git

        Args:
            url: Git repository URL (HTTPS or SSH format)

        Returns:
            URL with embedded access token
        """
        token = cls.get_token()

        if url.startswith("https://"):
            # Handle URLs that already have a token
            if "@" in url.split("//")[1].split("/")[0]:
                # Already has credentials, replace them
                url = re.sub(r"https://[^@]+@", "https://", url)
            return url.replace("https://", f"https://x-access-token:{token}@")

        elif url.startswith("git@"):
            # Convert SSH to HTTPS with token
            # git@github.com:org/repo.git -> https://x-access-token:TOKEN@github.com/org/repo.git
            match = re.match(r"git@([^:]+):(.+)", url)
            if match:
                host, path = match.groups()
                return f"https://x-access-token:{token}@{host}/{path}"

        log("GitHubAuth: Unknown URL format", {"url": url})
        return url

    @classmethod
    def clear_cache(cls) -> None:
        """Clear cached token and PEM key."""
        cls._token = None
        cls._token_expires_at = None
        cls._pem_key = None
        if "GITHUB_TOKEN" in os.environ:
            del os.environ["GITHUB_TOKEN"]
        log("GitHubAuth: Cache cleared")

    @classmethod
    def _is_token_valid(cls) -> bool:
        """Check if cached token is still valid (with buffer)."""
        if cls._token is None or cls._token_expires_at is None:
            return False

        now = datetime.now(timezone.utc)
        buffer = TOKEN_REFRESH_BUFFER_SECONDS
        expires_with_buffer = cls._token_expires_at.timestamp() - buffer

        return now.timestamp() < expires_with_buffer

    @classmethod
    def _get_pem_key(cls) -> str:
        """Fetch GitHub App private key from Secrets Manager (cached)."""
        if cls._pem_key is not None:
            return cls._pem_key

        log("GitHubAuth: Fetching PEM key from Secrets Manager")

        try:
            secrets_client = boto3.client("secretsmanager")
            response = secrets_client.get_secret_value(SecretId=GITHUB_SECRET_ID)
            cls._pem_key = response["SecretString"]
            return cls._pem_key

        except Exception as e:
            raise RuntimeError(f"Failed to fetch PEM key from Secrets Manager: {e}") from e

    @classmethod
    def _generate_jwt(cls, pem_key: str) -> str:
        """Generate a signed JWT for GitHub App authentication.

        Sets iat (issued at) 60 seconds in the past to account for clock skew
        and network latency. GitHub rejects JWTs with iat in the future.
        """
        now = int(time.time())

        payload = {
            "iat": now - 60,  # 60 seconds in the past for clock skew tolerance
            "exp": now + (JWT_EXPIRY_SECONDS - 60),  # Maintain 10-minute lifetime
            "iss": int(GITHUB_APP_ID),
        }

        return jwt.encode(payload, pem_key, algorithm="RS256")

    @classmethod
    def _exchange_for_token(cls, jwt_token: str) -> tuple[str, datetime]:
        """Exchange JWT for an installation access token."""
        url = f"{GITHUB_API_BASE}/app/installations/{GITHUB_INSTALLATION_ID}/access_tokens"

        response = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {jwt_token}",
                "Accept": "application/vnd.github.v3+json",
            },
            timeout=30,
        )

        if response.status_code != 201:
            raise RuntimeError(f"GitHub API error: {response.status_code} - {response.text}")

        data = response.json()
        token = data["token"]

        expires_at_str = data.get("expires_at")
        if expires_at_str:
            expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
        else:
            expires_at = datetime.now(timezone.utc).replace(hour=datetime.now(timezone.utc).hour + 1)

        return token, expires_at


# =============================================================================
# GIT OPERATIONS CLASS
# =============================================================================


class GitOperations:
    """Git operations with automatic token authentication."""

    @classmethod
    def parse_repo_url(cls, url: str) -> RepoInfo:
        """
        Parse a git URL to extract org and repo name.

        Supports:
            - SSH: git@github.com:org/repo.git
            - HTTPS: https://github.com/org/repo.git
            - HTTPS with token: https://token@github.com/org/repo.git

        Args:
            url: Git repository URL

        Returns:
            RepoInfo with org, name, and full_name

        Raises:
            ValueError: If URL format is not recognized
        """
        url = url.rstrip("/").removesuffix(".git")

        # SSH format: git@github.com:org/repo
        ssh_match = re.match(r"git@[^:]+:([^/]+)/(.+)", url)
        if ssh_match:
            org, name = ssh_match.groups()
            return RepoInfo(org=org, name=name, full_name=f"{org}/{name}")

        # HTTPS format: https://[token@]github.com/org/repo
        https_match = re.match(r"https://(?:[^@]+@)?[^/]+/([^/]+)/(.+)", url)
        if https_match:
            org, name = https_match.groups()
            return RepoInfo(org=org, name=name, full_name=f"{org}/{name}")

        raise ValueError(f"Could not parse git URL: {url}")

    @classmethod
    def validate_url(cls, url: str) -> bool:
        """Validate git URL format."""
        ssh_pattern = r"^git@.+:.+$"
        https_pattern = r"^https?://.+/.+$"
        return bool(re.match(ssh_pattern, url) or re.match(https_pattern, url))

    @classmethod
    def detect_base_branch(cls, repo_path: str) -> str:
        """
        Detect the base branch (main or master) for a repository.

        Args:
            repo_path: Path to the git repository

        Returns:
            "main" or "master"
        """
        try:
            result = subprocess.run(
                [
                    "git",
                    "-C",
                    repo_path,
                    "show-ref",
                    "--verify",
                    "--quiet",
                    "refs/remotes/origin/master",
                ],
                capture_output=True,
            )
            if result.returncode == 0:
                return "master"
        except Exception:  # NOSONAR — hooks must never crash the parent process
            pass

        return "main"

    @classmethod
    def clone_repo(
        cls,
        url: str,
        target_dir: str,
        depth: int = 1,
    ) -> CloneResult:
        """
        Clone a git repository with token authentication.

        If the repository already exists, pulls latest changes instead.

        Args:
            url: Git repository URL
            target_dir: REQUIRED. Target directory for clone (e.g., /tmp/my-session/repo-name).
                        Must be an absolute path. No default is provided.
            depth: Clone depth (default: 1 for shallow clone)

        Returns:
            CloneResult with path, status, and repo_name

        Raises:
            ValueError: If URL is invalid or target_dir is empty
            RuntimeError: If clone fails
        """
        if not cls.validate_url(url):
            raise ValueError(f"Invalid git URL format: {url}")

        if not target_dir or not target_dir.strip():
            raise ValueError("target_dir is required and cannot be empty")

        repo_info = cls.parse_repo_url(url)
        repo_name = f"{repo_info.org}-{repo_info.name}"

        target_path = Path(target_dir)

        # Check if already cloned
        if (target_path / ".git").exists():
            log("GitOperations: Repository exists, pulling latest", {"path": target_dir})

            try:
                # Get authenticated URL for fetch operations
                result = subprocess.run(
                    ["git", "-C", target_dir, "config", "--get", "remote.origin.url"],
                    capture_output=True,
                    text=True,
                )
                remote_url = result.stdout.strip() if result.returncode == 0 else url
                auth_url = GitHubAuth.embed_in_url(remote_url)

                # Fetch with authentication
                env = os.environ.copy()
                env["GIT_TERMINAL_PROMPT"] = "0"

                subprocess.run(
                    ["git", "-C", target_dir, "fetch", auth_url, "--quiet"],
                    capture_output=True,
                    check=True,
                    env=env,
                )
                subprocess.run(
                    ["git", "-C", target_dir, "pull", "--quiet"],
                    capture_output=True,
                    env=env,
                )
            except subprocess.CalledProcessError:
                log("GitOperations: Pull failed (might be on detached HEAD)")

            return CloneResult(path=target_dir, status="updated", repo_name=repo_name)

        # Create parent directory
        target_path.parent.mkdir(parents=True, exist_ok=True)

        # Clone with token
        clone_url = GitHubAuth.embed_in_url(url)

        log("GitOperations: Cloning repository", {"url": url, "target": target_dir})

        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"

        try:
            cmd = ["git", "clone"]
            if depth > 0:
                cmd.extend(["--depth", str(depth)])
            cmd.extend([clone_url, target_dir])

            subprocess.run(cmd, capture_output=True, check=True, env=env)

            log("GitOperations: Clone successful", {"path": target_dir})
            return CloneResult(path=target_dir, status="cloned", repo_name=repo_name)

        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.decode() if e.stderr else str(e)
            log("GitOperations: Clone failed", {"error": error_msg})
            raise RuntimeError(f"Clone failed: {error_msg}") from e

    @classmethod
    def create_pr(
        cls,
        repo_path: str,
        title: str,
        body: str,
        branch_prefix: str,
        files_to_stage: list[str] | None = None,
        commit_message: str | None = None,
    ) -> PRResult:
        """
        Create a pull request for changes in a repository.

        Args:
            repo_path: Path to the git repository
            title: PR title
            body: PR body (markdown)
            branch_prefix: Branch name prefix (timestamp will be appended)
            files_to_stage: Files to stage (default: all changes)
            commit_message: Commit message (default: derived from title)

        Returns:
            PRResult with url, branch, title, and repo

        Raises:
            RuntimeError: If PR creation fails
        """
        repo_path = str(Path(repo_path).resolve())

        if not Path(repo_path, ".git").exists():
            raise ValueError(f"Not a git repository: {repo_path}")

        # Get repo info from remote
        result = subprocess.run(
            ["git", "-C", repo_path, "config", "--get", "remote.origin.url"],
            capture_output=True,
            text=True,
            check=True,
        )
        remote_url = result.stdout.strip()
        repo_info = cls.parse_repo_url(remote_url)

        # Generate branch name
        timestamp = datetime.now().strftime("%m%d%Y-%H%M")
        branch = f"{branch_prefix}-{timestamp}"

        # Detect base branch
        base_branch = cls.detect_base_branch(repo_path)

        log(
            "GitOperations: Creating PR",
            {
                "repo": repo_info.full_name,
                "branch": branch,
                "base": base_branch,
            },
        )

        # Configure git identity
        subprocess.run(
            ["git", "-C", repo_path, "config", "user.name", "Agenticore Agent"],
            capture_output=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                repo_path,
                "config",
                "user.email",
                "agent@agenticore.com",
            ],
            capture_output=True,
        )

        # Create and checkout branch
        subprocess.run(
            ["git", "-C", repo_path, "checkout", "-b", branch],
            capture_output=True,
            check=True,
        )

        # Stage files
        if files_to_stage:
            for file in files_to_stage:
                subprocess.run(
                    ["git", "-C", repo_path, "add", file],
                    capture_output=True,
                    check=True,
                )
        else:
            subprocess.run(
                ["git", "-C", repo_path, "add", "-A"],
                capture_output=True,
                check=True,
            )

        # Check for changes
        result = subprocess.run(
            ["git", "-C", repo_path, "diff", "--cached", "--quiet"],
            capture_output=True,
        )
        if result.returncode == 0:
            raise RuntimeError("No changes to commit")

        # Commit
        commit_msg = commit_message or f"docs: {title}"
        subprocess.run(
            ["git", "-C", repo_path, "commit", "-m", commit_msg],
            capture_output=True,
            check=True,
        )

        # Push with token
        push_url = GitHubAuth.embed_in_url(remote_url)
        subprocess.run(
            ["git", "-C", repo_path, "push", "-u", push_url, branch],
            capture_output=True,
            check=True,
        )

        # Create PR using gh CLI
        result = subprocess.run(
            [
                "gh",
                "pr",
                "create",
                "--title",
                title,
                "--body",
                body,
                "--base",
                base_branch,
                "--head",
                branch,
                "--repo",
                repo_info.full_name,
            ],
            capture_output=True,
            text=True,
            cwd=repo_path,
        )

        if result.returncode != 0:
            error_msg = result.stderr or result.stdout
            log("GitOperations: PR creation failed", {"error": error_msg})
            raise RuntimeError(f"PR creation failed: {error_msg}")

        # Get PR URL
        pr_url = result.stdout.strip()

        log("GitOperations: PR created successfully", {"url": pr_url})

        return PRResult(
            url=pr_url,
            branch=branch,
            title=title,
            repo=repo_info.full_name,
        )


# =============================================================================
# DECORATOR
# =============================================================================

F = TypeVar("F", bound=Callable)


def requires_github_token(func: F) -> F:
    """
    Decorator that ensures a valid GitHub token is available in os.environ.

    Before calling the decorated function, this will:
    1. Check if a valid cached token exists
    2. Generate a new token if needed
    3. Set os.environ["GITHUB_TOKEN"]

    Usage:
        @requires_github_token
        def clone_repository(url: str):
            # GITHUB_TOKEN is now available
            token = os.environ["GITHUB_TOKEN"]
            ...
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        GitHubAuth.get_token()
        return func(*args, **kwargs)

    return wrapper  # type: ignore


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def get_github_token(force_refresh: bool = False) -> str:
    """Convenience function to get GitHub token."""
    return GitHubAuth.get_token(force_refresh=force_refresh)


def embed_token_in_url(url: str) -> str:
    """Convenience function to embed token in URL."""
    return GitHubAuth.embed_in_url(url)


def clone_repo(
    url: str,
    target_dir: str,
    depth: int = 1,
) -> CloneResult:
    """Convenience function to clone a repository. target_dir is REQUIRED."""
    return GitOperations.clone_repo(url, target_dir, depth)


def create_pr(
    repo_path: str,
    title: str,
    body: str,
    **kwargs,
) -> PRResult:
    """Convenience function to create a PR."""
    return GitOperations.create_pr(repo_path, title, body, **kwargs)
