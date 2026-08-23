"""Credential-read guard — blocks a read whose OUTPUT would be a secret value.

Ported from the bundle's Claude-only PreToolUse hook so it runs on every
target. It previously reached Claude alone: it was wired through Claude's
settings `hooks` array, and the companion `permissions.deny` rules are a Claude
key too. codex and copilot consumed neither, so credential-file reads were
unguarded there — copilot's own `permissions.deny` is enterprise-managed and
inert in user settings (verified live on v1.0.80: a bare `read` deny did not
block a read).

Reading IS the exposure: a value that reaches the transcript is published and
has to be rotated, not deleted. The guard therefore blocks the read rather than
redacting the output.

``decide(payload)`` returns a block reason, or None to allow. It reads
``tool_name``/``tool_input``, which hooks.targets.normalizer already fills for
codex and copilot, so no target-specific handling is needed here.
"""

#!/usr/bin/env python3
"""Credential-file read guard — PreToolUse.

Keeps credential *values* out of the transcript. The transcript is indexed and
permanent, so a value that reaches context is published: the remedy is rotating
the credential, not deleting the file. Doctrine lives in
``.claude/rules/credential-files.md``; this script is its enforcement.

Contract: a PreToolUse payload arrives on stdin. Exit 0 allows the call; exit 2
blocks it and the stderr text is shown to the agent — the same contract every
agentihooks guard uses. Any internal error exits 0, because a guard bug must
never brick a session.

Covers what ``permissions.deny`` provably cannot: shell sourcing, environment
dumps, interpreter reads, container/remote reads, value-rendering platform
commands, and emitting a secret-named variable.

Run ``--selftest`` to exercise the decision table.
"""

import os
import re
import shlex

# --- what counts as sensitive -------------------------------------------------

SAFE_SUFFIXES = (".example", ".sample", ".template", ".dist", ".tpl")

SHELL_RC = {
    ".bashrc",
    ".bash_profile",
    ".bash_login",
    ".profile",
    ".zshrc",
    ".zprofile",
    ".zshenv",
    ".bash_history",
    ".zsh_history",
}

CREDENTIAL_FILES = {".netrc", ".npmrc", ".pypirc", ".git-credentials", ".pgpass"}

KIND_DOTENV = "dotenv"
KIND_SHELLRC = "shellrc"
KIND_CREDENTIAL = "credential"
KIND_ENVIRONMENT = "environment"  # a live value, not a file on disk


def sensitive_kind(token):
    """Classify a path-ish token, or return None when it is not sensitive."""
    if not token:
        return None
    token = token.strip().strip("'\"")
    base = token.rstrip("/").split("/")[-1]
    if not base or base.endswith(SAFE_SUFFIXES):
        return None
    if base == ".env" or base.startswith(".env.") or (base.endswith(".env") and len(base) > 4):
        return KIND_DOTENV
    if base in SHELL_RC:
        return KIND_SHELLRC
    if base in CREDENTIAL_FILES:
        return KIND_CREDENTIAL
    if base == "credentials" and ".aws" in token:
        return KIND_CREDENTIAL
    return None


SECRETISH_NAME = re.compile(
    r"(?i)(PASSWORD|PASSWD|SECRET|TOKEN|API_?KEY|APIKEY|CREDENTIAL"
    r"|PRIVATE_?KEY|ACCESS_?KEY|SESSION_?KEY|AUTH)"
)

# --- bash lexing --------------------------------------------------------------

READER_VERBS = {
    "cat",
    "head",
    "tail",
    "sed",
    "less",
    "more",
    "bat",
    "strings",
    "xxd",
    "od",
    "nl",
    "tac",
    "awk",
    "grep",
    "egrep",
    "fgrep",
    "rg",
    "ack",
    "jq",
    "yq",
    "cp",
    "tar",
    "dd",
    "base64",
    "gpg",
    "openssl",
    "vi",
    "vim",
    "nano",
    "view",
    "source",
    ".",
    "python",
    "python3",
    "node",
    "ruby",
    "perl",
    "php",
    "dotenv",
    "scp",
    "rsync",
    "sftp",
    "xargs",
    "diff",
    "cmp",
}

# grep/rg flags that emit counts or filenames rather than matching lines
NON_CONTENT_GREP = re.compile(r"(?:^|\s)-[A-Za-z]*[clLq]")

