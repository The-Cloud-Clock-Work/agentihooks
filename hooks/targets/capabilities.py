"""Per-(target, event) hook capabilities.

What a hook process is allowed to say back to its host CLI differs by target.
Handlers consult this map instead of assuming Claude Code semantics.

Codex specifics (docs/reference/CODEX-COMPAT.md §2.4, verified against codex-cli 0.147.0):
- ``PreToolUse`` output supports ``permissionDecision: "deny"`` only — no
  allow/ask, and no ``additionalContext`` injection.
- Blocking via exit code 2 + stderr works on every event, same as Claude.

Copilot specifics (docs/reference/COPILOT-COMPAT.md, verified against @github/copilot 1.0.79-6):
- ``PreToolUse`` is a superset of Claude's: allow/deny/ask, plus
  ``additionalContext`` and ``modifiedArgs`` argument mutation.
- Exit code 2 is NOT a universal block: the runtime carries the string
  "Hook command exited with code 2 (warning)" while fail-closed denial is
  documented for ``preToolUse`` only. The JSON decision envelope is therefore
  the primary block channel for copilot; exit 2 is secondary.
"""

from __future__ import annotations

from hooks.targets import current_target

# Events whose stdout JSON may carry hookSpecificOutput.additionalContext.
_CODEX_NO_CONTEXT_EVENTS = frozenset({"PreToolUse"})

# Values legal in hookSpecificOutput.permissionDecision per target.
_PERMISSION_DECISIONS = {
    "claude": frozenset({"allow", "deny", "ask"}),
    "codex": frozenset({"deny"}),
    "copilot": frozenset({"allow", "deny", "ask"}),
}

# Targets whose PreToolUse channel can rewrite the tool's arguments in flight.
_ARG_MUTATION_TARGETS = frozenset({"copilot"})

# Targets that cannot be trusted to treat exit code 2 as a block on every
# event, so a guardrail must also state its denial in the stdout envelope.
_ENVELOPE_BLOCK_TARGETS = frozenset({"copilot"})


def can_inject_context(event: str, target: str | None = None) -> bool:
    target = target or current_target()
    if target == "codex" and event in _CODEX_NO_CONTEXT_EVENTS:
        return False
    return True


def allowed_permission_decisions(target: str | None = None) -> frozenset[str]:
    target = target or current_target()
    return _PERMISSION_DECISIONS.get(target, _PERMISSION_DECISIONS["claude"])


def supports_arg_mutation(target: str | None = None) -> bool:
    return (target or current_target()) in _ARG_MUTATION_TARGETS


# Events where a stdout ``permissionDecision`` envelope is meaningful. Emitting
# one on, say, SessionEnd would be noise the host has no field for.
_DECISION_EVENTS = frozenset({"PreToolUse", "PermissionRequest"})


def requires_envelope_block(event: str, target: str | None = None) -> bool:
    """Whether a denial must ALSO be stated in stdout JSON, not just via exit 2.

    Copilot's runtime carries the string "Hook command exited with code 2
    (warning)" while its docs describe ``preToolUse`` as fail-closed on any
    non-zero exit. Rather than bet on which is authoritative, the deny is
    stated in both channels on the events that have a decision field.
    """
    if event not in _DECISION_EVENTS:
        return False
    return (target or current_target()) in _ENVELOPE_BLOCK_TARGETS
