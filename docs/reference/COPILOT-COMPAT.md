# COPILOT-COMPAT — GitHub Copilot CLI as an AgentiHooks target

Reference for the `copilot` install target. Every claim carries how it was
established, so a reader can re-derive it against a newer CLI rather than
trusting this page.

**Verified against `@github/copilot` 1.0.79-6.** Copilot ships several releases
per week and has removed a flag pair (`--headless --stdio`) with no deprecation
window, so treat the surface as fast-moving: re-run `agentihooks doctor --target
copilot` after a CLI upgrade.

## §1 What a target is

See `scripts/targets/__init__.py`. A target is the agent CLI whose config
surface `agentihooks init` writes. Profile resolution, bundle linking, settings
merging and MCP server-dict assembly are target-agnostic; everything touching a
target-specific path or schema goes through the adapter from `get_adapter()`.

## §2 Hook contract

### §2.1 Events

Copilot's `HookType` enum carries 17 events. AgentiHooks wires the 12 that
`hook_manager.EVENT_HANDLERS` dispatches, registered under the **enum
spellings** from `schemas/api.schema.json`:

`sessionStart`, `sessionEnd`, `userPromptSubmitted`, `preToolUse`,
`postToolUse`, `postToolUseFailure`, `agentStop`, `subagentStart`,
`subagentStop`, `preCompact`, `permissionRequest`, `notification`.

⚠️ Two of these are **different tokens**, not case variants: Claude's `Stop` is
Copilot's `agentStop`, and `UserPromptSubmit` is `userPromptSubmitted`.
Lowercasing a Claude event name produces an event that does not exist and is
silently ignored by the loader.

Copilot's loader also accepts the Claude-style PascalCase aliases — verified on
1.0.80 (see the probe below) — but the enum spellings are what gets registered:
they carry direct schema evidence, and loader acceptance is not by itself proof
that an alias reaches the same handler.

Not registered: `preMcpToolCall`, `userPromptTransformed`, `errorOccurred` —
no distinct handler exists, but the normalizer maps each onto the nearest
dispatched event, so one arriving anyway is handled rather than dropped.

`postResult` and `prePRDescription` are neither registered **nor** mapped:
folding `postResult` onto `Stop` would re-run session-end work once per agent
result, and `prePRDescription` has no analogue. If either arrives, hook_manager
logs it as an unknown event.

Both spellings resolve. Registration uses the PascalCase aliases; Copilot may
echo either those or its own camelCase, and an unmapped name reaches no handler
and exits 0 — a silent bypass of every guardrail for that event. `_COPILOT_EVENTS`
therefore carries a camelCase entry, a derived identity entry per dispatch name,
and an explicit entry for `PostToolUseFailure` (registered PascalCase but
dispatched as `PostToolUse`, so the derived pass cannot cover it).
`tests/test_hook_targets.py::test_registered_pascalcase_spelling_resolves`
asserts every registered event resolves to a real handler.

Unlike codex, Copilot has native `PostToolUseFailure` and `Notification` events,
so **no `notify_shim` equivalent is needed**.

### §2.2 Registration

`~/.copilot/hooks/agentihooks.json`:

```json
{ "version": 1,
  "hooks": { "SessionStart": [ { "type": "command",
                                 "command": "~/.copilot/agentihooks-hook.sh",
                                 "timeoutSeconds": 30 } ] } }
```

Copilot merges hook definitions from several sources — admin policy files,
`.github/hooks/*.json`, `$COPILOT_HOME/hooks/`, an inline `hooks` key in
`settings.json`, and plugins. AgentiHooks writes the **hooks directory only**.
Writing both the directory file and the inline settings key fires every hook
twice.

Trust is keyed by content hash via the `disabledHooks` setting, so editing the
wrapper invalidates the hash and needs re-approval.

**Verified empirically against 1.0.80.** The loader runs *before* auth, so this
is testable without a Copilot subscription. Write a hooks file containing every
event name plus one deliberately bogus canary, point `COPILOT_HOME` at a scratch
dir, and run `copilot -p hi --log-level all --log-dir <dir>`:

```
Ignoring unknown hook event(s) in <path>/hooks/agentihooks.json: ZZZ_CANARY_NOT_REAL
```

Only the canary is named — for both the camelCase enum spellings and the
PascalCase aliases. That is what proves the names are recognised, that the
loader really validates (it rejects the canary rather than accepting anything),
and that `$COPILOT_HOME/hooks/*.json` is read at all, since the message names
the file. `scripts/copilot_smoke.sh` [2b] runs this check with the canary as a
second assertion, so a loader that silently ignored everything cannot score a
pass.

