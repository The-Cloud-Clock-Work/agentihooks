"""Tests for hooks.observability module."""

import pytest

pytestmark = pytest.mark.unit


class TestMetrics:
    """Test metrics system."""

    def test_timer_context_manager(self):
        """Timer works as context manager."""
        from hooks.observability.metrics import Timer

        timer = Timer()
        with timer:
            pass
        assert timer.elapsed_ms is not None
        assert timer.elapsed_ms >= 0

    def test_metrics_collector(self):
        """MetricsCollector records and summarizes."""
        from hooks.observability.metrics import MetricsCollector

        collector = MetricsCollector("test")
        collector.record("op1", 0.5)
        collector.record("op1", 1.0)
        collector.record("op1", 0.75)
        summary = collector.summary()
        assert summary is not None
        assert summary.count == 3

    def test_result_accumulator(self):
        """ResultAccumulator tracks success/failure."""
        from hooks.observability.metrics import ResultAccumulator

        acc = ResultAccumulator()
        acc.add_success("task_1")
        acc.add_success("task_2")
        acc.add_failure("task_3", error="test error")
        assert acc.total_count == 3
        assert acc.success_count == 2
        assert acc.failure_count == 1

    def test_timed_decorator(self):
        """@timed decorator captures timing."""
        from hooks.observability.metrics import timed

        @timed
        def fast_op():
            return 42

        result = fast_op()
        assert result == 42
