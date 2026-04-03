"""
Unit tests for backend.network.metrics.
Tests Prometheus metric counters, gauges, and rendering.
"""

import pytest
import threading
import time

from backend.network.metrics import (
    _Counter,
    _Gauge,
    NetworkMetrics,
)


class TestCounter:
    """Tests for _Counter."""

    def test_initial_value_is_zero(self):
        """Counter starts at 0."""
        c = _Counter()
        assert c.value == 0.0

    def test_increment_default(self):
        """inc() without args increments by 1."""
        c = _Counter()
        c.inc()
        assert c.value == 1.0

    def test_increment_by_amount(self):
        """inc(n) adds n to the counter."""
        c = _Counter()
        c.inc(5)
        assert c.value == 5.0

    def test_multiple_increments(self):
        """Multiple increments accumulate correctly."""
        c = _Counter()
        c.inc()
        c.inc()
        c.inc(10)
        assert c.value == 12.0

    def test_thread_safety(self):
        """Counter increments are thread-safe."""
        c = _Counter()
        threads = [threading.Thread(target=c.inc, args=(100,)) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert c.value == 1000.0

    def test_decimal_increments(self):
        """Counter can handle fractional values."""
        c = _Counter()
        c.inc(0.5)
        c.inc(0.5)
        assert c.value == 1.0


class TestGauge:
    """Tests for _Gauge."""

    def test_initial_value_is_zero(self):
        """Gauge starts at 0."""
        g = _Gauge()
        assert g.value == 0.0

    def test_set_absolute(self):
        """set() sets absolute value."""
        g = _Gauge()
        g.set(42)
        assert g.value == 42.0

    def test_inc_relative(self):
        """inc() increments from current value."""
        g = _Gauge()
        g.set(10)
        g.inc()
        assert g.value == 11.0

    def test_dec_relative(self):
        """dec() decrements from current value."""
        g = _Gauge()
        g.set(10)
        g.dec()
        assert g.value == 9.0

    def test_inc_by_amount(self):
        """inc(n) adds n."""
        g = _Gauge()
        g.inc(5)
        assert g.value == 5.0

    def test_dec_by_amount(self):
        """dec(n) subtracts n."""
        g = _Gauge()
        g.dec(3)
        assert g.value == -3.0

    def test_can_go_negative(self):
        """Gauge can go negative (no clamping)."""
        g = _Gauge()
        g.dec(100)
        assert g.value == -100.0

    def test_thread_safety(self):
        """Gauge operations are thread-safe."""
        g = _Gauge()
        threads = [threading.Thread(target=g.inc, args=(10,)) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert g.value == 100.0


class TestNetworkMetrics:
    """Tests for NetworkMetrics singleton."""

    def test_metrics_instance_exists(self):
        """METRICS should be a NetworkMetrics instance."""
        from backend.network.metrics import METRICS

        assert isinstance(METRICS, NetworkMetrics)

    def test_render_prometheus_contains_helpers(self):
        """Rendered output should contain HELP and TYPE lines."""
        metrics = NetworkMetrics()
        output = metrics.render_prometheus()
        assert "# HELP aura_peers_connected" in output
        assert "# TYPE aura_peers_connected gauge" in output

    def test_render_prometheus_contains_counters(self):
        """Rendered output should contain counter metrics."""
        metrics = NetworkMetrics()
        output = metrics.render_prometheus()
        assert "# TYPE aura_messages_published_total counter" in output
        assert "# TYPE aura_failed_validations_total counter" in output

    def test_render_prometheus_contains_uptime(self):
        """Rendered output should contain uptime metric."""
        metrics = NetworkMetrics()
        output = metrics.render_prometheus()
        assert "aura_uptime_seconds" in output

    def test_increment_updates_rendered_output(self):
        """After incrementing, render should reflect new value."""
        metrics = NetworkMetrics()
        metrics.messages_published_total.inc(5)
        output = metrics.render_prometheus()
        assert "aura_messages_published_total 5" in output

    def test_set_gauge_updates_rendered_output(self):
        """After setting gauge, render should reflect new value."""
        metrics = NetworkMetrics()
        metrics.peers_connected.set(3)
        output = metrics.render_prometheus()
        assert "aura_peers_connected 3" in output

    def test_bytes_metrics_present(self):
        """Bytes sent/received metrics should be present."""
        metrics = NetworkMetrics()
        output = metrics.render_prometheus()
        assert "aura_bytes_sent_total" in output
        assert "aura_bytes_received_total" in output

    def test_peer_connection_metrics_present(self):
        """Peer connection metrics should be present."""
        metrics = NetworkMetrics()
        output = metrics.render_prometheus()
        assert "aura_peer_connections_total" in output

    def test_uptime_increases_over_time(self):
        """Uptime should increase between renders."""
        metrics = NetworkMetrics()
        import re

        output1 = metrics.render_prometheus()
        match1 = re.search(r"aura_uptime_seconds ([\d.]+)", output1)
        assert match1
        initial = float(match1.group(1))
        time.sleep(0.05)  # 50ms
        output2 = metrics.render_prometheus()
        match2 = re.search(r"aura_uptime_seconds ([\d.]+)", output2)
        assert match2
        assert float(match2.group(1)) > initial
