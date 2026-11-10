"""
Health of a server: Healthy, Degraded or Failing, with the reasons.

It looks at the pings of the last few minutes (at least 3 minutes and at least
20 pings, so a long ping interval still has enough data) and at what a player
would notice:

* Failing - the connection is unusable right now:
  * an outage: the newest 3 pings were all lost (or 2 that span 10 s or more)
  * 10 % or more of the pings were lost (at least 3)
  * 20 % or more of the replies were spikes above the degraded threshold (at least 3)
  * jitter of at least half the degraded threshold (ping swinging wildly)
* Degraded - usable, but noticeably worse:
  * 2 % or more of the pings were lost (at least 3)
  * 10 % or more of the replies were above the healthy threshold (at least 3)
  * 3 or more spikes above the degraded threshold
  * jitter of at least half the healthy threshold
* Healthy otherwise - a single lost ping or spike never changes the status.

Each ping costs O(1): the window keeps running counts. Time uses epochs, so
daylight-saving changes cannot distort the window.
"""

from collections import deque
from dataclasses import dataclass, field

from src.core.models import HealthStatus, PingResult, PingStatus

MIN_WINDOW_SECONDS = 180.0
MIN_WINDOW_PINGS = 20
MIN_EVENTS = 3  # rates need at least this many lost pings / slow replies
OUTAGE_PINGS = 3
OUTAGE_SECONDS = 10.0
FAILING_LOSS = 0.10
DEGRADED_LOSS = 0.02
FAILING_SPIKE_SHARE = 0.20
DEGRADED_SLOW_SHARE = 0.10
DEGRADED_SPIKES = 3
MIN_JITTER_PAIRS = 5


@dataclass(frozen=True, slots=True)
class HealthReport:
    status: HealthStatus
    reasons: tuple[str, ...] = field(default_factory=tuple)  # why it is not healthy, worst first

    def summary(self) -> str:
        return ", ".join(self.reasons)


class HealthWindow:
    def __init__(self, healthy_ms: int, degraded_ms: int, interval_s: float = 1.0) -> None:
        self._healthy = healthy_ms
        self._degraded = degraded_ms
        self._interval = max(1.0, float(interval_s))
        # (epoch, rtt or None when lost, |rtt - previous reply| or None)
        self._pings: deque[tuple[float, int | None, int | None]] = deque()
        self._lost = 0
        self._slow = 0  # replies above the healthy threshold
        self._spikes = 0  # replies above the degraded threshold
        self._jitter_sum = 0
        self._jitter_pairs = 0
        self._last_rtt: int | None = None
        self._streak = 0  # newest pings lost in a row
        self._streak_start: float | None = None

    # ----------------------------------------------------------- settings
    def window_seconds(self) -> float:
        return max(MIN_WINDOW_SECONDS, MIN_WINDOW_PINGS * self._interval)

    def set_interval(self, interval_s: float) -> None:
        self._interval = max(1.0, float(interval_s))
        if self._pings:
            self._trim(self._pings[-1][0])

    def set_thresholds(self, healthy_ms: int, degraded_ms: int) -> None:
        self._healthy, self._degraded = healthy_ms, degraded_ms
        rtts = [rtt for _, rtt, _ in self._pings if rtt is not None]
        self._slow = sum(rtt > healthy_ms for rtt in rtts)
        self._spikes = sum(rtt > degraded_ms for rtt in rtts)

    def reset(self) -> None:
        self.__init__(self._healthy, self._degraded, self._interval)

    # -------------------------------------------------------------- update
    def add(self, result: PingResult) -> None:
        if result.status is PingStatus.GAP:
            return  # no samples: says nothing about the connection
        epoch = result.epoch
        if result.status is PingStatus.OK and result.rtt_ms is not None:
            rtt = result.rtt_ms
            delta = abs(rtt - self._last_rtt) if self._last_rtt is not None else None
            if delta is not None:
                self._jitter_sum += delta
                self._jitter_pairs += 1
            self._last_rtt = rtt
            self._slow += rtt > self._healthy
            self._spikes += rtt > self._degraded
            self._streak, self._streak_start = 0, None
            self._pings.append((epoch, rtt, delta))
        else:
            self._lost += 1
            if self._streak == 0:
                self._streak_start = epoch
            self._streak += 1
            self._pings.append((epoch, None, None))
        self._trim(epoch)

    def _trim(self, now: float) -> None:
        cutoff = now - self.window_seconds()
        pings = self._pings
        while pings and pings[0][0] < cutoff:
            _, rtt, delta = pings.popleft()
            if rtt is None:
                self._lost -= 1
            else:
                self._slow -= rtt > self._healthy
                self._spikes -= rtt > self._degraded
            if delta is not None:
                self._jitter_sum -= delta
                self._jitter_pairs -= 1
        if not pings:
            self._last_rtt = None

    # --------------------------------------------------------------- query
    def report(self) -> HealthReport:
        total = len(self._pings)
        if not total:
            return HealthReport(HealthStatus.UNKNOWN)
        replies = total - self._lost
        loss = self._lost / total
        slow_share = self._slow / replies if replies else 0.0
        spike_share = self._spikes / replies if replies else 0.0
        jitter = self._jitter_sum / self._jitter_pairs if self._jitter_pairs >= MIN_JITTER_PAIRS else None
        healthy, degraded = self._healthy, self._degraded

        failing: list[str] = []
        newest = self._pings[-1][0]
        streak_span = newest - self._streak_start if self._streak_start is not None else 0.0
        if self._streak >= OUTAGE_PINGS or (self._streak >= 2 and streak_span >= OUTAGE_SECONDS):
            failing.append(f"the last {self._streak} pings were lost")
        if self._lost >= MIN_EVENTS and loss >= FAILING_LOSS:
            failing.append(f"{_percent(loss)} of pings lost")
        if self._spikes >= MIN_EVENTS and spike_share >= FAILING_SPIKE_SHARE:
            failing.append(f"{_percent(spike_share)} of pings above {degraded} ms")
        if jitter is not None and jitter >= degraded / 2:
            failing.append(f"jitter {jitter:.0f} ms")
        if failing:
            return HealthReport(HealthStatus.FAILING, tuple(failing))

        degraded_reasons: list[str] = []
        if self._lost >= MIN_EVENTS and loss >= DEGRADED_LOSS:
            degraded_reasons.append(f"{_percent(loss)} of pings lost")
        if self._spikes >= DEGRADED_SPIKES:
            degraded_reasons.append(f"{self._spikes} spikes above {degraded} ms")
        elif self._slow >= MIN_EVENTS and slow_share >= DEGRADED_SLOW_SHARE:
            degraded_reasons.append(f"{_percent(slow_share)} of pings above {healthy} ms")
        if jitter is not None and jitter >= healthy / 2:
            degraded_reasons.append(f"jitter {jitter:.0f} ms")
        if degraded_reasons:
            return HealthReport(HealthStatus.DEGRADED, tuple(degraded_reasons))
        return HealthReport(HealthStatus.HEALTHY)


def _percent(share: float) -> str:
    value = share * 100
    return f"{value:.1f} %" if value < 10 else f"{value:.0f} %"