A grep of the binary for a quoted `"SessionStart"` returns nothing, which looks
like proof the aliases are rejected — it is a false negative. The alias
resolution is not a table of literal strings, and the `config.json` →
`settings.json` migration copies keys verbatim without normalising them, so
neither observation speaks to what the loader accepts. Only the probe does.

Two caveats from the same probe: the loader **tolerates unrecognized keys
silently** (a deliberately bogus key produced no complaint), so "no error" is
not evidence a field is honored; and the timeout field is written as
`timeoutSeconds`, because `timeoutSec` — the spelling in the public hooks
reference — appears zero times in `app.js` while `timeoutSeconds` appears in
both `app.js` and the native engine. A serde symbol dump of the engine does show
`timeoutSec` adjacent to the `HookConfig` discriminants, so the two spellings may
both be live on different paths; `timeoutSeconds` is the one with evidence in
both layers. Copilot fails OPEN on timeout, so the wrong spelling degrades to
the default rather than to a block.

`HookConfig` also carries `matcher` (a regex over tool names) and
`allowedEnvVars`, neither of which the adapter sets — unused capability, not a
gap.

### §2.3 stdout contract

Copilot parses hook stdout as exactly one JSON object, same as codex. Handlers
buffer through `hooks/targets/emitter.py` and flush once at process exit. The
predicate is `buffers_single_envelope()`, not `is_codex()` — the property is a
target capability, not a target identity.

### §2.4 Permission channel

`PreToolUse` on Copilot is a **superset** of Claude's and far wider than codex's:

| | claude | codex | copilot |
|---|---|---|---|
| `permissionDecision` | allow/deny/ask | deny only | allow/deny/ask |
| `additionalContext` on PreToolUse | yes | no | yes |
| `modifiedArgs` (rewrite tool args) | no | no | yes |

Encoded in `hooks/targets/capabilities.py`. `supports_arg_mutation()` is the
declared seam for `modifiedArgs`; nothing consumes it yet.

### §2.5 Exit-code semantics — the open hazard

Two sources disagree and this matters for every guardrail:

- GitHub's hooks reference states `preToolUse` command hooks are **fail-closed**:
  any non-zero exit denies the tool call.
- The shipped runtime carries the literal string
  `Hook command exited with code 2 (warning)`, implying exit 2 is a **warning**
  on at least some events.

AgentiHooks blocks via `BlockAction` → exit 2 + stderr. Rather than bet on which
source is authoritative, `hook_manager.main()` consults
`requires_envelope_block(event)` on the block path and, for copilot on the events
that carry a decision field (`PreToolUse`, `PermissionRequest`), also emits
`hookSpecificOutput.permissionDecision: "deny"` on stdout — one JSON object,
alongside the exit code. Codex and claude are unaffected; their block path emits
nothing on stdout, as before.

**Timeouts always fail OPEN**, on every event including `preToolUse`. A hung
hook does not block — it stops guarding. This is why `timeoutSec` is set
generously (30s) rather than tightly.

## §3 Surface map

