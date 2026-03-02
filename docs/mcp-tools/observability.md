---
title: Observability
nav_order: 10
---

# Observability Tools
{: .no_toc }

The Observability category provides timing utilities, metrics aggregation, structured logging, and container log tailing across Docker, Kubernetes, and AWS ECS.

## Table of contents
{: .no_toc .text-delta }

1. TOC
{:toc}

---

## Tools

| Tool | Description |
|------|-------------|
| `metrics_start_timer()` | Start a named timer |
| `metrics_stop_timer()` | Stop a timer and get elapsed time |
| `metrics_create_collector()` | Create or get a named metrics collector |
| `metrics_get_summary()` | Get aggregated stats from a collector |
| `log_message()` | Write a structured log entry |
| `log_command_output()` | Log command output (gated by env var) |
| `tail_container_logs()` | Tail logs from Docker, Kubernetes, or ECS |

---

## Tool reference

### `metrics_start_timer`

```python
metrics_start_timer(name: str = "") -> str
```

Starts a named timer. The returned `timer_id` is used to stop it.

**Returns:** JSON with `timer_id`, `started_at` (ISO 8601)

---

### `metrics_stop_timer`

```python
metrics_stop_timer(timer_id: str) -> str
```

Stops the timer and returns elapsed time.

**Returns:** JSON with `timer_id`, `started_at`, `elapsed_ms`, `elapsed_s`

---

### `metrics_create_collector`

```python
metrics_create_collector(name: str = "default") -> str
```

Creates or retrieves a named metrics collector. Multiple timers can be recorded against a single collector for aggregate statistics.

**Returns:** JSON with `name`, `metrics_count`

---

### `metrics_get_summary`

```python
metrics_get_summary(collector_name: str = "default") -> str
```

Returns aggregate statistics across all timers recorded to the collector.

**Returns:** JSON with `name`, `summary` containing:
- `count` — number of measurements
- `avg_ms` — average elapsed time
- `p95_ms` — 95th percentile
- `p99_ms` — 99th percentile
- `success_rate` — fraction of successful measurements

---

### `log_message`

```python
log_message(message: str, payload: str = "{}") -> str
```

Writes a structured log entry to the hooks log file. `payload` is a JSON string of additional fields to include.

**Returns:** JSON with `logged` (bool), `timestamp`, `message`

---

### `log_command_output`

```python
log_command_output(script_name: str, output: str) -> str
```

Logs command output. Only writes when `LOG_HOOKS_COMMANDS=true` — otherwise a no-op. Useful for conditional verbosity.

**Returns:** JSON with `logged` (bool), `script_name`, `output_length`

---

### `tail_container_logs`

```python
tail_container_logs(
    runtime: str,
    target: str,
    follow: bool = False,
    limit_lines: int = 200,
    since: str = None,
    filter_regex: str = None,
    namespace: str = None,
    container: str = None,
    cluster: str = None,
    log_group: str = None,
    region: str = None
) -> str
```

Tails logs from running containers across three runtimes.

**Returns:** JSON with `logs` (list), `count`, `runtime`, `target`

---

## Runtime target syntax

### `docker`

```python
tail_container_logs(runtime="docker", target="my-container-name")
```

Runs `docker logs` against the named container. Use `follow=True` for streaming (capped at `limit_lines`).

### `k8s` (Kubernetes)

```python
tail_container_logs(
    runtime="k8s",
    target="my-pod-name",
    namespace="production",
    container="app"   # optional: specific container in multi-container pod
)
```

Runs `kubectl logs`. `namespace` defaults to `default`.

### `ecs` (AWS ECS via CloudWatch)

```python
tail_container_logs(
    runtime="ecs",
    target="my-task-id",
    cluster="my-cluster",
    log_group="/ecs/my-service",
    region="us-east-1"
)
```

Reads CloudWatch Logs for the ECS task. `cluster`, `log_group`, and `region` are required for ECS.

---

## Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `CLAUDE_HOOK_LOG_FILE` | No | `~/.agentihooks/logs/hooks.log` | Log file path for `log_message` |
| `LOG_HOOKS_COMMANDS` | No | `false` | Enable `log_command_output` writes |
| `LOG_USE_COLORS` | No | `true` | ANSI colors in log output (disable for CloudWatch) |
