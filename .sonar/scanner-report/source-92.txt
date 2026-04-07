"""
In-process Prometheus-compatible metrics for the AURA P2P network layer.

Counters are maintained in a module-level singleton and exposed at GET /metrics
in the Prometheus text exposition format (text/plain; version=0.0.4).
"""
import threading
import time
from dataclasses import dataclass, field
from typing import ClassVar


@dataclass
class _Counter:
    """Thread-safe monotonic counter."""
    _value: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def inc(self, amount: float = 1.0) -> None:
        """Increment the counter by amount."""
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


class NetworkMetrics:
    """
    Singleton holding all network-layer metrics.

    Usage:
        from backend.network.metrics import METRICS
        METRICS.messages_published.inc()
        METRICS.peers_connected.set(3)
    """

    def __init__(self) -> None:
        self._start_time = time.time()

        # ── Gauges ──────────────────────────────────────────────────────────────
        self.peers_connected = _Gauge()

        # ── Counters ────────────────────────────────────────────────────────────
        self.messages_published_total = _Counter()
        self.messages_received_total = _Counter()
        self.failed_validations_total = _Counter()
        self.bytes_sent_total = _Counter()
        self.bytes_received_total = _Counter()
        self.peer_connections_total = _Counter()   # cumulative connects
        self.peer_disconnections_total = _Counter()

    def render_prometheus(self) -> str:
        """
        Render all metrics in Prometheus text exposition format.

        Returns:
            Multi-line string suitable for the /metrics HTTP endpoint.
        """
        uptime = time.time() - self._start_time
        lines = [
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
            "# HELP aura_uptime_seconds Seconds since the AURA node started",
            "# TYPE aura_uptime_seconds gauge",
            f"aura_uptime_seconds {uptime:.1f}",
            "",
        ]
        return "\n".join(lines)


# Module-level singleton
METRICS = NetworkMetrics()
