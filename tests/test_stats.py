from datetime import datetime, timedelta

from src.core.models import HealthStatus, LatencyLevel, PingResult, PingStatus, classify_latency, is_problem
from src.core.stats import MAX_SAMPLES, ServerHistory

T0 = datetime(2026, 11, 10, 12, 0, 0)


def ok(second: float, rtt: int) -> PingResult:
    return PingResult("s", "1.1.1.1", T0 + timedelta(seconds=second), PingStatus.OK, rtt)


def lost(second: float, status: PingStatus = PingStatus.TIMEOUT) -> PingResult:
    return PingResult("s", "1.1.1.1", T0 + timedelta(seconds=second), status)


def gap(second: float, seconds: float) -> PingResult:
    return PingResult("s", "1.1.1.1", T0 + timedelta(seconds=second), PingStatus.GAP, gap_seconds=seconds)


def brute_stats(history: ServerHistory, degraded: int):
    rtts = [r.rtt_ms for r in history.results if r.status is PingStatus.OK]
    lost_n = sum(1 for r in history.results if r.status.is_lost)
    jit = [abs(b - a) for a, b in zip(rtts, rtts[1:])]
    return {
        "ok": len(rtts),
        "lost": lost_n,
        "best": min(rtts) if rtts else None,
        "worst": max(rtts) if rtts else None,
        "avg": sum(rtts) / len(rtts) if rtts else None,
        "jitter": sum(jit) / len(jit) if jit else None,
        "spikes": sum(1 for r in rtts if r > degraded),
    }


def assert_matches_brute(history: ServerHistory, degraded: int):
    stats = history.window_stats()
    expected = brute_stats(history, degraded)
    assert stats.ok == expected["ok"]
    assert stats.lost == expected["lost"]
    assert stats.best == expected["best"]
    assert stats.worst == expected["worst"]
    assert stats.spikes == expected["spikes"]
    for key, value in (("avg", stats.average), ("jitter", stats.jitter)):
        if expected[key] is None:
            assert value is None
        else:
            assert abs(value - expected[key]) < 1e-9


def test_classify_and_problem():
    assert classify_latency(ok(0, 40), 40, 60) is LatencyLevel.EXCELLENT
    assert classify_latency(ok(0, 41), 40, 60) is LatencyLevel.GOOD
    assert classify_latency(ok(0, 60), 40, 60) is LatencyLevel.GOOD
    assert classify_latency(ok(0, 61), 40, 60) is LatencyLevel.BAD
    assert classify_latency(lost(0), 40, 60) is LatencyLevel.LOST
    assert classify_latency(gap(0, 3), 40, 60) is LatencyLevel.GAP
    assert is_problem(ok(0, 61), 60) and not is_problem(ok(0, 60), 60)
    assert is_problem(lost(0, PingStatus.UNREACHABLE), 60)
    assert not is_problem(gap(0, 3), 60)


def test_preserved_window_trims_by_time():
    history = ServerHistory(preserved_minutes=1, healthy_ms=40, degraded_ms=60)
    dropped = sum(history.add(ok(i, 20)) for i in range(120))
    assert dropped == 59
    assert len(history.results) == 61
    assert history.results[0].timestamp == T0 + timedelta(seconds=59)
    assert history.counters.pings == 120


def test_preserve_forever_keeps_everything():
    history = ServerHistory(preserved_minutes=-1, healthy_ms=40, degraded_ms=60)
    for i in range(1000):
        history.add(ok(i, 20))
    assert len(history.results) == 1000
    assert MAX_SAMPLES > 1000


def test_incremental_stats_match_brute_force():
    import random

    rng = random.Random(7)
    history = ServerHistory(preserved_minutes=2, healthy_ms=40, degraded_ms=60)
    second = 0.0
    for _ in range(2000):
        second += 1
        roll = rng.random()
        if roll < 0.05:
            history.add(lost(second))
        elif roll < 0.07:
            history.add(gap(second, 3))
            second += 3
        else:
            history.add(ok(second, rng.choice([5, 20, 20, 21, 35, 45, 70, 120])))
        if rng.random() < 0.2:
            assert_matches_brute(history, 60)
    assert_matches_brute(history, 60)
    history.set_preserved_minutes(1)
    assert_matches_brute(history, 60)
    history.set_thresholds(30, 40)
    assert_matches_brute(history, 40)


