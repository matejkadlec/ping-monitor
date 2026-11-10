"""
When to tell the user that the tray server is failing or healthy again.

* "failing" once per incident; "healthy again" only after the server has stayed
  healthy for ``recovery_hold_s`` (a server flapping around the 3-hit rule does
  not produce a pair of notifications every few minutes).
* At most one "failing" per ``alert_gap_s``. A blocked alert is not dropped:
  it is announced as soon as the gap has passed if the server is still failing.
* Quiet periods (app start, waking from sleep: Wi-Fi needs a few seconds) delay
  a "failing" alert the same way.

The state machine runs even while notifications are turned off, so turning
them on later never produces a stray "healthy again".
"""

from enum import Enum

from src.core.models import HealthStatus

ALERT_GAP_S = 300.0
RECOVERY_HOLD_S = 120.0
STARTUP_QUIET_S = 60.0
WAKE_QUIET_S = 60.0


class Alert(Enum):
    FAILING = "failing"
    RECOVERED = "recovered"


class HealthAlerts:
    def __init__(self, alert_gap_s: float = ALERT_GAP_S, recovery_hold_s: float = RECOVERY_HOLD_S) -> None:
        self.alert_gap_s = alert_gap_s
        self.recovery_hold_s = recovery_hold_s
        self._alerted = False  # told "failing", not yet told "healthy again"
        self._last_alert = float("-inf")
        self._healthy_since: float | None = None
        self._quiet_until = float("-inf")

    @property
    def alerted(self) -> bool:
        return self._alerted

    def reset(self) -> None:
        """Another server drives the tray now (or its metrics were reset): start over silently."""
        self._alerted = False
        self._healthy_since = None

    def quiet(self, now: float, seconds: float) -> None:
        """No "failing" alert before ``now + seconds`` (it is delayed, not dropped)."""
        self._quiet_until = max(self._quiet_until, now + seconds)

    def update(self, status: HealthStatus, now: float) -> Alert | None:
        """Feed the tray server's health after each of its pings."""
        if status is HealthStatus.FAILING:
            self._healthy_since = None
            if (not self._alerted and now >= self._quiet_until
                    and now - self._last_alert >= self.alert_gap_s):
                self._alerted = True
                self._last_alert = now
                return Alert.FAILING
            return None
        if status is HealthStatus.HEALTHY:
            if not self._alerted:
                return None
            if self._healthy_since is None:
                self._healthy_since = now
            if now - self._healthy_since >= self.recovery_hold_s:
                self._alerted = False
                self._healthy_since = None
                return Alert.RECOVERED
            return None
        self._healthy_since = None  # degraded / unknown: not recovered yet
        return None