| Concern | Copilot path | Notes |
|---|---|---|
| Config home | `~/.copilot` | `COPILOT_HOME` overrides; no XDG support |
| Settings | `~/.copilot/settings.json` | plus `settings.local.json`; repo scope `.github/copilot/settings.json` |
| Machine config | `~/.copilot/config.json` | **never written** — CLI-managed, its own header says "User settings belong in settings.json" |
| Hooks | `~/.copilot/hooks/*.json` | repo scope `.github/hooks/*.json` |
| Persona | `~/.copilot/copilot-instructions.md` | also reads `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `.github/copilot-instructions.md` |
| Instructions | `~/.copilot/instructions/**/*.instructions.md` | path-scoped; not used by agentihooks |
| MCP | `~/.copilot/mcp-config.json` | key `mcpServers`; repo scope `.mcp.json` / `.github/mcp.json` |
| Skills | `~/.copilot/skills/`, `~/.agents/skills/` | agentihooks uses the open standard dir, shared with codex |
| Agents | `~/.copilot/agents/*.md` | MD + YAML frontmatter |
| Commands | — | no prompt-file mechanism (github/copilot-cli#1113) |
| Status line | `settings.json` `statusLine` | `type: "command"`, session JSON on stdin |
| Session log | `~/.copilot/session-state/<id>/events.jsonl` | see §6 |

## §4 What the adapter writes

`scripts/targets/copilot_target.py`.

**settings.json** — managed keys only, recorded under an `agentihooks.managed`
key so a value the operator hand-edited since the last write is left alone and
reported. `statusLine` wires to `python -m hooks.statusline`; `disableAllHooks`
is pinned false because an inherited true kills every guardrail silently.

`trustedFolders` is deliberately **outside** the managed-key rule. It is a set
the operator also edits via `/add-dir`, so treating a non-empty list as a
hand-edit would mean never seeding the repo root on any machine that had ever
trusted a directory. It is unioned, never replaced.

**Features** — skills symlink to `~/.agents/skills`; agents translate into
`~/.copilot/agents`; commands translate into skills (see §5); rules compile into
the persona, since Copilot auto-loads instruction files rather than a rules dir.

**Persona** — `copilot-instructions.md`, assembled by the shared
`scripts/targets/_common.build_persona()`: identity preamble → bundle CLAUDE.md
→ profile-chain CLAUDE.mds → compiled rules → CI manifesto, between
`_MANAGED_HEADER` / `_MANAGED_FOOTER` so an operator-appended tail survives
re-init. Copilot has no `project_doc_max_bytes` analogue, so no ceiling is
raised.

## §5 Divergences from the codex adapter

| | codex | copilot | why |
|---|---|---|---|
| Agents | skipped | installed | Copilot has a real custom-agent registry |
| Commands | `~/.codex/prompts/` | skills in `~/.agents/skills/` | Copilot has no prompt-file mechanism |
| SSE MCP | dropped with a warning | supported | Copilot ships an SSE client |
| Header `${VAR}` | mapped to `bearer_token_env_var` | dropped with a warning | Copilot has no env-indirection field and sends header values literally |
| Status line | static `tui.status_line` items | command-backed | Copilot supports a command status line |
| Notification | `notify` shim bridge | native event | Copilot has a `notification` hook |
| Config format | TOML via tomlkit | JSON | — |

**Command translation.** Each `commands/<name>.md` becomes
`~/.agents/skills/<name>/SKILL.md` with `name` + `description` frontmatter. It
loses `/name` invocation and becomes model-discoverable instead.

**Shared-directory hazard.** `~/.agents/skills` holds both codex's symlinks and
copilot's translated commands. The translation manifest is a separate file
(`.agentihooks-copilot-commands.json`, not the `.agentihooks-manifest.json`
codex uses for prompts), reaping only real directories it wrote and never
following or deleting a symlink. A symlinked skill of the same name always wins
over a translated command.

**Agent frontmatter translation.** Claude tool names map to Copilot runtime
names: `Read`→`view`, `Write`→`create`, `Edit`→`edit`, `Bash`→`shell`,
`Grep`→`grep`, `Glob`→`glob`, `WebFetch`→`web_fetch`, `WebSearch`→`web_search`,
`Agent`/`Task`→`task`, `TodoWrite`→`update_todo`,
`AskUserQuestion`→`ask_user`. `description` is required by Copilot and is
synthesized when the source omits it, or the agent is unloadable. Bodies over
30,000 characters are truncated at a paragraph boundary with a marker.

## §6 Transcript format

`~/.copilot/session-state/<session-id>/events.jsonl`.

⚠️ The `session-state/<session-id>/` directory layout is **observed** (an
unauthenticated 1.0.80 run creates it, alongside `workspace.yaml`,
`checkpoints/`, `rewind-file-snapshots/`, `research/`, `files/`). The
`events.jsonl` filename and its contents are **not** — the file only
materializes on an authenticated turn, and this integration has not yet had
one. The per-line shape below is derived from the shipped
`session-events.schema.json`, which is authoritative for the event union but
does not name the file. Re-verify after the first authenticated session; the
fixture (`tests/fixtures/copilot_events_sample.jsonl`) is schema-derived and
should be replaced with a captured one.

Each line is
`{id, timestamp, parentId, type, data}` where `type` is a dotted namespace
string. No other target writes a dotted type, so the prefix alone discriminates
the format (`hooks/memory/transcript_reader.py`).

Mapped into `TranscriptRecord`:

| Copilot event | record kind |
|---|---|
| `session.start` | `meta` |
| `user.message` | `user_text` |
| `assistant.message` | `assistant_text` |
| `system.message` | `system_text` |
| `tool.execution_start` | `tool_call` |
| `tool.execution_complete` | `tool_result` (`is_error` = `not data.success`) |
| `assistant.usage` | `token_usage` |
| `session.task_complete` | `turn_complete`, only when the turn produced no `assistant.message` |

The envelope also carries `ephemeral` and `agentId`, which the reader uses to
skip streaming deltas (§6 rules below) and ignores respectively.

Two rules that matter:

- **Ephemeral events are skipped** (except `assistant.usage`, which is marked
  ephemeral but is the only usage record). Streaming deltas and re-renders would
  otherwise multiply every reply by its chunk count.
- **`session.task_complete` is a fallback only.** Emitting it alongside
  `assistant.message` double-counts every turn for consumers that treat the two
  as equivalent digest text — the same rule the codex reader applies to
  `task_complete`.

Unlike codex, Copilot states tool success explicitly, so transcript error
scanning works and `tool_memory` does not have to fall back to live PostToolUse
recording.

## §7 Payload normalization

Copilot sends camelCase (`sessionId`, `toolName`, `toolArgs`, `toolResult`) and
its own event vocabulary. `hooks/targets/normalizer.py` fills both spellings and
maps every known event name onto the single vocabulary `EVENT_HANDLERS`
dispatches on, so a guardrail cannot depend on which spelling arrives. The
original name is preserved as `copilot_event_name` for diagnostics.

Copilot omits `transcript_path`; `copilot_events_path()` resolves it from the
session id for the transcript-driven events only.

## §8 Known gaps

- **Uninstall.** `uninstall_global()` removes Claude artifacts only — codex has
  the same gap, and copilot inherits it. Tracked in the defer log.
- **Slash commands.** No prompt-file support upstream; commands are reachable as
  skills, not as `/name`.
- **Exit-code semantics.** §2.5 — needs an authenticated live turn to settle;
  `scripts/copilot_smoke.sh` [8] is the assertion and currently skips.
- **`events.jsonl` unobserved.** §6 — filename and contents are schema-derived
  until an authenticated session produces one.
- **MCP `url` / `command` / `args` are not secret-scanned** on any target — only
  `env` values, header values and `tools` entries are. A credential embedded in
  a server URL reaches disk. Pre-existing across claude, codex and copilot;
  tracked in the defer log rather than changed here, because tightening what
  gets dropped would alter existing installs on the next `init`.

## §9 Verification

```bash
agentihooks init --target copilot
agentihooks doctor --target copilot
./scripts/copilot_smoke.sh              # live, against a throwaway COPILOT_HOME
uv run python -m pytest tests/test_copilot_target.py tests/test_copilot_e2e.py
```

## §10 Evidence table

Everything above was derived from the shipped package, not from documentation
alone. Reproduce with:

| Claim | How to re-derive |
|---|---|
| 17 hook events, exact names | `jq '.definitions.HookType.enum' schemas/api.schema.json` in the `@github/copilot-<platform>` package |
| Hook settings catalogue, `disableAllHooks`, `disabledHooks` | `strings prebuilds/*/runtime.node \| grep -o '{"path":"[^"]*[Hh]ook[^"]*"[^}]*}'` |
| Exit-code / timeout strings | `strings prebuilds/*/runtime.node \| grep -E 'Hook command (failed\|timed out\|exited)'` |
| Config paths (`mcp-config.json`, `copilot-instructions.md`, `skills/`) | `grep -oE '\.copilot/[A-Za-z0-9/._*-]+' app.js \| sort -u` |
| Repo-scope paths (`.github/hooks/*.json`, `.github/copilot/settings.json`) | `grep -oE '\.github/[A-Za-z0-9/._*-]+' app.js \| sort -u` |
| Settings semantics ("User settings belong in settings.json", `hooks`, `statusLine`, `trustedFolders`) | the `{name:"config",summary:"Configuration Settings"` help topic in `app.js` |
| Instruction files read (`AGENTS.md`, `CLAUDE.md`, `copilot-instructions.md`) | `grep -oE '"[A-Za-z.-]*\.md"' app.js \| sort -u` |
| Session-event envelope + `data` shapes | `jq '.definitions.SessionEvent.anyOf' schemas/session-events.schema.json` |
| Subcommands and 89 flags | `copilot completion bash`, or the installed `~/.local/share/bash-completion/completions/copilot` |
| `COPILOT_HOME` and other env vars | `grep -oE 'COPILOT_[A-Z0-9_]+' app.js \| sort -u` |

Cross-checked against `docs.github.com/en/copilot/reference/hooks-reference`,
`.../custom-agents-configuration`, and the MCP/instructions how-to pages.
