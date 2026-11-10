from src.core.alerts import Alert, HealthAlerts
from src.core.models import HealthStatus

FAILING, HEALTHY, DEGRADED = HealthStatus.FAILING, HealthStatus.HEALTHY, HealthStatus.DEGRADED
BAD, OK = True, False  # was this ping a problem (lost / above the degraded threshold)?


def run(alerts: HealthAlerts, timeline) -> list[tuple[float, Alert]]:
    return [(now, alert) for now, status, problem in timeline
            if (alert := alerts.update(status, now, problem)) is not None]


def test_one_failing_alert_per_incident_and_a_held_recovery():
    alerts = HealthAlerts(alert_gap_s=300, recovery_hold_s=60)
    timeline = [(0, HEALTHY, OK), (10, FAILING, BAD), (11, FAILING, BAD), (20, FAILING, OK),
                (300, HEALTHY, OK),  # the losses aged out of the 5-minute window
                (301, HEALTHY, OK)]
    assert run(alerts, timeline) == [(10, Alert.FAILING), (300, Alert.RECOVERED)]


def test_flapping_waits_for_a_quiet_minute_before_healthy_again():
    alerts = HealthAlerts(alert_gap_s=0, recovery_hold_s=60)
    timeline = [(0, FAILING, BAD), (30, HEALTHY, OK), (50, FAILING, BAD), (80, HEALTHY, OK),
                (100, HEALTHY, OK), (111, HEALTHY, OK)]
    assert run(alerts, timeline) == [(0, Alert.FAILING), (111, Alert.RECOVERED)]


def test_a_blocked_failing_alert_comes_when_problems_continue():
    alerts = HealthAlerts(alert_gap_s=300, recovery_hold_s=0)
    timeline = [(0, FAILING, BAD), (10, HEALTHY, OK), (60, FAILING, BAD), (200, FAILING, BAD),
                (300, FAILING, OK), (301, FAILING, BAD)]
    assert run(alerts, timeline) == [(0, Alert.FAILING), (10, Alert.RECOVERED), (301, Alert.FAILING)]


def test_a_blip_that_is_over_before_the_block_ends_is_not_announced():
    alerts = HealthAlerts(alert_gap_s=300, recovery_hold_s=0)
    timeline = [(0, FAILING, BAD), (10, HEALTHY, OK), (60, FAILING, BAD), (90, FAILING, OK),
                (310, FAILING, OK), (400, HEALTHY, OK)]
    assert run(alerts, timeline) == [(0, Alert.FAILING), (10, Alert.RECOVERED)]


def test_problems_during_a_quiet_period_are_not_announced_later():
    alerts = HealthAlerts(alert_gap_s=0, recovery_hold_s=0)
    alerts.quiet(0, 60)  # e.g. Wi-Fi reconnecting after sign-in
    timeline = [(1, FAILING, BAD), (5, FAILING, BAD), (61, FAILING, OK), (200, FAILING, OK)]
    assert run(alerts, timeline) == []
    assert run(alerts, [(201, FAILING, BAD)]) == [(201, Alert.FAILING)]  # a real outage still counts


def test_degraded_is_not_recovered_and_reset_is_silent():
    alerts = HealthAlerts(alert_gap_s=0, recovery_hold_s=0)
    assert run(alerts, [(0, FAILING, BAD), (10, DEGRADED, OK)]) == [(0, Alert.FAILING)]
    alerts.reset()
    assert not alerts.alerted
    assert run(alerts, [(200, HEALTHY, OK), (400, HEALTHY, OK)]) == []