# A sensitive path can hide inside a larger token — python3 -c "open('.env')".
# Sweep the raw command for the vocabulary itself when tokenizing finds nothing.
SENSITIVE_FRAGMENT = re.compile(
    r"[\w./~-]*(?:"
    r"\.env(?:\.[\w-]+)*"
    r"|[\w-]+\.env"
    r"|\.bashrc|\.bash_profile|\.bash_login|\.profile"
    r"|\.zshrc|\.zprofile|\.zshenv|\.bash_history|\.zsh_history"
    r"|\.netrc|\.npmrc|\.pypirc|\.git-credentials|\.pgpass"
    r"|\.aws/credentials"
    r")"
)

STRIPPER_STAGE = (
    re.compile(r"^\s*wc(\s|$)"),
    re.compile(r"^\s*grep\s+.*-[A-Za-z]*[clLq]"),
    re.compile(r"^\s*cut\s+.*-f\s*1(\s|$)"),
    re.compile(r"^\s*sed\s+.*s/=\.\*//"),
    re.compile(r"^\s*awk\s+.*-F.*print\s+\$1"),
    re.compile(r"^\s*compgen\b"),
)
NEUTRAL_STAGE = re.compile(r"^\s*(sort|uniq|column|tr)\b")


HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1.*?^\s*\2\s*$", re.S | re.M)


def strip_heredocs(cmd):
    """Drop heredoc bodies — they are data fed to a command, not commands."""
    return HEREDOC.sub("<<HEREDOC", cmd)


def split_commands(cmd):
    return [c for c in re.split(r"&&|\|\||;|\n", cmd) if c.strip()]


def split_stages(command):
    return [s for s in re.split(r"(?<!\|)\|(?!\|)", command) if s.strip()]


def tokens_of(text):
    try:
        return shlex.split(text)
    except ValueError:
        return text.split()


def verb_of(tokens):
    for tok in tokens:
        if tok in ("sudo", "command", "env") and len(tokens) > 1:
            continue
        return tok.split("/")[-1]
    return ""


# --- message construction -----------------------------------------------------

PREAMBLE = (
    "A value read here enters the transcript, which is indexed and permanent — "
    "an exposed credential has to be rotated, not deleted."
)

ALTERNATIVE = {
    KIND_DOTENV: (
        "To learn what a project configures, read its .env.example / .env.sample.\n"
        'To test whether one variable is set:  test -n "${VAR:-}" && echo set || echo unset'
    ),
    KIND_SHELLRC: (
        "Shell rc files carry the operator's exported credentials. Ask the operator what "
        "is configured, or check size only:  wc -l ~/.bashrc"
    ),
    KIND_CREDENTIAL: (
        "This file exists to hold credentials. Reference the value through its environment "
        "variable or its secret store; never open the file."
    ),
    KIND_ENVIRONMENT: (
        "Name-only views carry no values:  env | cut -d= -f1  ·  env | wc -l\n"
        'To test one variable:  test -n "${VAR:-}" && echo set || echo unset\n'
        'To use a value, reference the variable ("$VAR") so the shell expands it at '
        "execution instead of printing it."
    ),
}

MAX_KEYS = 200
MAX_BYTES = 64 * 1024
KEY_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")


def dotenv_keys(path):
    """Key names only. Values never leave this process."""
    try:
        with open(os.path.expanduser(path), "r", encoding="utf-8", errors="replace") as fh:
            blob = fh.read(MAX_BYTES)
    except OSError:
        return []
    names = []
    for line in blob.splitlines():
        m = KEY_LINE.match(line)
        if m and m.group(1) not in names:
            names.append(m.group(1))
            if len(names) >= MAX_KEYS:
                break
    return names


def block(what, kind, path=None):
    lines = ["BLOCKED: {}.".format(what), PREAMBLE, ""]
    if kind == KIND_DOTENV and path:
        keys = dotenv_keys(path)
        if keys:
            lines.append("Keys defined (names only): " + ", ".join(keys))
    lines.append(ALTERNATIVE.get(kind, ALTERNATIVE[KIND_CREDENTIAL]))
    return "\n".join(lines)


# --- per-tool decisions -------------------------------------------------------


def decide_read(tool_input):
    path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    kind = sensitive_kind(path)
    if kind:
        return block("reading {}".format(path), kind, path)
    return None


def decide_grep(tool_input):
    for field in ("path", "glob", "pattern"):
        value = tool_input.get(field) or ""
        kind = sensitive_kind(value)
        if kind:
            return block("searching the contents of {}".format(value), kind, value if field == "path" else None)
    return None


