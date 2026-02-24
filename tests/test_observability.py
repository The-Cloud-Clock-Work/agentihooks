"""Tests for hooks.observability module."""

import pytest

pytestmark = pytest.mark.unit


class TestMetrics:
    """Test metrics system."""

    def test_timer_context_manager(self):
        """Timer works as context manager."""
        from hooks.observability.metrics import Timer
        timer = Timer("test_op")
        with timer:
            pass
        assert timer.elapsed is not None
        assert timer.elapsed >= 0

    def test_metrics_collector(self):
        """MetricsCollector records and summarizes."""
        from hooks.observability.metrics import MetricsCollector
        collector = MetricsCollector("test")
        collector.record("op1", 0.5)
        collector.record("op1", 1.0)
        collector.record("op1", 0.75)
        summary = collector.get_summary()
        assert summary is not None

    def test_result_accumulator(self):
        """ResultAccumulator tracks success/failure."""
        from hooks.observability.metrics import ResultAccumulator
        acc = ResultAccumulator()
        acc.success()
        acc.success()
        acc.failure()
        assert acc.total == 3
        assert acc.successes == 2
        assert acc.failures == 1

    def test_timed_decorator(self):
        """@timed decorator captures timing."""
        from hooks.observability.metrics import timed

        @timed
        def fast_op():
            return 42

        result = fast_op()
        assert result == 42
