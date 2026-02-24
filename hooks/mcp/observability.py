"""Metrics, logging, and container log tailing MCP tools."""

import json
import uuid
from datetime import datetime, timezone
from typing import Dict, Optional

from hooks.common import log

# Module-level state for timers and collectors
_active_timers: Dict[str, dict] = {}
_active_collectors: Dict[str, object] = {}  # MetricsCollector instances


def register(mcp):
    @mcp.tool()
    def metrics_start_timer(name: str = "") -> str:
        """Start a named timer for measuring elapsed time.

        Args:
            name: Optional name for this timer (default: auto-generated UUID)

        Returns:
            JSON with timer_id and started_at timestamp
        """
        try:
            timer_id = name if name else str(uuid.uuid4())[:8]
            started_at = datetime.now(timezone.utc).isoformat()

            _active_timers[timer_id] = {
                "started_at": started_at,
                "start_time": datetime.now(timezone.utc).timestamp(),
            }

            return json.dumps(
                {
                    "success": True,
                    "timer_id": timer_id,
                    "started_at": started_at,
                }
            )

        except Exception as e:
            log("MCP metrics_start_timer failed", {"name": name, "error": str(e)})
            return json.dumps({"success": False, "error": str(e)})

    @mcp.tool()
    def metrics_stop_timer(timer_id: str) -> str:
        """Stop a timer and get elapsed time.

        Args:
            timer_id: Timer ID from metrics_start_timer

        Returns:
            JSON with elapsed_ms and elapsed_s
        """
        try:
            if timer_id not in _active_timers:
                return json.dumps(
                    {
                        "success": False,
                        "error": f"Timer '{timer_id}' not found. Active timers: {list(_active_timers.keys())}",
                    }
                )

            timer_data = _active_timers.pop(timer_id)
            elapsed_s = datetime.now(timezone.utc).timestamp() - timer_data["start_time"]
            elapsed_ms = elapsed_s * 1000

            return json.dumps(
                {
                    "success": True,
                    "timer_id": timer_id,
                    "started_at": timer_data["started_at"],
                    "elapsed_ms": round(elapsed_ms, 2),
                    "elapsed_s": round(elapsed_s, 4),
                }
            )

        except Exception as e:
            log("MCP metrics_stop_timer failed", {"timer_id": timer_id, "error": str(e)})
            return json.dumps({"success": False, "error": str(e)})

    @mcp.tool()
    def metrics_create_collector(name: str = "default") -> str:
        """Create or get a metrics collector for aggregating multiple measurements.

        Args:
            name: Name for this collector (default: "default")

        Returns:
            JSON with collector name and count of existing metrics
        """
        try:
            from hooks.observability.metrics import MetricsCollector

            if name not in _active_collectors:
                _active_collectors[name] = MetricsCollector(name)

            collector = _active_collectors[name]

            return json.dumps(
                {
                    "success": True,
                    "name": name,
                    "metrics_count": len(collector.metrics),
                }
            )

        except Exception as e:
            log("MCP metrics_create_collector failed", {"name": name, "error": str(e)})
            return json.dumps({"success": False, "error": str(e)})

    @mcp.tool()
    def metrics_get_summary(collector_name: str = "default") -> str:
        """Get aggregated summary from a metrics collector.

        Args:
            collector_name: Name of the collector (default: "default")

        Returns:
            JSON with count, avg_ms, p95_ms, p99_ms, success_rate, etc.
        """
        try:
            if collector_name not in _active_collectors:
                return json.dumps(
                    {
                        "success": False,
                        "error": f"Collector '{collector_name}' not found. Available: {list(_active_collectors.keys())}",
                    }
                )

            collector = _active_collectors[collector_name]
            summary = collector.summary()

            return json.dumps(
                {
                    "success": True,
                    "name": collector_name,
                    "summary": summary.to_dict(),
                }
            )

        except Exception as e:
            log("MCP metrics_get_summary failed", {"collector_name": collector_name, "error": str(e)})
            return json.dumps({"success": False, "error": str(e)})

    @mcp.tool()
    def log_message(message: str, payload: str = "{}") -> str:
        """Write a log entry to the hooks log file.

        Args:
            message: Log message
            payload: JSON string with additional data (default: {})

        Returns:
            JSON with logged status and timestamp
        """
        try:
            payload_dict = json.loads(payload) if payload else {}
            timestamp = datetime.now(timezone.utc).isoformat()

            log(message, payload_dict)

            return json.dumps(
                {
                    "success": True,
                    "logged": True,
                    "timestamp": timestamp,
                    "message": message,
                }
            )

        except json.JSONDecodeError as e:
            return json.dumps(
                {
                    "success": False,
                    "error": f"Invalid JSON payload: {str(e)}",
                }
            )
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})

    @mcp.tool()
    def log_command_output(script_name: str, output: str) -> str:
        """Log command output in readable format.

        Only logs if LOG_HOOKS_COMMANDS=true is set.

        Args:
            script_name: Name of the script/command
            output: Command output to log

        Returns:
            JSON with logged status
        """
        try:
            from hooks.common import log_command

            log_command(script_name, output)

            return json.dumps(
                {
                    "success": True,
                    "logged": True,
                    "script_name": script_name,
                    "output_length": len(output),
                }
            )

        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})

    @mcp.tool()
    def tail_container_logs(
        runtime: str,
        target: str,
        follow: bool = False,
        limit_lines: int = 200,
        since: Optional[str] = None,
        filter_regex: Optional[str] = None,
        namespace: Optional[str] = None,
        container: Optional[str] = None,
        cluster: Optional[str] = None,
        log_group: Optional[str] = None,
        region: Optional[str] = None,
    ) -> str:
        """Tail logs from a container across Docker, Kubernetes, or AWS ECS.

        Args:
            runtime: REQUIRED - 'docker', 'k8s', or 'ecs'
            target: REQUIRED - Container ID/name, pod name, or task ARN
            follow: Stream logs continuously (default: False for last N lines)
            limit_lines: Number of recent lines to show (default: 200)
            since: Time duration (e.g., '10m', '1h')
            filter_regex: Client-side regex filter for log lines
            namespace: (K8s only) Kubernetes namespace (default: 'default')
            container: (K8s only) Container name in pod (if multi-container)
            cluster: (ECS only) REQUIRED - ECS cluster name
            log_group: (ECS only) REQUIRED - CloudWatch log group
            region: (ECS only) AWS region (optional)

        Returns:
            JSON with logs list and count
        """
        try:
            from hooks.observability.container_logs import ContainerLogTailer

            kwargs = {}
            if namespace:
                kwargs["namespace"] = namespace
            if container:
                kwargs["container"] = container
            if cluster:
                kwargs["cluster"] = cluster
            if log_group:
                kwargs["log_group"] = log_group
            if region:
                kwargs["region"] = region

            tailer = ContainerLogTailer(runtime, target, **kwargs)
            logs = tailer.tail(
                follow=follow,
                limit_lines=limit_lines,
                since=since,
                filter_regex=filter_regex,
            )

            return json.dumps(
                {
                    "success": True,
                    "logs": logs,
                    "count": len(logs),
                    "runtime": runtime,
                    "target": target,
                }
            )

        except ValueError as e:
            log("MCP tail_container_logs validation failed", {"error": str(e)})
            return json.dumps({"success": False, "error": str(e)})

        except FileNotFoundError as e:
            log("MCP tail_container_logs command not found", {"error": str(e)})
            return json.dumps({"success": False, "error": str(e)})

        except Exception as e:
            log("MCP tail_container_logs failed", {"error": str(e)})
            return json.dumps({"success": False, "error": str(e)})
