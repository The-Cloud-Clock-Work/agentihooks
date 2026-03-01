"""Tests for hooks.secrets module.

All secret-like test strings are assembled inside each test function so
the source file itself does not match any detection pattern.
"""

import pytest

pytestmark = pytest.mark.unit


class TestScan:
    """Tests for secrets.scan()."""

    def test_scan_aws_access_key(self):
        key = "AKIA" + "IOSFODNN7EXAMPLE"
        from hooks.secrets import scan

        hits = scan(f"export AWS_ACCESS_KEY_ID={key}")
        assert "aws_access_key" in hits

    def test_scan_github_token(self):
        token = "ghp_" + "A" * 36
        from hooks.secrets import scan

        hits = scan(f"token: {token}")
        assert "github_token" in hits

    def test_scan_private_key(self):
        header = "-----BEGIN RSA" + " PRIVATE KEY-----"
        from hooks.secrets import scan

        hits = scan(f"{header}\nMIIEowIBAAK...")
        assert "private_key" in hits

    def test_scan_db_url(self):
        scheme = "postgres"
        userpass = "admin:s3cr3tpassword"
        host = "db.example.com/mydb"
        url = f"{scheme}://{userpass}@{host}"
        from hooks.secrets import scan

        hits = scan(url)
        assert "db_url_creds" in hits

    def test_scan_clean_text(self):
        from hooks.secrets import scan

        hits = scan("ls -la /tmp && echo 'hello world' && git status")
        assert hits == []

    def test_scan_env_var_reference(self):
        """PASSWORD=$MY_VAR should not be flagged — it is a reference, not a value."""
        from hooks.secrets import scan

        hits = scan("PASSWORD=$MY_VAR")
        assert "generic_secret" not in hits

    def test_scan_env_var_reference_placeholder(self):
        """PASSWORD=<placeholder> should not be flagged."""
        from hooks.secrets import scan

        hits = scan("PASSWORD=<my-secret-here>")
        assert "generic_secret" not in hits

    def test_scan_bearer_token(self):
        header = "Authorization: Bearer "
        token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" + ".payload.sig"
        from hooks.secrets import scan

        hits = scan(header + token)
        assert "bearer_token" in hits

    def test_scan_aws_secret_key(self):
        key_name = "aws_secret" + "_access_key"
        key_val = "wJalrXUtnFEMI" + "/K7MDENG/bPxRfiCYEXAMPLEKEY"
        from hooks.secrets import scan

        hits = scan(f"{key_name}={key_val}")
        assert "aws_secret_key" in hits

    def test_scan_generic_secret_value(self):
        """Literal secret value assigned to a known key name should be flagged."""
        name = "API" + "_KEY"
        value = "supersecretvalue123"
        from hooks.secrets import scan

        hits = scan(f"{name}={value}")
        assert "generic_secret" in hits

    def test_scan_nosecret_suppresses_line(self):
        """A line ending with # nosecret should not be flagged."""
        key = "AKIA" + "IOSFODNN7EXAMPLE"
        from hooks.secrets import scan

        hits = scan(f"key = {key}  # nosecret")
        assert hits == []

    def test_scan_nosecret_only_suppresses_marked_line(self):
        """Only the marked line is suppressed; other lines are still scanned."""
        key = "AKIA" + "IOSFODNN7EXAMPLE"
        from hooks.secrets import scan

        text = f"safe = 'nothing'  # nosecret\nkey = {key}\n"
        hits = scan(text)
        assert "aws_access_key" in hits

    def test_scan_nosecret_case_insensitive(self):
        """# NOSECRET and # NoSecret are also valid suppressors."""
        key = "AKIA" + "IOSFODNN7EXAMPLE"
        from hooks.secrets import scan

        assert scan(f"x = {key}  # NOSECRET") == []
        assert scan(f"x = {key}  # NoSecret") == []


class TestRedact:
    """Tests for secrets.redact()."""

    def test_redact_replaces_secrets(self):
        key = "AKIA" + "IOSFODNN7EXAMPLE"
        from hooks.secrets import redact

        result = redact(f"key: {key} rest")
        assert "[REDACTED:aws_access_key]" in result
        assert key not in result

    def test_redact_clean_text_unchanged(self):
        from hooks.secrets import redact

        text = "ls -la /tmp && echo hello"
        result = redact(text)
        assert result == text

    def test_redact_multiple_secrets(self):
        key = "AKIA" + "IOSFODNN7EXAMPLE"
        key_name = "aws_secret" + "_access_key"
        key_val = "wJalrXUtnFEMI" + "/K7MDENG/bPxRfiCYEXAMPLEKEY"
        from hooks.secrets import redact

        result = redact(f"{key} and {key_name}={key_val}")
        assert "[REDACTED:aws_access_key]" in result
        assert "[REDACTED:aws_secret_key]" in result

    def test_redact_db_url(self):
        scheme = "postgres"
        userpass = "admin:s3cr3tpassword"
        host = "db.example.com/mydb"
        url = f"{scheme}://{userpass}@{host}"
        from hooks.secrets import redact

        result = redact(url)
        assert "[REDACTED:db_url_creds]" in result
        assert "s3cr3tpassword" not in result
