"""Metrics collection module for hooks.

General-purpose metrics collection for tests, benchmarks, and API calls.

Usage:
    from hooks.observability.metrics import MetricsCollector, Timer

    # Simple timing
    with Timer() as t:
        do_something()
    print(f"Took {t.elapsed_ms}ms")

    # Full metrics collection
    collector = MetricsCollector()
    collector.start("test_1")
    # ... do work ...
    collector.end(success=True, metadata={"tool": "CLI"})

    # Get summary
    print(collector.summary())
"""

import json
import statistics
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Union

from hooks.common import log

# =============================================================================
# DATA CLASSES
# =============================================================================


@dataclass
class Metric:
    """Single metric data point."""

    name: str
    timestamp: str
    elapsed_ms: float
    success: bool = True
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class MetricsSummary:
    """Aggregated metrics summary."""

    count: int
    success_count: int
    failure_count: int
    avg_ms: float
    min_ms: float
    max_ms: float
    median_ms: float
    p95_ms: float
    p99_ms: float
    total_ms: float
    success_rate: float
    metadata_counts: Dict[str, Dict[str, int]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


# =============================================================================
# TIMER CONTEXT MANAGER
# =============================================================================


class Timer:
    """Simple timer context manager for measuring elapsed time.

    Usage:
        with Timer() as t:
            do_something()
        print(f"Elapsed: {t.elapsed_ms}ms")

        # Or manually
        t = Timer()
        t.start()
        do_something()
        t.stop()
        print(t.elapsed_ms)
    """

    def __init__(self):
        self._start_time: Optional[float] = None
        self._end_time: Optional[float] = None

    def start(self) -> "Timer":
        """Start the timer."""
        self._start_time = time.perf_counter()
        self._end_time = None
        return self

    def stop(self) -> "Timer":
        """Stop the timer."""
        self._end_time = time.perf_counter()
        return self

    def reset(self) -> "Timer":
        """Reset the timer."""
        self._start_time = None
        self._end_time = None
        return self

    @property
    def elapsed_ms(self) -> float:
        """Get elapsed time in milliseconds."""
        if self._start_time is None:
            return 0.0
        end = self._end_time or time.perf_counter()
        return (end - self._start_time) * 1000

    @property
    def elapsed_s(self) -> float:
        """Get elapsed time in seconds."""
        return self.elapsed_ms / 1000

    def __enter__(self) -> "Timer":
        self.start()
        return self

    def __exit__(self, *args) -> None:
        self.stop()


# =============================================================================
# METRICS COLLECTOR
# =============================================================================


class MetricsCollector:
    """Collect and aggregate metrics for tests, benchmarks, or API calls.

    Usage:
        collector = MetricsCollector("evaluation")

        # Record metrics
        collector.start("test_1")
        # ... do work ...
        collector.end(success=True, metadata={"tool": "RAG"})

        collector.start("test_2")
        # ... do work ...
        collector.end(success=False, error="Timeout")

        # Get results
        print(collector.summary())
        collector.save("results.json")
    """

    def __init__(self, name: str = "metrics"):
        """
        Initialize metrics collector.

        Args:
            name: Name for this collection (used in output).
        """
        self.name = name
        self.metrics: List[Metric] = []
        self._current_name: Optional[str] = None
        self._timer = Timer()

    def start(self, name: str) -> None:
        """
        Start timing a metric.

        Args:
            name: Name/identifier for this metric.
        """
        self._current_name = name
        self._timer.start()

    def end(
        self,
        success: bool = True,
        error: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Metric:
        """
        End timing and record the metric.

        Args:
            success: Whether the operation succeeded.
            error: Error message if failed.
            metadata: Additional metadata to record.

        Returns:
            The recorded Metric.
        """
        self._timer.stop()

        metric = Metric(
            name=self._current_name or "unnamed",
            timestamp=datetime.now(timezone.utc).isoformat(),
            elapsed_ms=round(self._timer.elapsed_ms, 2),
            success=success,
            error=error,
            metadata=metadata or {},
        )

        self.metrics.append(metric)
        self._current_name = None

        return metric

    def record(
        self,
        name: str,
        elapsed_ms: float,
        success: bool = True,
        error: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Metric:
        """
        Record a metric directly without timing.

        Args:
            name: Name/identifier for this metric.
            elapsed_ms: Elapsed time in milliseconds.
            success: Whether the operation succeeded.
            error: Error message if failed.
            metadata: Additional metadata to record.

        Returns:
            The recorded Metric.
        """
        metric = Metric(
            name=name,
            timestamp=datetime.now(timezone.utc).isoformat(),
            elapsed_ms=round(elapsed_ms, 2),
            success=success,
            error=error,
            metadata=metadata or {},
        )

        self.metrics.append(metric)
        return metric

    @contextmanager
    def measure(
        self,
        name: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Iterator[Timer]:
        """
        Context manager for measuring a metric.

        Args:
            name: Name/identifier for this metric.
            metadata: Additional metadata to record.

        Yields:
            Timer instance for the measurement.

        Usage:
            with collector.measure("operation", {"type": "API"}) as t:
                do_something()
            # Metric automatically recorded
        """
        self.start(name)
        timer = self._timer
        error = None
        success = True

        try:
            yield timer
        except Exception as e:
            error = str(e)
            success = False
            raise
        finally:
            self.end(success=success, error=error, metadata=metadata)

    def summary(self) -> MetricsSummary:
        """
        Get aggregated summary of all metrics.

        Returns:
            MetricsSummary with statistics.
        """
        if not self.metrics:
            return MetricsSummary(
                count=0,
                success_count=0,
                failure_count=0,
                avg_ms=0.0,
                min_ms=0.0,
                max_ms=0.0,
                median_ms=0.0,
                p95_ms=0.0,
                p99_ms=0.0,
                total_ms=0.0,
                success_rate=0.0,
            )

        times = [m.elapsed_ms for m in self.metrics]
        sorted_times = sorted(times)
        success_count = sum(1 for m in self.metrics if m.success)

        # Calculate percentiles
        def percentile(data: List[float], p: float) -> float:
            k = (len(data) - 1) * p / 100
            f = int(k)
            c = f + 1
            if c >= len(data):
                return data[-1]
            return data[f] + (k - f) * (data[c] - data[f])

        # Count metadata values
        metadata_counts: Dict[str, Dict[str, int]] = {}
        for m in self.metrics:
            for key, value in m.metadata.items():
                if key not in metadata_counts:
                    metadata_counts[key] = {}
                str_value = str(value)
                metadata_counts[key][str_value] = metadata_counts[key].get(str_value, 0) + 1

        return MetricsSummary(
            count=len(self.metrics),
            success_count=success_count,
            failure_count=len(self.metrics) - success_count,
            avg_ms=round(statistics.mean(times), 2),
            min_ms=round(min(times), 2),
            max_ms=round(max(times), 2),
            median_ms=round(statistics.median(times), 2),
            p95_ms=round(percentile(sorted_times, 95), 2),
            p99_ms=round(percentile(sorted_times, 99), 2),
            total_ms=round(sum(times), 2),
            success_rate=round(success_count / len(self.metrics) * 100, 2),
            metadata_counts=metadata_counts,
        )

    def get_failures(self) -> List[Metric]:
        """Get all failed metrics."""
        return [m for m in self.metrics if not m.success]

    def get_by_metadata(self, key: str, value: Any) -> List[Metric]:
        """Get metrics matching metadata value."""
        return [m for m in self.metrics if m.metadata.get(key) == value]

    def clear(self) -> None:
        """Clear all recorded metrics."""
        self.metrics = []
        self._current_name = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary with summary and all metrics."""
        return {
            "name": self.name,
            "summary": self.summary().to_dict(),
            "metrics": [m.to_dict() for m in self.metrics],
        }

    def save(self, filepath: Union[str, Path]) -> None:
        """
        Save metrics to JSON file.

        Args:
            filepath: Path to save JSON file.
        """
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

        log(f"Saved metrics to {path}", {"count": len(self.metrics)})

    @classmethod
    def load(cls, filepath: Union[str, Path]) -> "MetricsCollector":
        """
        Load metrics from JSON file.

        Args:
            filepath: Path to JSON file.

        Returns:
            MetricsCollector with loaded metrics.
        """
        path = Path(filepath)

        with open(path) as f:
            data = json.load(f)

        collector = cls(data.get("name", "loaded"))
        for m in data.get("metrics", []):
            collector.metrics.append(
                Metric(
                    name=m["name"],
                    timestamp=m["timestamp"],
                    elapsed_ms=m["elapsed_ms"],
                    success=m.get("success", True),
                    error=m.get("error"),
                    metadata=m.get("metadata", {}),
                )
            )

        return collector


# =============================================================================
# RESULT ACCUMULATOR
# =============================================================================


class ResultAccumulator:
    """Accumulate results from parallel/batch operations.

    Usage:
        acc = ResultAccumulator()

        # In parallel workers
        acc.add_success("task_1", data={"result": 123})
        acc.add_failure("task_2", error="Timeout")
        acc.add_timeout("task_3")

        # Get results
        print(acc.summary())
    """

    def __init__(self, name: str = "results"):
        """
        Initialize result accumulator.

        Args:
            name: Name for this accumulation.
        """
        self.name = name
        self._results: List[Dict[str, Any]] = []
        self._start_time = time.perf_counter()

    def add_success(self, task_id: str, data: Optional[Dict[str, Any]] = None) -> None:
        """Record a successful result."""
        self._results.append(
            {
                "task_id": task_id,
                "status": "success",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "data": data or {},
            }
        )

    def add_failure(self, task_id: str, error: str, data: Optional[Dict[str, Any]] = None) -> None:
        """Record a failed result."""
        self._results.append(
            {
                "task_id": task_id,
                "status": "failure",
                "error": error,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "data": data or {},
            }
        )

    def add_timeout(self, task_id: str) -> None:
        """Record a timeout result."""
        self._results.append(
            {
                "task_id": task_id,
                "status": "timeout",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

    def add_skip(self, task_id: str, reason: str = "") -> None:
        """Record a skipped result."""
        self._results.append(
            {
                "task_id": task_id,
                "status": "skipped",
                "reason": reason,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

    @property
    def success_count(self) -> int:
        """Count of successful results."""
        return sum(1 for r in self._results if r["status"] == "success")

    @property
    def failure_count(self) -> int:
        """Count of failed results."""
        return sum(1 for r in self._results if r["status"] == "failure")

    @property
    def timeout_count(self) -> int:
        """Count of timeout results."""
        return sum(1 for r in self._results if r["status"] == "timeout")

    @property
    def total_count(self) -> int:
        """Total count of results."""
        return len(self._results)

    @property
    def elapsed_s(self) -> float:
        """Total elapsed time in seconds."""
        return time.perf_counter() - self._start_time

    def get_failures(self) -> List[Dict[str, Any]]:
        """Get all failed results."""
        return [r for r in self._results if r["status"] == "failure"]

    def get_successes(self) -> List[Dict[str, Any]]:
        """Get all successful results."""
        return [r for r in self._results if r["status"] == "success"]

    def summary(self) -> Dict[str, Any]:
        """Get summary of accumulated results."""
        return {
            "name": self.name,
            "total": self.total_count,
            "success": self.success_count,
            "failure": self.failure_count,
            "timeout": self.timeout_count,
            "success_rate": round(self.success_count / max(self.total_count, 1) * 100, 2),
            "elapsed_seconds": round(self.elapsed_s, 2),
        }

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "summary": self.summary(),
            "results": self._results,
        }

    def save(self, filepath: Union[str, Path]) -> None:
        """Save results to JSON file."""
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

        log(f"Saved results to {path}", self.summary())


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def timed(func):
    """
    Decorator to time function execution.

    Usage:
        @timed
        def my_function():
            ...

        result = my_function()
        # Logs: "my_function completed in 123.45ms"
    """
    from functools import wraps

    @wraps(func)
    def wrapper(*args, **kwargs):
        with Timer() as t:
            result = func(*args, **kwargs)
        log(f"{func.__name__} completed in {t.elapsed_ms:.2f}ms")
        return result

    return wrapper
