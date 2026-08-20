"""Credential-read guard behaviour, ported with the guard itself.

These cases came from the bundle hook's own selftest, which ran only on Claude.
The guard now runs on every target, so they run in CI instead of by hand.
"""

import pytest

from hooks.context.credential_guard import decide

pytestmark = pytest.mark.unit

CASES = [
    # (label, payload, should_block)
    ("read dotenv", {"tool_name": "Read", "tool_input": {"file_path": "/srv/app/.env"}}, True),
    ("read .env.production", {"tool_name": "Read", "tool_input": {"file_path": ".env.production"}}, True),
    ("read stack env", {"tool_name": "Read", "tool_input": {"file_path": "runtime/tracker.env"}}, True),
    ("read .env.example", {"tool_name": "Read", "tool_input": {"file_path": ".env.example"}}, False),
    ("read bashrc", {"tool_name": "Read", "tool_input": {"file_path": "~/.bashrc"}}, True),
    ("read netrc", {"tool_name": "Read", "tool_input": {"file_path": "/home/x/.netrc"}}, True),
    ("read aws creds", {"tool_name": "Read", "tool_input": {"file_path": "~/.aws/credentials"}}, True),
    ("read source file", {"tool_name": "Read", "tool_input": {"file_path": "hooks/secrets.py"}}, False),
    ("grep in dotenv", {"tool_name": "Grep", "tool_input": {"pattern": "URL", "path": ".env"}}, True),
    ("grep in src", {"tool_name": "Grep", "tool_input": {"pattern": "URL", "path": "src/"}}, False),
    ("glob untouched", {"tool_name": "Glob", "tool_input": {"pattern": "**/.env"}}, False),
    ("write untouched", {"tool_name": "Write", "tool_input": {"file_path": ".env"}}, False),
    ("cat dotenv", {"tool_name": "Bash", "tool_input": {"command": "cat .env"}}, True),
    ("source bashrc", {"tool_name": "Bash", "tool_input": {"command": "source ~/.bashrc"}}, True),
    ("dot-source dotenv", {"tool_name": "Bash", "tool_input": {"command": ". ./.env"}}, True),
    ("cat example", {"tool_name": "Bash", "tool_input": {"command": "cat .env.example"}}, False),
    ("ls dotenv", {"tool_name": "Bash", "tool_input": {"command": "ls -la .env"}}, False),
    ("wc dotenv", {"tool_name": "Bash", "tool_input": {"command": "wc -l ~/.bashrc"}}, False),
    ("test -f dotenv", {"tool_name": "Bash", "tool_input": {"command": "test -f .env && echo yes"}}, False),
    ("grep -c bashrc", {"tool_name": "Bash", "tool_input": {"command": "grep -c export ~/.bashrc"}}, False),
    ("grep content bashrc", {"tool_name": "Bash", "tool_input": {"command": "grep export ~/.bashrc"}}, True),
    ("bare env", {"tool_name": "Bash", "tool_input": {"command": "env"}}, True),
    ("bare printenv", {"tool_name": "Bash", "tool_input": {"command": "printenv"}}, True),
    ("export -p", {"tool_name": "Bash", "tool_input": {"command": "export -p"}}, True),
    ("env names", {"tool_name": "Bash", "tool_input": {"command": "env | cut -d= -f1"}}, False),
    ("env count", {"tool_name": "Bash", "tool_input": {"command": "env | wc -l"}}, False),
    ("env grep value", {"tool_name": "Bash", "tool_input": {"command": "env | grep REDIS"}}, True),
    ("env names then head", {"tool_name": "Bash", "tool_input": {"command": "env | cut -d= -f1 | head -3"}}, False),
    ("env sorted names", {"tool_name": "Bash", "tool_input": {"command": "env | sort | cut -d= -f1"}}, False),
    ("env head raw", {"tool_name": "Bash", "tool_input": {"command": "env | head -3"}}, True),
    ("printenv PATH", {"tool_name": "Bash", "tool_input": {"command": "printenv PATH"}}, False),
    ("printenv secret", {"tool_name": "Bash", "tool_input": {"command": "printenv DB_PASSWORD"}}, True),
    ("echo secret var", {"tool_name": "Bash", "tool_input": {"command": 'echo "$KB_ROUTER_TOKEN"'}}, True),
    ("echo plain var", {"tool_name": "Bash", "tool_input": {"command": 'echo "$HOME"'}}, False),
    (
        "curl with token",
        {"tool_name": "Bash", "tool_input": {"command": 'curl -H "Authorization: Bearer $API_TOKEN" http://x'}},
        False,
    ),
    ("docker exec cat env", {"tool_name": "Bash", "tool_input": {"command": "docker exec app cat /app/.env"}}, True),
    (
        "kubectl exec cat env",
        {"tool_name": "Bash", "tool_input": {"command": "kubectl exec pod -- cat /app/.env"}},
        True,
    ),
    ("ssh cat bashrc", {"tool_name": "Bash", "tool_input": {"command": "ssh host cat ~/.bashrc"}}, True),
    ("compose config", {"tool_name": "Bash", "tool_input": {"command": "docker compose config"}}, True),
    (
        "compose no-interpolate",
        {"tool_name": "Bash", "tool_input": {"command": "docker compose config --no-interpolate"}},
        False,
    ),
    ("docker inspect bare", {"tool_name": "Bash", "tool_input": {"command": "docker inspect litellm"}}, True),
    (
        "docker inspect format",
        {"tool_name": "Bash", "tool_input": {"command": "docker inspect --format '{{.State.Status}}' litellm"}},
        False,
    ),
    ("kubectl secret yaml", {"tool_name": "Bash", "tool_input": {"command": "kubectl get secret db -o yaml"}}, True),
    ("kubectl secret list", {"tool_name": "Bash", "tool_input": {"command": "kubectl get secrets -n prod"}}, False),
    ("kubectl describe secret", {"tool_name": "Bash", "tool_input": {"command": "kubectl describe secret db"}}, False),
    (
        "python opens dotenv",
        {"tool_name": "Bash", "tool_input": {"command": "python3 -c \"print(open('.env').read())\""}},
        True,
    ),
    ("chained cat dotenv", {"tool_name": "Bash", "tool_input": {"command": "cd /app && cat .env"}}, True),
    ("git status", {"tool_name": "Bash", "tool_input": {"command": "git status --short"}}, False),
    ("kubectl logs", {"tool_name": "Bash", "tool_input": {"command": "kubectl logs -f pod-0 -n ns"}}, False),
    ("empty command", {"tool_name": "Bash", "tool_input": {"command": ""}}, False),
    ("no tool_input", {"tool_name": "Bash"}, False),
    ("unknown tool", {"tool_name": "WebFetch", "tool_input": {"url": "http://x/.env"}}, False),
    ("malformed payload", {}, False),
    (
        "heredoc mentioning a renderer",
        {
            "tool_name": "Bash",
            "tool_input": {"command": "python3 - <<'PY'\nprint('" + "docker " + "compose config')\nPY"},
        },
        False,
    ),
    (
        "heredoc mentioning a dotenv",
        {"tool_name": "Bash", "tool_input": {"command": "python3 - <<'PY'\nprint('read the .env file')\nPY"}},
        False,
    ),
]


@pytest.mark.parametrize("label,payload,should_block", CASES, ids=[c[0] for c in CASES])
def test_guard_decision(label, payload, should_block):
    verdict = decide(payload)
    assert (verdict is not None) is should_block


def test_guard_never_raises_on_garbage():
    for payload in ({}, {"tool_name": None}, {"tool_input": "notadict"}, {"tool_name": "Bash", "tool_input": None}):
        decide(payload)


class TestRunsOnEveryTarget:
    """The whole point of the port: this reached Claude only before."""

    def test_copilot_normalized_payload_blocks(self):
        # what hooks.targets.normalizer produces for copilot's `bash` tool
        assert decide({"tool_name": "Bash", "tool_input": {"command": "cat .env"}}) is not None

    def test_template_files_still_readable(self):
        assert decide({"tool_name": "Bash", "tool_input": {"command": "cat .env.example"}}) is None
