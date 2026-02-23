"""Observability modules: logging, metrics, tracing, and container logs.

This package contains:
- transcript: Automatic transcript logging for conversation history
- metrics: Metrics collection and timing utilities
- container_logs: Unified container log tailing across Docker, K8s, and ECS
"""

from hooks.observability.transcript import (
    log_new_entries,
    get_last_position,
    save_position,
    extract_content,
)

from hooks.observability.metrics import (
    Metric,
    MetricsSummary,
    MetricsCollector,
    ResultAccumulator,
    Timer,
    timed,
)

from hooks.observability.container_logs import (
    ContainerLogTailer,
)

__all__ = [
    # Transcript
    "log_new_entries",
    "get_last_position",
    "save_position",
    "extract_content",
    # Metrics
    "Metric",
    "MetricsSummary",
    "MetricsCollector",
    "ResultAccumulator",
    "Timer",
    "timed",
    # Container Logs
    "ContainerLogTailer",
]
