---
title: GitHub
nav_order: 2
---

# GitHub Tools
{: .no_toc }

The GitHub category provides token management, repository operations, and pull request creation. It supports two authentication modes: **Personal Access Token** (simple) and **GitHub App** (production, rotating tokens via AWS Secrets Manager).

## Table of contents
{: .no_toc .text-delta }

1. TOC
{:toc}

---

## Tools

| Tool | Description |
|------|-------------|
| `github_get_token()` | Get GitHub installation access token (cached, auto-refreshes) |
| `github_clone_repo()` | Clone or pull a repository with token auth |
| `github_create_pr()` | Stage files, commit, push, and open a pull request |
| `github_get_repo_info()` | Parse a git URL to extract org and repo name |
| `git_summary()` | Get commit history and diff statistics |

---

## Tool reference

### `github_get_token`

```python
github_get_token(force_refresh: bool = False) -> str
```

Returns a valid GitHub token. If using GitHub App auth, generates a JWT, exchanges it for an installation token via the GitHub API, and caches it with a refresh buffer. Falls back to `GITHUB_TOKEN` if App credentials are not configured.

**Returns:** JSON with `token`, `expiration_at`

---

### `github_clone_repo`

```python
github_clone_repo(url: str, target_dir: str, depth: int = 1) -> str
```

Clones the repository or runs `git pull` if it already exists. Injects the token into the remote URL for authentication.

{: .important }
`target_dir` must follow the pattern `/tmp/<uuid>/<repo-name>` for session isolation.

**Returns:** JSON with `path`, `status` (`cloned` or `updated`), `repo_name`

---

### `github_create_pr`

```python
github_create_pr(
    repo_path: str,
    title: str,
    body: str,
    branch_prefix: str,
    files_to_stage: str = "",
    commit_message: str = ""
) -> str
```

Full PR workflow in one call: stages specified files (or all changes), commits, creates a new branch (`<branch_prefix>/<timestamp>`), pushes, and opens a pull request via the GitHub API.

**Returns:** JSON with `url`, `branch`, `title`, `repo`

---

### `github_get_repo_info`

```python
github_get_repo_info(url: str) -> str
```

Parses SSH (`git@github.com:org/repo.git`) or HTTPS (`https://github.com/org/repo`) URLs.

**Returns:** JSON with `org`, `name`, `full_name`

---

### `git_summary`

```python
git_summary(repo_path: str, num_commits: int = 10) -> str
```

Returns a human-readable summary of recent commits and file change statistics.

**Returns:** plain text summary

---

## Authentication modes

### Mode 1: Personal Access Token (PAT)

Set `GITHUB_TOKEN` and nothing else. Every call uses this token directly.

### Mode 2: GitHub App (recommended for production)

Requires all four App variables. The tool:
1. Fetches the private key from AWS Secrets Manager (`GITHUB_SECRET_ID`)
2. Signs a JWT (`GITHUB_APP_ID`, expires in `GITHUB_JWT_EXPIRY` seconds)
3. Exchanges the JWT for an installation access token (`GITHUB_INSTALLATION_ID`)
4. Caches the token and refreshes it `GITHUB_TOKEN_REFRESH_BUFFER` seconds before expiry

---

## Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GITHUB_TOKEN` | PAT only | — | Personal access token |
| `GITHUB_APP_ID` | App only | — | GitHub App ID |
| `GITHUB_INSTALLATION_ID` | App only | — | GitHub App installation ID |
| `GITHUB_SECRET_ID` | App only | — | AWS Secrets Manager secret ID for the App private key |
| `GITHUB_API_BASE` | No | `https://api.github.com` | API base URL (for GitHub Enterprise) |
| `GITHUB_TOKEN_REFRESH_BUFFER` | No | `300` | Seconds before expiry to refresh token |
| `GITHUB_JWT_EXPIRY` | No | `600` | JWT lifetime in seconds |
