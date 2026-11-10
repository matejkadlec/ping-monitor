"""
Plain data types shared by the ping engine, statistics and the UI.

Nothing in here depends on Qt, so the core can be unit-tested on any platform.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class PingStatus(StrEnum):
    """Outcome of one scheduled ping slot."""

    OK = "ok"
    TIMEOUT = "timeout"
    UNREACHABLE = "unreachable"
    ERROR = "error"
    # Not a ping at all: the scheduler woke up too late and some slots were
    # never measured (PC asleep, frozen, heavily loaded...).
    GAP = "gap"

    @property
    def is_lost(self) -> bool:
        """True for pings that were sent but got no usable reply."""
        return self in (PingStatus.TIMEOUT, PingStatus.UNREACHABLE, PingStatus.ERROR)


class HealthStatus(StrEnum):
    """Overall connection health of one server (drives tab dots and the tray icon)."""

    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILING = "failing"

    @property
    def label(self) -> str:
        return "Waiting" if self is HealthStatus.UNKNOWN else self.value.title()


class LatencyLevel(StrEnum):
    """Color bucket of a single result."""

    EXCELLENT = "excellent"  # <= healthy threshold (green)
    GOOD = "good"  # <= degraded threshold (yellow)
    BAD = "bad"  # above degraded threshold (red)
    LOST = "lost"  # timeout / unreachable / error (red)
    GAP = "gap"  # no measurement (grey)


@dataclass(frozen=True, slots=True)
class ServerSpec:
    """A monitored server: display name + address that is actually pinged."""

    name: str
    host: str


@dataclass(frozen=True, slots=True)
class PingReply:
    """What a pinger returns for one echo request."""

    status: PingStatus
    rtt_ms: int | None = None
    detail: str = ""


@dataclass(frozen=True, slots=True)
class PingResult:
    """One entry of the ping stream of a server."""

    server: str
    host: str
    # Send time as local wall-clock time (display only). For GAP results this
    # is the first slot that was missed.
    timestamp: datetime
    status: PingStatus
    rtt_ms: int | None = None
    detail: str = ""
    # GAP only: how many seconds of slots were skipped.
    gap_seconds: float = 0.0
    # Wall-clock duration of the ping call itself (diagnostics).
    call_ms: int = 0
    # Seconds since the epoch of ``timestamp``. All time arithmetic (windows,
    # durations, chart positions) uses this, so DST changes never distort it.
    epoch: float = 0.0

    def __post_init__(self) -> None:
        if not self.epoch:
            object.__setattr__(self, "epoch", self.timestamp.timestamp())


def classify_latency(result: PingResult, healthy_ms: int, degraded_ms: int) -> LatencyLevel:
    """Map a result to its color bucket using the configured thresholds."""
    if result.status is PingStatus.GAP:
        return LatencyLevel.GAP
    if result.status is not PingStatus.OK or result.rtt_ms is None:
        return LatencyLevel.LOST
    if result.rtt_ms <= healthy_ms:
        return LatencyLevel.EXCELLENT
    if result.rtt_ms <= degraded_ms:
        return LatencyLevel.GOOD
    return LatencyLevel.BAD


def is_problem(result: PingResult, degraded_ms: int) -> bool:
    """True for results worth recording in the ping spikes log."""
    if result.status is PingStatus.GAP:
        return False
    if result.status.is_lost:
        return True
    return result.rtt_ms is not None and result.rtt_ms > degraded_ms
