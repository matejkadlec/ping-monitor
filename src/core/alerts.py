"""
When to tell the user that the tray server is failing or healthy again.

* "failing" once per incident, and only when a problem ping (lost or above the
  degraded threshold) arrives while alerts are allowed: at most one "failing"
  per ``alert_gap_s``, and none during quiet periods (app start, waking from
  sleep: Wi-Fi needs a few seconds). A blocked alert is not dropped: it comes
  as soon as the server keeps having problems after the block.
* "healthy again" once the health is back to healthy and the last problem ping
  is at least ``recovery_hold_s`` old, so a server flapping around the 3-hit
  rule does not produce a pair of notifications every few minutes.

The state machine runs even while notifications are turned off, so turning
them on later never produces a stray "healthy again".
"""

from enum import Enum

from src.core.models import HealthStatus

ALERT_GAP_S = 300.0
RECOVERY_HOLD_S = 60.0
STARTUP_QUIET_S = 60.0
WAKE_QUIET_S = 60.0
WAKE_GAP_S = 30.0  # a "system" gap at least this long means the PC was asleep


class Alert(Enum):
    FAILING = "failing"
    RECOVERED = "recovered"


class HealthAlerts:
    def __init__(self, alert_gap_s: float = ALERT_GAP_S, recovery_hold_s: float = RECOVERY_HOLD_S) -> None:
        self.alert_gap_s = alert_gap_s
        self.recovery_hold_s = recovery_hold_s
        self._alerted = False  # told "failing", not yet told "healthy again"
        self._last_alert = float("-inf")
        self._last_problem = float("-inf")
        self._quiet_until = float("-inf")

    @property
    def alerted(self) -> bool:
        return self._alerted

    def reset(self) -> None:
        """Another server drives the tray now (or its metrics were reset): start over silently."""
        self._alerted = False
        self._last_problem = float("-inf")

    def quiet(self, now: float, seconds: float) -> None:
        """No "failing" alert for problems before ``now + seconds``."""
        self._quiet_until = max(self._quiet_until, now + seconds)

    def update(self, status: HealthStatus, now: float, problem: bool) -> Alert | None:
        """Feed the tray server's health after each of its pings (``problem``: this
        ping was lost or above the degraded threshold)."""
        if problem:
            self._last_problem = now
        if status is HealthStatus.FAILING:
            blocked_until = max(self._quiet_until, self._last_alert + self.alert_gap_s)
            if not self._alerted and now >= blocked_until and self._last_problem >= blocked_until:
                self._alerted = True
                self._last_alert = now
                return Alert.FAILING
            return None
        if status is HealthStatus.HEALTHY and self._alerted:
            if now - self._last_problem >= self.recovery_hold_s:
                self._alerted = False
                return Alert.RECOVERED
        return None
