from src.core.alerts import Alert, HealthAlerts
from src.core.models import HealthStatus

FAILING, HEALTHY, DEGRADED = HealthStatus.FAILING, HealthStatus.HEALTHY, HealthStatus.DEGRADED


def run(alerts: HealthAlerts, timeline: list[tuple[float, HealthStatus]]) -> list[tuple[float, Alert]]:
    return [(now, alert) for now, status in timeline if (alert := alerts.update(status, now)) is not None]


def test_one_failing_alert_per_incident_and_a_held_recovery():
    alerts = HealthAlerts(alert_gap_s=300, recovery_hold_s=120)
    timeline = [(0, HEALTHY), (10, FAILING), (11, FAILING), (100, HEALTHY), (150, FAILING),  # flapping
                (160, HEALTHY), (279, HEALTHY), (281, HEALTHY), (290, HEALTHY)]
    assert run(alerts, timeline) == [(10, Alert.FAILING), (281, Alert.RECOVERED)]


def test_a_blocked_failing_alert_is_delayed_not_dropped():
    alerts = HealthAlerts(alert_gap_s=300, recovery_hold_s=0)
    timeline = [(0, FAILING), (10, HEALTHY), (60, FAILING), (200, FAILING), (300, FAILING), (301, FAILING)]
    assert run(alerts, timeline) == [(0, Alert.FAILING), (10, Alert.RECOVERED), (300, Alert.FAILING)]


def test_a_short_blip_inside_the_gap_is_not_announced():
    alerts = HealthAlerts(alert_gap_s=300, recovery_hold_s=0)
    timeline = [(0, FAILING), (10, HEALTHY), (60, FAILING), (90, HEALTHY), (400, HEALTHY)]
    assert run(alerts, timeline) == [(0, Alert.FAILING), (10, Alert.RECOVERED)]


def test_quiet_periods_delay_failing_alerts():
    alerts = HealthAlerts(alert_gap_s=0, recovery_hold_s=0)
    alerts.quiet(0, 60)
    assert run(alerts, [(5, FAILING), (59, FAILING), (61, FAILING)]) == [(61, Alert.FAILING)]


def test_degraded_does_not_count_as_recovered_and_reset_is_silent():
    alerts = HealthAlerts(alert_gap_s=0, recovery_hold_s=60)
    assert run(alerts, [(0, FAILING), (10, HEALTHY), (40, DEGRADED), (80, HEALTHY), (100, HEALTHY)]) == [
        (0, Alert.FAILING)]
    alerts.reset()
    assert not alerts.alerted
    assert run(alerts, [(200, HEALTHY), (400, HEALTHY)]) == []
