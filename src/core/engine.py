"""
Drift-free ping scheduling.

Every server gets its own worker thread. Workers ping on a shared wall-clock
grid (every whole ``interval`` seconds), so all servers are pinged in parallel
and timestamps never drift or skip a second. The very first ping happens
immediately after start.

If a worker wakes up so late that whole slots were missed (PC asleep, frozen or
overloaded, or the previous ping call itself hung), it does not invent results:
it reports one ``GAP`` result that covers the missed time and continues on the
grid. Results carry their real send time.

The engine is framework agnostic: results are delivered through a callback that
is invoked from the worker threads (the Qt layer turns it into a queued signal).
Once ``set_servers``/``set_paused``/``stop`` return, the callback is no longer
invoked for removed, changed, paused or stopped workers. (Results the callback
already queued elsewhere, e.g. as Qt signals, are the consumer's to filter.)
"""

import logging
import math
import threading
import time
from collections.abc import Callable, Iterable
from datetime import datetime

from src.core.models import PingReply, PingResult, PingStatus, ServerSpec
from src.core.pinger import Pinger, create_pinger

LOGGER = logging.getLogger(__name__)

# A ping call taking this much longer than its timeout means something stalled.
STALL_GRACE_S = 1.0
# Upper bound for a single wait, keeps workers responsive to interval changes.
MAX_WAIT_S = 0.5
MIN_TIMEOUT_MS = 500
MAX_TIMEOUT_MS = 4000

GAP_REASON_SYSTEM = "system"
GAP_REASON_SLOW_CALL = "slow-call"

ResultCallback = Callable[[PingResult], None]


def timeout_for_interval(interval_s: float) -> int:
    """Echo timeout: most of the interval, so a lost packet never delays the next slot."""
    return int(min(MAX_TIMEOUT_MS, max(MIN_TIMEOUT_MS, interval_s * 1000 * 0.9)))


def slot_index_after(now: float, interval: float) -> int:
    """Index of the first grid slot strictly after ``now``."""
    return math.floor(now / interval) + 1