def env_dump_verdict(command):
    stages = split_stages(command)
    if not stages:
        return None
    toks = tokens_of(stages[0])
    if not toks:
        return None
    verb = verb_of(toks)
    args = [t for t in toks[1:] if not t.startswith("-")]
    flags = [t for t in toks[1:] if t.startswith("-")]

    if verb == "printenv" and args:
        for name in args:
            if SECRETISH_NAME.search(name):
                return block("printing the value of {}".format(name), KIND_ENVIRONMENT)
        return None

    dump = (
        (verb == "env" and not args and not any(f.startswith("--") for f in flags))
        or (verb == "printenv" and not args)
        or (verb == "export" and (not toks[1:] or toks[1:] == ["-p"]))
        or (verb == "declare" and "-x" in flags and not args)
        or (verb == "set" and not toks[1:])
    )
    if not dump:
        return None

    # Walk the pipeline in order: once a stage strips values, everything after it
    # only ever sees key names, so the rest of the pipeline is harmless.
    for stage in stages[1:]:
        if any(p.search(stage) for p in STRIPPER_STAGE):
            return None
        if not NEUTRAL_STAGE.search(stage):
            break
    return block(
        "dumping the whole environment ({})".format(verb),
        KIND_ENVIRONMENT,
    )


def echo_secret_verdict(command):
    if not re.search(r"\b(echo|printf)\b", command):
        return None
    for name in re.findall(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)", command):
        if SECRETISH_NAME.search(name):
            return block(
                "printing ${} to stdout".format(name),
                KIND_ENVIRONMENT,
            )
    return None


def renderer_verdict(command):
    low = command.lower()
    if re.search(r"\bdocker[- ]compose\b.*\bconfig\b", low) and "--no-interpolate" not in low:
        return (
            block(
                "rendering the compose file with interpolated values (docker compose config)",
                KIND_ENVIRONMENT,
            )
            + "\nUse --no-interpolate to see the file without resolved secrets."
        )
    if re.search(r"\bdocker\s+inspect\b", low) and not re.search(r"(--format|\s-f\s)", low):
        return (
            block(
                "dumping container config including its Env array (docker inspect)",
                KIND_ENVIRONMENT,
            )
            + "\nSelect fields instead:  docker inspect --format '{{.State.Status}}' <container>"
        )
    if re.search(r"\bkubectl\b.*\bget\s+secret", low) and re.search(r"-o\s*(yaml|json)", low):
        return (
            block(
                "printing Secret data (kubectl get secret -o yaml/json)",
                KIND_ENVIRONMENT,
            )
            + "\nkubectl describe secret <name> shows the keys and byte sizes without the values."
        )
    return None


def reader_verdict(command):
    toks = tokens_of(command)
    if not toks:
        return None
    target = None
    kind = None
    for tok in toks:
        k = sensitive_kind(tok)
        if k:
            target, kind = tok, k
            break
    if not kind:
        for frag in SENSITIVE_FRAGMENT.findall(command) or []:
            k = sensitive_kind(frag)
            if k:
                target, kind = frag, k
                break
    if not kind:
        return None
    verbs = {t.split("/")[-1] for t in toks} | {t for t in toks}
    reader = verbs & READER_VERBS
    if not reader:
        return None
    if reader <= {"grep", "egrep", "fgrep", "rg", "ack"} and NON_CONTENT_GREP.search(command):
        return None  # -c/-l/-q emit counts or filenames, not content
    return block("reading {} via shell".format(target), kind, target if kind == KIND_DOTENV else None)


def decide_bash(tool_input):
    command = tool_input.get("command") or ""
    if not command:
        return None
    command = strip_heredocs(command)
    for single in split_commands(command):
        for check in (env_dump_verdict, echo_secret_verdict, renderer_verdict, reader_verdict):
            verdict = check(single)
            if verdict:
                return verdict
    return None


DISPATCH = {
    "Read": decide_read,
    "NotebookRead": decide_read,
    "Grep": decide_grep,
    "Bash": decide_bash,
}


def decide(payload):
    handler = DISPATCH.get(payload.get("tool_name"))
    if handler is None:
        return None
    return handler(payload.get("tool_input") or {})


def disabled():
    return os.environ.get("ANTON_CREDENTIAL_GUARD", "").strip().lower() in {"off", "0", "false", "no"}


# --- selftest -----------------------------------------------------------------
