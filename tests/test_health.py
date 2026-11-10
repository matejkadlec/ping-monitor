import random
from datetime import datetime, timedelta

from src.core.health import HealthWindow
from src.core.models import HealthStatus, PingResult, PingStatus

T0 = datetime(2026, 11, 10, 12, 0, 0)
HEALTHY, DEGRADED, FAILING = HealthStatus.HEALTHY, HealthStatus.DEGRADED, HealthStatus.FAILING


def ping(second: float, rtt: int | None) -> PingResult:
    if rtt is None:
        return PingResult("s", "1.1.1.1", T0 + timedelta(seconds=second), PingStatus.TIMEOUT)
    return PingResult("s", "1.1.1.1", T0 + timedelta(seconds=second), PingStatus.OK, rtt)


def window(rtts, start: float = 0, step: float = 1, health: HealthWindow | None = None) -> HealthWindow:
    health = health or HealthWindow(40, 60)
    for index, rtt in enumerate(rtts):
        health.add(ping(start + index * step, rtt))
    return health


def steady(count: int, rtt: int = 20) -> list[int]:
    return [rtt + (i % 3) for i in range(count)]


def test_unknown_until_the_first_ping():
    assert HealthWindow(40, 60).report().status is HealthStatus.UNKNOWN
    assert window([20]).report().status is HEALTHY


def test_single_lost_pings_on_a_good_connection_stay_healthy():
    rtts = steady(60)
    rtts[20] = rtts[45] = None  # the case from the screenshot: 2 timeouts in a minute
    assert window(rtts).report().status is HEALTHY


def test_an_outage_fails_right_away_and_leaves_degraded():
    health = window(steady(100) + [None, None])
    assert health.report().status is HEALTHY
    health.add(ping(102, None))
    report = health.report()
    assert report.status is FAILING and "the last 3 pings were lost" in report.reasons
    window(steady(5), start=103, health=health)
    report = health.report()  # back up, but 3 of 108 pings were lost recently
    assert report.status is DEGRADED and "2.8 % of pings lost" in report.reasons


def test_problems_age_out_of_the_window():
    health = window(steady(10) + [None] * 5)
    assert health.report().status is FAILING
    window(steady(10), start=15 + 181, health=health)
    assert health.report().status is HEALTHY


def test_loss_rates():
    rng = random.Random(3)
    lossy = [None if rng.random() < 0.15 else 20 for _ in range(180)]
    lossy[-3:] = [20, 20, 20]  # no outage right now
    assert window(lossy).report().status is FAILING
    some = steady(180)
    for index in (10, 60, 110, 150):  # 4 of 180 = 2.2 %
        some[index] = None
    assert window(some).report().status is DEGRADED


def test_spikes_and_slow_pings():
    rtts = steady(120)
    rtts[30] = rtts[90] = 150
    assert window(rtts).report().status is HEALTHY  # two spikes are fine
    rtts[100] = 95
    report = window(rtts).report()
    assert report.status is DEGRADED and report.reasons == ("3 spikes above 60 ms",)
    slow = [50 if i % 5 == 0 else 20 for i in range(100)]  # 20 % above 40 ms, none above 60
    assert window(slow).report().reasons == ("20 % of pings above 40 ms",)
    laggy = [70 if i % 4 == 0 else 20 for i in range(100)]  # 25 % above 60 ms
    assert window(laggy).report().status is FAILING


def test_jitter():
    shaky = [10 if i % 2 else 35 for i in range(60)]  # swings by 25 ms, never above 40
    report = window(shaky).report()
    assert report.status is DEGRADED and report.reasons == ("jitter 25 ms",)
    wild = [5 if i % 2 else 38 for i in range(60)]
    assert window(wild).report().status is FAILING


def test_long_intervals_widen_the_window_and_time_the_outage():
    health = HealthWindow(40, 60, interval_s=30)
    assert health.window_seconds() == 600
    window(steady(5) + [None, None], step=30, health=health)
    assert health.report().status is FAILING  # 2 lost pings 30 s apart: a real outage


def test_threshold_and_interval_changes_recompute():
    health = window([45, 50, 55] + steady(20))
    assert health.report().status is DEGRADED
    health.set_thresholds(60, 80)
    assert health.report().status is HEALTHY
    health.set_thresholds(30, 44)
    assert health.report().status is DEGRADED  # 3 spikes above 44 ms
    health.set_interval(60)
    assert health.window_seconds() == 1200


def test_gaps_are_ignored():
    health = window(steady(10))
    health.add(PingResult("s", "1.1.1.1", T0 + timedelta(seconds=11), PingStatus.GAP, gap_seconds=30))
    assert health.report().status is HEALTHY