def test_health_comes_from_the_health_window():
    history = ServerHistory(preserved_minutes=10, healthy_ms=40, degraded_ms=60)
    assert history.health() is HealthStatus.UNKNOWN
    for i in range(30):
        history.add(ok(i, 20))
    history.add(ok(30, 75))
    history.add(ok(31, 90))
    assert history.health() is HealthStatus.HEALTHY  # two spikes are tolerated
    history.add(ok(32, 61))
    report = history.health_report()
    assert report.status is HealthStatus.DEGRADED and report.reasons == ("3 spikes above 60 ms",)


def test_an_outage_fails_and_expires():
    history = ServerHistory(preserved_minutes=10, healthy_ms=40, degraded_ms=60)
    for i in range(3):
        history.add(lost(i))
    assert history.health() is HealthStatus.FAILING
    # minutes later the losses fall out of the health window
    history.add(ok(5 * 60 + 3, 20))
    assert history.health() is HealthStatus.HEALTHY


def test_gaps_do_not_affect_stats_or_health():
    history = ServerHistory(preserved_minutes=10, healthy_ms=40, degraded_ms=60)
    history.add(gap(0, 5))
    assert history.health() is HealthStatus.UNKNOWN
    assert history.window_stats().samples == 0
    assert history.counters.gaps == 1 and history.counters.pings == 0


def test_threshold_change_recomputes():
    history = ServerHistory(preserved_minutes=10, healthy_ms=40, degraded_ms=60)
    for i, rtt in enumerate([45, 50, 55] + [20] * 20):
        history.add(ok(i, rtt))
    assert history.health() is HealthStatus.DEGRADED
    assert history.window_stats().spikes == 0
    history.set_thresholds(30, 44)
    assert history.health() is HealthStatus.DEGRADED  # now 3 spikes
    assert history.window_stats().spikes == 3
    history.set_thresholds(60, 80)
    assert history.health() is HealthStatus.HEALTHY


def test_reset_clears_everything():
    history = ServerHistory(preserved_minutes=10, healthy_ms=40, degraded_ms=60)
    for i in range(10):
        history.add(ok(i, 100))
    history.reset()
    assert not history.results
    assert history.health() is HealthStatus.UNKNOWN
    assert history.counters.pings == 0
    assert history.window_stats().ok == 0


def test_windows_use_epoch_not_local_time():
    # Autumn DST change: local time jumps back one hour while epoch keeps going.
    history = ServerHistory(preserved_minutes=10, healthy_ms=40, degraded_ms=60)
    base = T0.timestamp()
    for i in range(3):
        history.add(PingResult("s", "1.1.1.1", T0 + timedelta(seconds=i), PingStatus.TIMEOUT, epoch=base + i))
    assert history.health() is HealthStatus.FAILING
    later = base + 5 * 60 + 10  # 5 minutes later, but the local clock reads an hour earlier
    history.add(PingResult("s", "1.1.1.1", T0 - timedelta(minutes=55), PingStatus.OK, 20, epoch=later))
    assert history.health() is HealthStatus.HEALTHY
    assert len(history.results) == 4  # still inside the 10-minute window
    assert history.counters.elapsed_seconds == 5 * 60 + 10


def test_best_worst_stay_correct_with_cap(monkeypatch):
    import random

    import src.core.stats as stats_module

    monkeypatch.setattr(stats_module, "MAX_SAMPLES", 50)
    rng = random.Random(3)
    history = ServerHistory(preserved_minutes=-1, healthy_ms=40, degraded_ms=60)
    for i in range(500):
        history.add(ok(i, rng.randint(1, 200)) if rng.random() > 0.1 else lost(i))
        assert_matches_brute(history, 60)
    assert len(history.results) == 50
