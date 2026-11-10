import threading
import time

from src.core.engine import PingEngine, slot_index_after, timeout_for_interval
from src.core.models import PingReply, PingStatus, ServerSpec


class Collector:
    def __init__(self):
        self.results = []
        self.lock = threading.Lock()
        self.event = threading.Event()

    def __call__(self, result):
        with self.lock:
            self.results.append(result)
        self.event.set()

    def for_server(self, name):
        with self.lock:
            return [r for r in self.results if r.server == name]

    def wait_for(self, predicate, timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self.lock:
                if predicate(list(self.results)):
                    return True
            time.sleep(0.01)
        return False


class FakePinger:
    def __init__(self, delays=None, rtt=12):
        self.delays = delays or {}
        self.rtt = rtt
        self.calls = 0
        self.closed = False

    def ping(self, host, timeout_ms):
        self.calls += 1
        delay = self.delays.get(self.calls, 0)
        if delay:
            time.sleep(delay)
        return PingReply(PingStatus.OK, self.rtt)

    def close(self):
        self.closed = True


def test_helpers():
    assert timeout_for_interval(1) == 900
    assert timeout_for_interval(0.1) == 500
    assert timeout_for_interval(60) == 4000
    assert slot_index_after(10.0, 1.0) == 11
    assert slot_index_after(10.4, 0.5) == 21


def test_first_ping_is_immediate_then_on_grid():
    collector = Collector()
    engine = PingEngine(collector, interval_s=0.1, pinger_factory=FakePinger)
    engine.set_servers([ServerSpec("a.com", "1.1.1.1")])
    started = time.time()
    engine.start()
    try:
        assert collector.wait_for(lambda rs: len(rs) >= 1, 1.0)
        first = collector.for_server("a.com")[0]
        assert first.timestamp.timestamp() - started < 0.05
        assert collector.wait_for(lambda rs: len(rs) >= 8, 3.0)
    finally:
        engine.stop()
    stamps = [r.epoch for r in collector.for_server("a.com")][1:]
    # every later ping is sent right after a 100 ms grid point and none is skipped
    for value in stamps:
        assert 0 <= value - (value // 0.1) * 0.1 < 0.05
    steps = [round((b - a) / 0.1) for a, b in zip(stamps, stamps[1:])]
    assert all(step == 1 for step in steps)


def test_servers_are_pinged_in_parallel():
    collector = Collector()
    engine = PingEngine(collector, interval_s=0.2, pinger_factory=FakePinger)
    engine.set_servers([ServerSpec(f"s{i}.com", f"10.0.0.{i}") for i in range(3)])
    engine.start()
    try:
        assert collector.wait_for(lambda rs: len(rs) >= 12, 3.0)
    finally:
        engine.stop()
    by_slot = {}
    for result in collector.results[3:]:
        by_slot.setdefault(round(result.epoch / 0.2), set()).add(result.server)
    full_slots = [servers for servers in by_slot.values() if len(servers) == 3]
    assert full_slots, "all servers should share the same slots"


def test_stall_is_reported_as_gap_not_as_fake_pings():
    collector = Collector()
    pinger = FakePinger(delays={3: 0.75})  # third ping call blocks for 7+ slots
    engine = PingEngine(collector, interval_s=0.1, pinger_factory=lambda: pinger)
    engine.set_servers([ServerSpec("a.com", "1.1.1.1")])
    engine.start()
    try:
        assert collector.wait_for(lambda rs: any(r.status is PingStatus.GAP for r in rs), 3.0)
        assert collector.wait_for(lambda rs: len(rs) >= 8, 3.0)
    finally:
        engine.stop()
    results = collector.for_server("a.com")
    gaps = [r for r in results if r.status is PingStatus.GAP]
    stall_gaps = [g for g in gaps if 0.5 <= g.gap_seconds <= 0.8]
    assert len(stall_gaps) == 1
    # the stalled call keeps its send time; nothing is invented in between
    gap = stall_gaps[0]
    assert gap.detail == "slow-call"
    index = results.index(gap)
    before, after = results[index - 1], results[index + 1]
    assert before.status is PingStatus.OK and after.status is PingStatus.OK
    covered = after.epoch - before.epoch
    assert gap.gap_seconds <= covered <= gap.gap_seconds + 0.3
    assert pinger.closed


def test_set_servers_keeps_unchanged_workers_and_drops_stale_results():
    collector = Collector()
    engine = PingEngine(collector, interval_s=0.05, pinger_factory=FakePinger)
    engine.set_servers([ServerSpec("a.com", "1.1.1.1"), ServerSpec("b.com", "2.2.2.2")])
    engine.start()
    try:
        assert collector.wait_for(lambda rs: len(rs) >= 6, 2.0)
        worker_a = engine._workers["a.com"]
        engine.set_servers([ServerSpec("a.com", "1.1.1.1"), ServerSpec("c.com", "3.3.3.3")])
        assert engine._workers["a.com"] is worker_a
        assert engine.server_names() == ["a.com", "c.com"]
        cutoff = len(collector.results)
        assert collector.wait_for(lambda rs: len(rs) >= cutoff + 8, 2.0)
        time.sleep(0.1)
        later = collector.results[cutoff + 2:]
        assert not any(r.server == "b.com" for r in later)
        assert any(r.server == "c.com" for r in later)
    finally:
        engine.stop()
    assert engine.server_names() == ["a.com", "c.com"]  # kept for a later start()


def test_pause_and_interval_change():
    collector = Collector()
    engine = PingEngine(collector, interval_s=0.05, pinger_factory=FakePinger)
    engine.set_servers([ServerSpec("a.com", "1.1.1.1")])
    engine.start()
    try:
        assert collector.wait_for(lambda rs: len(rs) >= 3, 2.0)
        engine.set_paused(True)
        time.sleep(0.15)
        count = len(collector.results)
        time.sleep(0.3)
        assert len(collector.results) == count
        engine.set_paused(False)
        engine.set_interval(0.2)
        assert collector.wait_for(lambda rs: len(rs) >= count + 3, 2.0)
    finally:
        engine.stop()
    assert not any(r.status is PingStatus.GAP for r in collector.results)


def test_pinger_exception_becomes_error_result():
    class Exploding(FakePinger):
        def ping(self, host, timeout_ms):
            raise RuntimeError("boom")

    collector = Collector()
    engine = PingEngine(collector, interval_s=0.05, pinger_factory=Exploding)
    engine.set_servers([ServerSpec("a.com", "1.1.1.1")])
    engine.start()
    try:
        assert collector.wait_for(lambda rs: len(rs) >= 3, 2.0)
    finally:
        engine.stop()
    assert all(r.status is PingStatus.ERROR and "boom" in r.detail for r in collector.results)


def test_watchdog_restarts_dead_worker():
    collector = Collector()
    engine = PingEngine(collector, interval_s=0.05, pinger_factory=FakePinger)
    engine.set_servers([ServerSpec("a.com", "1.1.1.1")])
    engine.start()
    try:
        old = engine._workers["a.com"]
        old.stop()  # simulate a dead thread
        old.thread.join(1)
        assert engine.check_workers() == []
        assert engine._workers["a.com"] is not old
        count = len(collector.results)
        assert collector.wait_for(lambda rs: len(rs) >= count + 2, 2.0)
    finally:
        engine.stop()


def test_no_stale_results_after_set_servers_returns():
    release = threading.Event()

    class Blocking(FakePinger):
        def ping(self, host, timeout_ms):
            if host == "2.2.2.2":
                release.wait(2)
            return PingReply(PingStatus.OK, 5)

    collector = Collector()
    engine = PingEngine(collector, interval_s=0.05, pinger_factory=Blocking)
    engine.set_servers([ServerSpec("a.com", "1.1.1.1"), ServerSpec("b.com", "2.2.2.2")])
    engine.start()
    try:
        assert collector.wait_for(lambda rs: any(r.server == "a.com" for r in rs), 2.0)
        time.sleep(0.05)  # b.com is now blocked inside its ping call
        engine.set_servers([ServerSpec("a.com", "1.1.1.1")])
        cutoff = len(collector.results)
        release.set()
        time.sleep(0.3)
        assert not any(r.server == "b.com" for r in collector.results[cutoff:])
    finally:
        release.set()
        engine.stop()


def test_stop_then_start_resumes_the_same_servers():
    collector = Collector()
    engine = PingEngine(collector, interval_s=0.05, pinger_factory=FakePinger)
    engine.set_servers([ServerSpec("a.com", "1.1.1.1")])
    engine.start()
    assert collector.wait_for(lambda rs: len(rs) >= 2, 2.0)
    engine.stop()
    count = len(collector.results)
    time.sleep(0.2)
    assert len(collector.results) == count
    engine.start()
    try:
        assert collector.wait_for(lambda rs: len(rs) >= count + 2, 2.0)
    finally:
        engine.stop()


def test_one_missed_slot_is_reported_too():
    collector = Collector()
    pinger = FakePinger(delays={3: 0.45})  # ~1.25 slots late at a 200 ms interval
    engine = PingEngine(collector, interval_s=0.2, pinger_factory=lambda: pinger)
    engine.set_servers([ServerSpec("a.com", "1.1.1.1")])
    engine.start()
    try:
        assert collector.wait_for(lambda rs: len(rs) >= 6, 3.0)
    finally:
        engine.stop()
    results = collector.for_server("a.com")
    gaps = [r for r in results if r.status is PingStatus.GAP]
    assert gaps and 0.2 <= gaps[0].gap_seconds <= 0.4
    # never two pings within half an interval of each other
    pings = [r.epoch for r in results if r.status is PingStatus.OK]
    assert all(b - a > 0.1 for a, b in zip(pings, pings[1:]))
