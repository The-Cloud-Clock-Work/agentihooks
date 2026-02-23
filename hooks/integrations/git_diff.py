"""Git diff summary for a repository."""
import subprocess


def get_git_summary(repo_path: str, num_commits: int = 10) -> str:
    """
    Get commit history and diff stats for a repo.

    Args:
        repo_path: Path to the git repository
        num_commits: Number of commits to include (default 10)

    Returns:
        Text summary of commits and changes
    """
    try:
        # Get commit log
        log_cmd = [
            "git", "-C", repo_path, "log",
            f"-{num_commits}",
            "--pretty=format:%h | %ad | %s",
            "--date=short"
        ]
        log_result = subprocess.run(log_cmd, capture_output=True, text=True, timeout=30)

        if log_result.returncode != 0:
            return f"Error: {log_result.stderr.strip()}"

        commits = log_result.stdout.strip()

        # Get diff stats for those commits
        stats_cmd = [
            "git", "-C", repo_path, "diff",
            "--stat",
            f"HEAD~{num_commits}..HEAD"
        ]
        stats_result = subprocess.run(stats_cmd, capture_output=True, text=True, timeout=30)
        stats = stats_result.stdout.strip() if stats_result.returncode == 0 else ""

        # Build output
        output = f"=== Last {num_commits} Commits ===\n{commits}"
        if stats:
            output += f"\n\n=== Changes ===\n{stats}"

        return output

    except subprocess.TimeoutExpired:
        return "Error: Git command timed out"
    except Exception as e:
        return f"Error: {e}"
