"""
Per-server ping history with rolling statistics and health evaluation.

* ``results`` holds what the log view shows: everything from the last
  ``preserved_minutes`` (or everything when preserving forever, capped for
  safety). Best/worst/average/jitter/loss/spikes describe this window and are
  maintained incrementally (O(1) per ping), so long sessions stay cheap.
* Health uses a fixed 5-minute window: a server becomes Degraded after 3 pings
  above the healthy threshold and Failing after 3 pings above the degraded
  threshold. Lost pings (timeouts, unreachable, errors) count as both.
* Session counters (pings, spikes, losses, duration) cover everything since the
  start or the last reset.

All windows use epoch seconds, so daylight-saving changes never distort them.
"""

from collections import deque
from dataclasses import dataclass

from src.core.models import HealthStatus, PingResult, PingStatus

STATUS_WINDOW_SECONDS = 5 * 60
STATUS_HIT_THRESHOLD = 3
# Hard cap for "preserve forever" (~2.3 days at one ping per second, per server).
MAX_SAMPLES = 200_000


@dataclass(frozen=True, slots=True)
class WindowStats:
    samples: int = 0  # OK + lost pings in the window (gaps excluded)
    ok: int = 0
    lost: int = 0
    spikes: int = 0
    best: int | None = None
    worst: int | None = None
    average: float | None = None
    jitter: float | None = None

    @property
    def loss_percent(self) -> float:
        return 100.0 * self.lost / self.samples if self.samples else 0.0


@dataclass(slots=True)
class SessionCounters:
    pings: int = 0
    spikes: int = 0
    lost: int = 0
    gaps: int = 0
    started_epoch: float | None = None
    last_epoch: float | None = None

    @property
    def elapsed_seconds(self) -> float:
        if self.started_epoch is None or self.last_epoch is None:
            return 0.0
        return max(0.0, self.last_epoch - self.started_epoch)


def _is_ok(result: PingResult) -> bool:
    return result.status is PingStatus.OK and result.rtt_ms is not None


