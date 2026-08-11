"""Per-(target, event) hook capabilities.

What a hook process is allowed to say back to its host CLI differs by target.
Handlers consult this map instead of assuming Claude Code semantics.

Codex specifics (CODEX-COMPAT.md §2.4, verified against codex-cli 0.147.0):
- ``PreToolUse`` output supports ``permissionDecision: "deny"`` only — no
  allow/ask, and no ``additionalContext`` injection.
- Blocking via exit code 2 + stderr works on every event, same as Claude.
"""

from __future__ import annotations

from hooks.targets import current_target

# Events whose stdout JSON may carry hookSpecificOutput.additionalContext.
_CODEX_NO_CONTEXT_EVENTS = frozenset({"PreToolUse"})

# Values legal in hookSpecificOutput.permissionDecision per target.
_PERMISSION_DECISIONS = {
    "claude": frozenset({"allow", "deny", "ask"}),
    "codex": frozenset({"deny"}),
}


def can_inject_context(event: str, target: str | None = None) -> bool:
    target = target or current_target()
    if target == "codex" and event in _CODEX_NO_CONTEXT_EVENTS:
        return False
    return True


def allowed_permission_decisions(target: str | None = None) -> frozenset[str]:
    target = target or current_target()
    return _PERMISSION_DECISIONS.get(target, _PERMISSION_DECISIONS["claude"])