class _Worker:
    def __init__(self, engine: "PingEngine", server: ServerSpec) -> None:
        self.engine = engine
        self.server = server
        self.stop_event = threading.Event()
        self.thread = threading.Thread(
            target=self._run, name=f"ping:{server.name}", daemon=True
        )
        self.started = False
        self.last_activity = time.monotonic()
        self._last_call_seconds = 0.0

    def start(self) -> None:
        if not self.started:
            self.started = True
            self.last_activity = time.monotonic()
            self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()

    # ------------------------------------------------------------------ thread
    def _run(self) -> None:
        try:
            pinger = self.engine.pinger_factory()
        except Exception as error:
            LOGGER.exception("Cannot create pinger for %s", self.server.name)
            self._emit_reply(time.time(), PingReply(PingStatus.ERROR, None, f"Pinger failed: {error}"), 0)
            return
        try:
            self._loop(pinger)
        except Exception:
            LOGGER.exception("Ping worker for %s crashed", self.server.name)
        finally:
            try:
                pinger.close()
            except Exception:
                LOGGER.debug("Closing pinger failed", exc_info=True)

    def _loop(self, pinger: Pinger) -> None:
        clock = self.engine.clock
        interval = self.engine.interval
        next_index: int | None = None  # None -> ping right away

        while not self.stop_event.is_set():
            self.last_activity = time.monotonic()
            now = clock()

            current_interval = self.engine.interval
            if current_interval != interval:
                interval = current_interval
                if next_index is not None:
                    next_index = slot_index_after(now, interval)

            if self.engine.paused:
                next_index = None
                if self.stop_event.wait(MAX_WAIT_S):
                    break
                continue

            if next_index is None:
                self._ping_slot(pinger, interval)
                next_index = slot_index_after(now, interval)
                continue

            slot_time = next_index * interval
            delay = slot_time - now
            if delay > interval * 1.5:
                # Wall clock jumped backwards: re-align without reporting a gap.
                LOGGER.info("Clock moved backwards, re-aligning %s", self.server.name)
                next_index = slot_index_after(now, interval)
                continue
            if delay > 0:
                if self.stop_event.wait(min(delay, MAX_WAIT_S)):
                    break
                continue

            lateness = -delay
            skipped = int(lateness // interval)  # whole slots already in the past
            if skipped:
                # Report the missed time honestly and continue on the grid (never
                # two pings back to back to "catch up").
                self._emit_gap(slot_time, skipped * interval, lateness)
                next_index += skipped
            self._ping_slot(pinger, interval)
            next_index += 1

    def _ping_slot(self, pinger: Pinger, interval: float) -> None:
        timeout_ms = timeout_for_interval(interval)
        sent_at = self.engine.clock()
        started = time.monotonic()
        try:
            reply = pinger.ping(self.server.host, timeout_ms)
        except Exception as error:
            LOGGER.exception("Ping of %s (%s) raised", self.server.name, self.server.host)
            reply = PingReply(PingStatus.ERROR, None, str(error) or error.__class__.__name__)
        duration = time.monotonic() - started
        self.last_activity = time.monotonic()
        self._last_call_seconds = duration
        if duration > timeout_ms / 1000 + STALL_GRACE_S:
            LOGGER.warning(
                "Ping call for %s took %.2f s (timeout %d ms)", self.server.name, duration, timeout_ms
            )
        self._emit_reply(sent_at, reply, int(duration * 1000))

    def _emit_reply(self, sent_at: float, reply: PingReply, call_ms: int) -> None:
        self.engine._emit(
            self,
            PingResult(
                server=self.server.name,
                host=self.server.host,
                timestamp=datetime.fromtimestamp(sent_at),
                status=reply.status,
                rtt_ms=reply.rtt_ms,
                detail=reply.detail,
                call_ms=call_ms,
                epoch=sent_at,
            ),
        )

    def _emit_gap(self, first_missed_slot: float, gap_seconds: float, lateness: float) -> None:
        # If the previous ping call took about as long as we are late, that call
        # (e.g. a hanging DNS lookup, or the PC sleeping during it) caused the gap.
        reason = GAP_REASON_SLOW_CALL if self._last_call_seconds >= lateness else GAP_REASON_SYSTEM
        LOGGER.warning(
            "No samples for %s during %.1f s (worker %.2f s late, reason: %s)",
            self.server.name, gap_seconds, lateness, reason,
        )
        self.engine._emit(
            self,
            PingResult(
                server=self.server.name,
                host=self.server.host,
                timestamp=datetime.fromtimestamp(first_missed_slot),
                status=PingStatus.GAP,
                detail=reason,
                gap_seconds=gap_seconds,
                epoch=first_missed_slot,
            ),
        )


class PingEngine:
    """Owns the per-server workers. All public methods are thread safe."""

    def __init__(
        self,
        on_result: ResultCallback,
        interval_s: float = 1.0,
        pinger_factory: Callable[[], Pinger] = create_pinger,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if interval_s <= 0:
            raise ValueError("interval must be positive")
        self._on_result = on_result
        self.pinger_factory = pinger_factory
        self.clock = clock
        self._interval = float(interval_s)
        self._paused = False
        self._running = False
        self._workers: dict[str, _Worker] = {}
        # Re-entrant: the callback runs under the lock (see _emit).
        self._lock = threading.RLock()

    # ------------------------------------------------------------- properties
    @property
    def interval(self) -> float:
        return self._interval

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def running(self) -> bool:
        return self._running

    def server_names(self) -> list[str]:
        with self._lock:
            return list(self._workers)

    # ---------------------------------------------------------------- control
    def set_interval(self, interval_s: float) -> None:
        if interval_s <= 0:
            raise ValueError("interval must be positive")
        self._interval = float(interval_s)

    def set_paused(self, paused: bool) -> None:
        with self._lock:
            self._paused = bool(paused)

    def set_servers(self, servers: Iterable[ServerSpec]) -> None:
        """Start/stop workers so they match ``servers``; untouched servers keep running."""
        desired = {server.name: server for server in servers}
        with self._lock:
            for name, worker in list(self._workers.items()):
                wanted = desired.get(name)
                if wanted is None or wanted.host != worker.server.host:
                    worker.stop()
                    del self._workers[name]
            for name, server in desired.items():
                if name not in self._workers:
                    worker = _Worker(self, server)
                    self._workers[name] = worker
                    if self._running:
                        worker.start()

    def start(self) -> None:
        with self._lock:
            self._running = True
            for worker in self._workers.values():
                worker.start()

    def stop(self, join_timeout: float = 0.5) -> None:
        """Stop pinging. The server list is kept, so ``start()`` resumes it."""
        with self._lock:
            self._running = False
            stopped = list(self._workers.values())
            for worker in stopped:
                worker.stop()
            # Fresh, not yet started workers for the same servers.
            self._workers = {name: _Worker(self, worker.server) for name, worker in self._workers.items()}
        deadline = time.monotonic() + join_timeout
        for worker in stopped:
            if worker.started:
                worker.thread.join(max(0.0, deadline - time.monotonic()))

    def check_workers(self) -> list[str]:
        """Watchdog: restart dead workers, return names of workers that look stuck."""
        stuck: list[str] = []
        limit = max(10.0, 3 * self._interval + timeout_for_interval(self._interval) / 1000)
        now = time.monotonic()
        with self._lock:
            if not self._running:
                return stuck
            for name, worker in list(self._workers.items()):
                if worker.started and not worker.thread.is_alive():
                    LOGGER.error("Ping worker for %s died, restarting it", name)
                    replacement = _Worker(self, worker.server)
                    self._workers[name] = replacement
                    replacement.start()
                elif now - worker.last_activity > limit:
                    stuck.append(name)
        if stuck:
            LOGGER.warning("Ping workers look stuck: %s", ", ".join(stuck))
        return stuck

    # --------------------------------------------------------------- internal
    def _emit(self, worker: _Worker, result: PingResult) -> None:
        # The callback runs under the lock (it only queues a signal), so once a
        # control method returns, stale workers can no longer deliver anything.
        with self._lock:
            if not self._running or self._paused or self._workers.get(worker.server.name) is not worker:
                return
            try:
                self._on_result(result)
            except Exception:
                LOGGER.exception("Result callback failed")