class ServerHistory:
    def __init__(self, preserved_minutes: int, healthy_ms: int, degraded_ms: int) -> None:
        self._preserved_minutes = preserved_minutes
        self._healthy = healthy_ms
        self._degraded = degraded_ms
        self.results: deque[PingResult] = deque()
        self.counters = SessionCounters()
        self._reset_window()
        self._status_window: deque[PingResult] = deque()
        self._over_healthy = 0
        self._over_degraded = 0
        self._last_result: PingResult | None = None

    # --------------------------------------------------------------- settings
    @property
    def preserved_minutes(self) -> int:
        return self._preserved_minutes

    @property
    def last_result(self) -> PingResult | None:
        return self._last_result

    @property
    def thresholds(self) -> tuple[int, int]:
        return self._healthy, self._degraded

    def set_thresholds(self, healthy_ms: int, degraded_ms: int) -> None:
        if (healthy_ms, degraded_ms) == (self._healthy, self._degraded):
            return
        self._healthy = healthy_ms
        self._degraded = degraded_ms
        self._over_healthy = sum(self._is_over(r, healthy_ms) for r in self._status_window)
        self._over_degraded = sum(self._is_over(r, degraded_ms) for r in self._status_window)
        self._spikes = sum(1 for r in self.results if _is_ok(r) and r.rtt_ms > degraded_ms)

    def set_preserved_minutes(self, minutes: int) -> int:
        """Change the window; returns how many results were dropped from the front."""
        self._preserved_minutes = minutes
        return self._trim()

    # ----------------------------------------------------------------- update
    def add(self, result: PingResult) -> int:
        """Append a result; returns how many old results were dropped from the front."""
        self._append_window(result)
        self._last_result = result

        counters = self.counters
        if counters.started_epoch is None:
            counters.started_epoch = result.epoch
        counters.last_epoch = result.epoch
        if result.status is PingStatus.GAP:
            counters.gaps += 1
        else:
            counters.pings += 1
            if result.status.is_lost:
                counters.lost += 1
            elif result.rtt_ms is not None and result.rtt_ms > self._degraded:
                counters.spikes += 1
            self._status_window.append(result)
            self._over_healthy += self._is_over(result, self._healthy)
            self._over_degraded += self._is_over(result, self._degraded)

        self._trim_status_window(result.epoch)
        return self._trim()

    def reset(self) -> None:
        self.results.clear()
        self.counters = SessionCounters()
        self._reset_window()
        self._status_window.clear()
        self._over_healthy = 0
        self._over_degraded = 0
        self._last_result = None

    # ---------------------------------------------------------------- queries
    def health(self) -> HealthStatus:
        if not self._status_window:
            return HealthStatus.UNKNOWN
        if self._over_degraded >= STATUS_HIT_THRESHOLD:
            return HealthStatus.FAILING
        if self._over_healthy >= STATUS_HIT_THRESHOLD:
            return HealthStatus.DEGRADED
        return HealthStatus.HEALTHY

    def window_stats(self) -> WindowStats:
        return WindowStats(
            samples=self._ok + self._lost,
            ok=self._ok,
            lost=self._lost,
            spikes=self._spikes,
            best=self._min_queue[0][1] if self._min_queue else None,
            worst=self._max_queue[0][1] if self._max_queue else None,
            average=(self._sum / self._ok) if self._ok else None,
            jitter=(self._jitter_sum / self._jitter_pairs) if self._jitter_pairs else None,
        )

    # ------------------------------------------------------- window internals
    def _reset_window(self) -> None:
        # Parallel to ``results``: |rtt - previous OK rtt| for OK results that have
        # an OK predecessor inside the window, otherwise None.
        self._deltas: deque[int | None] = deque()
        # Parallel to ``results``: sequence number of OK results (None otherwise).
        self._seqs: deque[int | None] = deque()
        # Monotonic queues of (seq, rtt) for the sliding minimum / maximum.
        self._min_queue: deque[tuple[int, int]] = deque()
        self._max_queue: deque[tuple[int, int]] = deque()
        self._next_seq = 0
        self._ok = 0
        self._lost = 0
        self._sum = 0
        self._spikes = 0
        self._jitter_sum = 0
        self._jitter_pairs = 0
        self._last_ok_rtt: int | None = None

    def _append_window(self, result: PingResult) -> None:
        delta: int | None = None
        seq: int | None = None
        if _is_ok(result):
            rtt = result.rtt_ms
            if self._last_ok_rtt is not None:
                delta = abs(rtt - self._last_ok_rtt)
                self._jitter_sum += delta
                self._jitter_pairs += 1
            self._last_ok_rtt = rtt
            self._ok += 1
            self._sum += rtt
            if rtt > self._degraded:
                self._spikes += 1
            seq = self._next_seq
            self._next_seq += 1
            while self._min_queue and self._min_queue[-1][1] >= rtt:
                self._min_queue.pop()
            self._min_queue.append((seq, rtt))
            while self._max_queue and self._max_queue[-1][1] <= rtt:
                self._max_queue.pop()
            self._max_queue.append((seq, rtt))
        elif result.status.is_lost:
            self._lost += 1
        self.results.append(result)
        self._deltas.append(delta)
        self._seqs.append(seq)

    def _pop_window(self) -> None:
        result = self.results.popleft()
        delta = self._deltas.popleft()
        seq = self._seqs.popleft()
        if delta is not None:  # defensive: the first OK result never keeps a delta
            self._jitter_sum -= delta
            self._jitter_pairs -= 1
        if _is_ok(result):
            rtt = result.rtt_ms
            self._ok -= 1
            self._sum -= rtt
            if rtt > self._degraded:
                self._spikes -= 1
            if self._min_queue and self._min_queue[0][0] == seq:
                self._min_queue.popleft()
            if self._max_queue and self._max_queue[0][0] == seq:
                self._max_queue.popleft()
            # The next OK result measured its delta against this one: drop that pair.
            for index, candidate in enumerate(self.results):
                if _is_ok(candidate):
                    next_delta = self._deltas[index]
                    if next_delta is not None:
                        self._jitter_sum -= next_delta
                        self._jitter_pairs -= 1
                        self._deltas[index] = None
                    break
            if self._ok == 0:
                self._last_ok_rtt = None
        elif result.status.is_lost:
            self._lost -= 1

    def _trim(self) -> int:
        results = self.results
        dropped = 0
        if self._preserved_minutes > 0 and results:
            cutoff = results[-1].epoch - self._preserved_minutes * 60
            while results and results[0].epoch < cutoff:
                self._pop_window()
                dropped += 1
        while len(results) > MAX_SAMPLES:
            self._pop_window()
            dropped += 1
        return dropped

    # ------------------------------------------------------- status internals
    @staticmethod
    def _is_over(result: PingResult, threshold: int) -> bool:
        if result.status.is_lost:
            return True
        return result.rtt_ms is not None and result.rtt_ms > threshold

    def _trim_status_window(self, now_epoch: float) -> None:
        cutoff = now_epoch - STATUS_WINDOW_SECONDS
        window = self._status_window
        while window and window[0].epoch < cutoff:
            old = window.popleft()
            self._over_healthy -= self._is_over(old, self._healthy)
            self._over_degraded -= self._is_over(old, self._degraded)
