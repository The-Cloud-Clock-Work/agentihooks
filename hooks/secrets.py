"""Secrets detection and redaction for Claude Code hooks.

Scans text for credential patterns and redacts them to prevent
secrets from appearing in logs or being processed by Claude.
"""

import re
from typing import NamedTuple


class _Pattern(NamedTuple):
    name: str
    regex: re.Pattern


_NOSECRET_RE = re.compile(r"#\s*nosecret\b", re.IGNORECASE)

_PATTERNS: list[_Pattern] = [
    _Pattern(
        "aws_access_key",
        re.compile(r"(AKIA|ASIA|AROA|AIPA)[A-Z0-9]{16}"),
    ),
    _Pattern(
        "aws_secret_key",
        re.compile(r"aws_secret_access_key\s*[=:]\s*[A-Za-z0-9+/]{40}", re.IGNORECASE),
    ),
    _Pattern(
        "github_token",
        re.compile(r"gh[ps]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{82}"),
    ),
    _Pattern(
        "private_key",
        re.compile(r"-----BEGIN\s+(RSA|EC|OPENSSH|PGP)\s+PRIVATE KEY-----"),
    ),
    _Pattern(
        "bearer_token",
        re.compile(r"Authorization:\s*Bearer\s+[A-Za-z0-9._\-+/]{20,}", re.IGNORECASE),
    ),
    _Pattern(
        "db_url_creds",
        re.compile(r"(postgres|mysql|mongodb)://[^:]+:[^@]{4,}@", re.IGNORECASE),
    ),
    _Pattern(
        "generic_secret",
        # Match KEY = VALUE but skip env var references ($VAR) and placeholders (<...> or {...})
        re.compile(
            r"(?:PASSWORD|SECRET|API_KEY|PRIVATE_KEY|ACCESS_TOKEN)\s*[=:]\s*(?!\$)(?!<)(?!\{)[^\s$<{]{8,}",
            re.IGNORECASE,
        ),
    ),
]


def scan(text: str) -> list[str]:
    """Return list of matched pattern names found in text.

    Lines containing '# nosecret' (case-insensitive) are excluded from scanning,
    allowing intentional suppression of known-safe patterns (e.g. docs, tests).
    """
    # Strip suppressed lines before pattern matching
    filtered = "".join(
        line
        for line in text.splitlines(keepends=True)
        if not _NOSECRET_RE.search(line)
    )
    hits: list[str] = []
    for pattern in _PATTERNS:
        if pattern.regex.search(filtered):
            hits.append(pattern.name)
    return hits


def redact(text: str) -> str:
    """Replace detected secrets with [REDACTED:<name>]."""
    for pattern in _PATTERNS:
        text = pattern.regex.sub(f"[REDACTED:{pattern.name}]", text)
    return text
