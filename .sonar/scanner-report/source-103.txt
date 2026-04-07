"""
Extended Prometheus-compatible metrics for AURA.

Includes:
- Query metrics (total, duration histogram)
- System metrics (CPU, memory)
- Carbon/SCI estimates
- Network metrics
"""

import os
import threading
import time
from dataclasses import dataclass, field
from typing import List, Tuple


@dataclass
class _Counter:
    """Thread-safe monotonic counter."""

    _value: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def inc(self, amount: float = 1.0) -> None:
        with self._lock:
            self._value += amount

    @property
    def value(self) -> float:
        with self._lock:
            return self._value


@dataclass
class _Gauge:
    """Thread-safe gauge (can go up and down)."""

    _value: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def set(self, value: float) -> None:
        with self._lock:
            self._value = value

    def inc(self, amount: float = 1.0) -> None:
        with self._lock:
            self._value += amount

    def dec(self, amount: float = 1.0) -> None:
        with self._lock:
            self._value -= amount

    @property
    def value(self) -> float:
        with self._lock:
            return self._value


@dataclass
class _Histogram:
    """
    Thread-safe histogram with configurable buckets.
    Tracks sum, count, and bucket counts for Prometheus-style histograms.
    """

    buckets: Tuple[float, ...] = (
        0.01,
        0.025,
        0.05,
        0.1,
        0.25,
        0.5,
        1.0,
        2.5,
        5.0,
        10.0,
    )
    _sum: float = 0.0
    _count: int = 0
    _bucket_counts: List[int] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self):
        if not self._bucket_counts:
            self._bucket_counts = [0] * len(self.buckets)

    def observe(self, value: float) -> None:
        with self._lock:
            self._sum += value
            self._count += 1
            for i, bucket in enumerate(self.buckets):
                if value <= bucket:
                    self._bucket_counts[i] += 1

    @property
    def sum(self) -> float:
        with self._lock:
            return self._sum

    @property
    def count(self) -> int:
        with self._lock:
            return self._count

    def get_buckets(self) -> List[Tuple[float, int]]:
        """Return list of (le, count) tuples for Prometheus format."""
        with self._lock:
            result = []
            cumulative = 0
            for i, bucket in enumerate(self.buckets):
                cumulative += self._bucket_counts[i]
                result.append((bucket, cumulative))
            result.append((float("inf"), self._count))
            return result


def _get_cpu_percent() -> float:
    """Get current CPU usage percentage."""
    try:
        import psutil

        return psutil.cpu_percent(interval=None)
    except ImportError:
        # Fallback: read from /proc/stat on Linux
        try:
            with open("/proc/stat", "r") as f:
                line = f.readline()
                parts = line.split()
                if parts[0] == "cpu":
                    idle = float(parts[4])
                    total = sum(float(p) for p in parts[1:])
                    return 100.0 * (1.0 - idle / total) if total > 0 else 0.0
        except (FileNotFoundError, ValueError, IndexError):
            pass
    return 0.0


def _get_memory_bytes() -> int:
    """Get current process memory usage in bytes."""
    try:
        import psutil

        process = psutil.Process(os.getpid())
        return process.memory_info().rss
    except ImportError:
        # Fallback: read from /proc/self/status on Linux
        try:
            with open("/proc/self/status", "r") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        parts = line.split()
                        return int(parts[1]) * 1024  # kB to bytes
        except (FileNotFoundError, ValueError, IndexError):
            pass
    return 0


