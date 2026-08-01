---
layout: default
title: MCP Transport
parent: Hooks
nav_order: 5
---

# MCP Transport — stdio and network modes
{: .no_toc }

1. TOC
{:toc}

---

## Why this exists

Some Claude Code deployments filter **every stdio-transport MCP server** out of
the client at load time. The server is never spawned, its tools never appear,
and `claude mcp add` refuses new registrations regardless of transport. On such
a machine `hooks-utils` is simply absent, taking Fleet Command, enforcement and
the brain tools with it.

Network transports (`sse`, `streamable-http`) are not filtered, so `hooks-utils`
can run as a persistent server the client connects to instead of spawns.

**stdio remains the default.** Nothing below applies unless you opt in.

## The difference in one table

| | stdio (default) | sse / streamable-http |
|---|---|---|
| Who starts the server | Claude Code **spawns** one per session | you run it; Claude Code **connects** |
| Processes | one per session | one, shared by every session |
| Caller identity | the process env — one process *is* one session | must be passed explicitly |
| If nothing is running | Claude Code starts it | no tools |

That last row is the whole reason a network mode needs a persistent server:
there is no "connect and it starts for you."

## Turning it on

```bash
echo 'MCP_TRANSPORT=streamable-http' >> ~/.agentihooks/.env
agentihooks init
systemctl --user enable --now agentihooks-mcp.service
```

`agentihooks init` reads the same `~/.agentihooks/.env` the daemon does, so one
edit drives both the `~/.claude.json` entry and the unit. It writes the unit but
never starts it — starting is an operator action.

Reverting is symmetric: remove the line (or set `MCP_TRANSPORT=stdio`) and
re-run `agentihooks init`. The stdio entry is restored and the unit is removed,
so a downgrade cannot leave a daemon running that nothing points at.

### Which transport

Prefer `streamable-http`. `sse` is the legacy MCP transport and is being phased
out of the spec; it is supported here because it is the mode most likely to be
verified working behind a restrictive client.

Note the naming mismatch, which is easy to get wrong: the SDK calls it
`streamable-http`, but Claude Code's config schema calls it `http`. The
installer emits the right one.

| `MCP_TRANSPORT` | `~/.claude.json` entry |
|---|---|
| `sse` | `{"type": "sse", "url": "http://127.0.0.1:8642/sse"}` |
| `streamable-http` | `{"type": "http", "url": "http://127.0.0.1:8642/mcp"}` |

## Caller identity — the part that changes how you use the tools

Under stdio, Claude Code spawns one server process per session, so the process
environment identifies the caller. Under a network transport one process serves
every session and no environment lookup can tell callers apart.

Four tools therefore take an explicit `session_id`:

- `call_agent`
- `pool_list`
- `pool_status`
- `channel_acknowledge`

SessionStart injects a banner naming the session's own id so the agent can pass
it. Under stdio the argument is optional and the environment is used as a
fallback; under a network transport **the fallback is disabled entirely** and an
omitted argument makes the call fail.

That refusal is deliberate. A daemon inherits `CLAUDE_CODE_SESSION_ID` from
whatever shell started it, so consulting the environment there does not return
"no idea" — it returns a real, unrelated session id and writes another agent's
state. Failing beats acting as the wrong agent.

Set `MCP_SESSION_ID_BANNER_ENABLED=false` to suppress the banner.

## What a shared server costs

- **One category set for everyone.** A url entry carries no per-client `env`
  block, so `MCP_CATEGORIES` in the daemon's `.env` applies to every session
  pointing at it. Per-profile tool subsetting is stdio-only.
- **Shared fate.** A crash takes the tools out for all sessions at once, which
  is why the unit restarts on any exit.
- **No authentication.** Both transports are plain HTTP with no token. The
  loopback bind *is* the boundary: any local process that can reach the port can
  call every tool and enumerate live session ids via `pool_list`. On a
  single-user workstation that is no worse than filesystem access to
  `~/.agentihooks`. On a shared-account host it is a real exposure — keep
  `MCP_HOST` at `127.0.0.1`, and do not widen it without adding a gate.

## The systemd unit

Written to `~/.config/systemd/user/agentihooks-mcp.service`, rendered from a
template in the package. Two details are load-bearing:

**The transport is baked in** as `Environment=MCP_TRANSPORT=…`, from the value
`agentihooks init` validated. This is what stops the daemon and `~/.claude.json`
from disagreeing about which protocol is in play. Transport is an install-time
decision — changing it must rewrite the url too — so it belongs to `init`, not
to a runtime edit.

**There is deliberately no `EnvironmentFile=`.** systemd's parser is not a
shell: it does not strip an `export ` prefix, so `export MCP_TRANSPORT=sse`
would set a key literally named `export MCP_TRANSPORT` and leave the real one
unset. The daemon does not need it anyway — `hooks/config.py` parses
`~/.agentihooks/.env` itself at import, handling `export`, quotes and inline
comments. It parses with `os.environ.setdefault`, so anything systemd injected
would take precedence over the correctly-parsed value.

Every other knob (`MCP_CATEGORIES`, `MCP_HOST`, `MCP_PORT`, …) is an edit to
`~/.agentihooks/.env` plus `systemctl --user restart agentihooks-mcp.service`.

Where there is no systemd user session — WSL2 without `systemd=true`, a
container, macOS — `init` writes the unit, says so, and tells you to run the
daemon directly:

```bash
MCP_TRANSPORT=streamable-http python -m hooks.mcp
```

## Verifying it works

```bash
# is anything listening
ss -ltn | grep 8642

# real MCP handshake — expect 12 tools, each session-scoped one carrying session_id
curl -s -X POST http://127.0.0.1:8642/mcp \
  -H 'content-type: application/json' \
  -H 'accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'

journalctl --user -u agentihooks-mcp.service -f
```

In a live session, `pool_status("<what you are doing>", session_id="<your id>")`
should return success, and a call with the argument omitted should return
`no session id resolvable` — that error is the guard working, not a fault.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `MCP_TRANSPORT` | `stdio` | `stdio`, `sse`, or `streamable-http`. An unrecognised value warns and falls back to stdio. |
| `MCP_HOST` | `127.0.0.1` | Bind address. Widening this removes the only access boundary. |
| `MCP_PORT` | `8642` | Bind port. |
| `MCP_SSE_PATH` | `/sse` | SSE event-stream path. |
| `MCP_STREAMABLE_HTTP_PATH` | `/mcp` | streamable-http endpoint path. |
| `MCP_STATELESS_HTTP` | `false` | Stateless mode. Only relevant behind a non-sticky reverse proxy. |
| `MCP_SESSION_ID_BANNER_ENABLED` | `true` | Tell the agent its own session id at SessionStart. |
| `AGENTIHOOKS_MCP_TRANSPORT` | -- | Installer-only override of `MCP_TRANSPORT`, for a one-off `agentihooks init` without editing `.env`. |