class ObservabilityMetrics:
    """
    Comprehensive metrics for AURA.

    Includes query metrics, system metrics, and carbon estimates.
    """

    def __init__(self) -> None:
        self._start_time = time.time()

        # ── Query Metrics ────────────────────────────────────────────────────────
        self.queries_total = _Counter()
        self.queries_successful = _Counter()
        self.queries_failed = _Counter()
        self.query_duration_seconds = _Histogram(
            buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0)
        )

        # ── P2P Network Metrics ──────────────────────────────────────────────────
        self.peers_connected = _Gauge()
        self.messages_published_total = _Counter()
        self.messages_received_total = _Counter()
        self.failed_validations_total = _Counter()
        self.bytes_sent_total = _Counter()
        self.bytes_received_total = _Counter()
        self.peer_connections_total = _Counter()
        self.peer_disconnections_total = _Counter()

        # ── System Metrics ───────────────────────────────────────────────────────
        self.cpu_usage_percent = _Gauge()
        self.memory_usage_bytes = _Gauge()

        # ── Carbon/GreenOps Metrics ──────────────────────────────────────────────
        self.carbon_estimate_grams = _Counter()
        self.grid_intensity_gco2_kwh = _Gauge()
        self.queries_deferred_for_carbon = _Counter()

        # ── Document/Ingestion Metrics ───────────────────────────────────────────
        self.documents_ingested_total = _Counter()
        self.chunks_stored_total = _Counter()
        self.ingestion_duration_seconds = _Histogram(
            buckets=(0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0)
        )

    def update_system_metrics(self) -> None:
        """Update CPU and memory gauges with current values."""
        self.cpu_usage_percent.set(_get_cpu_percent())
        self.memory_usage_bytes.set(_get_memory_bytes())

    def record_query(self, duration_seconds: float, success: bool = True) -> None:
        """Record a query completion."""
        self.queries_total.inc()
        self.query_duration_seconds.observe(duration_seconds)
        if success:
            self.queries_successful.inc()
        else:
            self.queries_failed.inc()

    def record_carbon(self, grams: float) -> None:
        """Add carbon emissions estimate in grams CO2eq."""
        self.carbon_estimate_grams.inc(grams)

    def render_prometheus(self) -> str:
        """
        Render all metrics in Prometheus text exposition format.
        """
        # Update system metrics before rendering
        self.update_system_metrics()

        uptime = time.time() - self._start_time
        lines = []

        # ── Query Metrics ────────────────────────────────────────────────────────
        lines.extend(
            [
                "# HELP aura_queries_total Total number of queries processed",
                "# TYPE aura_queries_total counter",
                f"aura_queries_total {self.queries_total.value:.0f}",
                "",
                "# HELP aura_queries_successful_total Total successful queries",
                "# TYPE aura_queries_successful_total counter",
                f"aura_queries_successful_total {self.queries_successful.value:.0f}",
                "",
                "# HELP aura_queries_failed_total Total failed queries",
                "# TYPE aura_queries_failed_total counter",
                f"aura_queries_failed_total {self.queries_failed.value:.0f}",
                "",
                "# HELP aura_query_duration_seconds Query latency histogram",
                "# TYPE aura_query_duration_seconds histogram",
            ]
        )
        for le, count in self.query_duration_seconds.get_buckets():
            le_str = "+Inf" if le == float("inf") else f"{le}"
            lines.append(f'aura_query_duration_seconds_bucket{{le="{le_str}"}} {count}')
        lines.extend(
            [
                f"aura_query_duration_seconds_sum {self.query_duration_seconds.sum:.4f}",
                f"aura_query_duration_seconds_count {self.query_duration_seconds.count}",
                "",
            ]
        )

        # ── P2P Network Metrics ──────────────────────────────────────────────────
        lines.extend(
            [
                "# HELP aura_peers_connected Number of currently connected P2P peers",
                "# TYPE aura_peers_connected gauge",
                f"aura_peers_connected {self.peers_connected.value:.0f}",
                "",
                "# HELP aura_messages_published_total Total messages published to P2P topics",
                "# TYPE aura_messages_published_total counter",
                f"aura_messages_published_total {self.messages_published_total.value:.0f}",
                "",
                "# HELP aura_messages_received_total Total messages received from peers",
                "# TYPE aura_messages_received_total counter",
                f"aura_messages_received_total {self.messages_received_total.value:.0f}",
                "",
                "# HELP aura_failed_validations_total Envelopes rejected due to bad sig/replay/version",
                "# TYPE aura_failed_validations_total counter",
                f"aura_failed_validations_total {self.failed_validations_total.value:.0f}",
                "",
                "# HELP aura_bytes_sent_total Total bytes sent over P2P connections",
                "# TYPE aura_bytes_sent_total counter",
                f"aura_bytes_sent_total {self.bytes_sent_total.value:.0f}",
                "",
                "# HELP aura_bytes_received_total Total bytes received over P2P connections",
                "# TYPE aura_bytes_received_total counter",
                f"aura_bytes_received_total {self.bytes_received_total.value:.0f}",
                "",
                "# HELP aura_peer_connections_total Cumulative number of peer connections established",
                "# TYPE aura_peer_connections_total counter",
                f"aura_peer_connections_total {self.peer_connections_total.value:.0f}",
                "",
                "# HELP aura_peer_disconnections_total Cumulative peer disconnections",
                "# TYPE aura_peer_disconnections_total counter",
                f"aura_peer_disconnections_total {self.peer_disconnections_total.value:.0f}",
                "",
            ]
        )

        # ── System Metrics ───────────────────────────────────────────────────────
        lines.extend(
            [
                "# HELP aura_cpu_usage_percent Current CPU usage percentage",
                "# TYPE aura_cpu_usage_percent gauge",
                f"aura_cpu_usage_percent {self.cpu_usage_percent.value:.2f}",
                "",
                "# HELP aura_memory_usage_bytes Current process memory usage in bytes",
                "# TYPE aura_memory_usage_bytes gauge",
                f"aura_memory_usage_bytes {self.memory_usage_bytes.value:.0f}",
                "",
            ]
        )

        # ── Carbon/GreenOps Metrics ──────────────────────────────────────────────
        lines.extend(
            [
                "# HELP aura_carbon_estimate_grams Total estimated carbon emissions in grams CO2eq",
                "# TYPE aura_carbon_estimate_grams counter",
                f"aura_carbon_estimate_grams {self.carbon_estimate_grams.value:.4f}",
                "",
                "# HELP aura_grid_intensity_gco2_kwh Current grid carbon intensity in gCO2/kWh",
                "# TYPE aura_grid_intensity_gco2_kwh gauge",
                f"aura_grid_intensity_gco2_kwh {self.grid_intensity_gco2_kwh.value:.2f}",
                "",
                "# HELP aura_queries_deferred_for_carbon Queries deferred due to high carbon intensity",
                "# TYPE aura_queries_deferred_for_carbon counter",
                f"aura_queries_deferred_for_carbon {self.queries_deferred_for_carbon.value:.0f}",
                "",
            ]
        )

        # ── Document/Ingestion Metrics ───────────────────────────────────────────
        lines.extend(
            [
                "# HELP aura_documents_ingested_total Total documents ingested",
                "# TYPE aura_documents_ingested_total counter",
                f"aura_documents_ingested_total {self.documents_ingested_total.value:.0f}",
                "",
                "# HELP aura_chunks_stored_total Total chunks stored in vector DB",
                "# TYPE aura_chunks_stored_total counter",
                f"aura_chunks_stored_total {self.chunks_stored_total.value:.0f}",
                "",
                "# HELP aura_ingestion_duration_seconds Ingestion latency histogram",
                "# TYPE aura_ingestion_duration_seconds histogram",
            ]
        )
        for le, count in self.ingestion_duration_seconds.get_buckets():
            le_str = "+Inf" if le == float("inf") else f"{le}"
            lines.append(
                f'aura_ingestion_duration_seconds_bucket{{le="{le_str}"}} {count}'
            )
        lines.extend(
            [
                f"aura_ingestion_duration_seconds_sum {self.ingestion_duration_seconds.sum:.4f}",
                f"aura_ingestion_duration_seconds_count {self.ingestion_duration_seconds.count}",
                "",
            ]
        )

        # ── Uptime ───────────────────────────────────────────────────────────────
        lines.extend(
            [
                "# HELP aura_uptime_seconds Seconds since the AURA node started",
                "# TYPE aura_uptime_seconds gauge",
                f"aura_uptime_seconds {uptime:.1f}",
                "",
            ]
        )

        return "\n".join(lines)


# Module-level singleton
OBSERVABILITY_METRICS = ObservabilityMetrics()
