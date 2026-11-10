"""
User settings: defaults, validation and JSON persistence.

The file format is backward compatible with the pre-PySide6 ``app_config.json``
(``servers`` is still a ``{name: ip}`` object), so existing settings survive the
upgrade.
"""

import json
import logging
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any

from src.core import validation
from src.core.fileio import atomic_write_text
from src.core.models import ServerSpec
from src.core.paths import data_dir

LOGGER = logging.getLogger(__name__)

SETTINGS_FILE_NAME = "app_config.json"

DEFAULT_SERVERS: tuple[ServerSpec, ...] = (
    ServerSpec("cloudflare.com", "1.1.1.1"),
    ServerSpec("google.com", "8.8.8.8"),
    ServerSpec("seznam.cz", "77.75.77.222"),
)

# Limits shared with the config UI (tooltips + validation).
THRESHOLD_MIN, THRESHOLD_MAX = 1, 999
INTERVAL_MIN, INTERVAL_MAX = 1, 60
PRESERVED_MIN, PRESERVED_MAX = 1, 999
PRESERVE_FOREVER = -1
MAX_SERVERS = 10
MAX_NAME_LENGTH = 64


@dataclass(frozen=True, slots=True)
class FieldError:
    """A validation problem, addressed to a settings field (and table cell)."""

    field: str
    message: str
    row: int | None = None
    column: str | None = None  # "name" / "host" for server table cells


@dataclass(frozen=True, slots=True)
class Settings:
    servers: tuple[ServerSpec, ...] = DEFAULT_SERVERS
    ping_threshold_healthy: int = 40
    ping_threshold_degraded: int = 60
    ping_interval: int = 1
    preserved_minutes: int = 10
    close_to_tray: bool = True

    # ------------------------------------------------------------------ helpers
    @property
    def preserve_forever(self) -> bool:
        return self.preserved_minutes == PRESERVE_FOREVER

    def with_changes(self, **changes: Any) -> "Settings":
        return replace(self, **changes)

    def server_names(self) -> list[str]:
        return [server.name for server in self.servers]

    # --------------------------------------------------------------- validation
    def validate(self) -> list[FieldError]:
        """Strict validation used before saving from the UI."""
        errors: list[FieldError] = []

        if not self.servers:
            errors.append(FieldError("servers", "At least one server is required."))
        if len(self.servers) > MAX_SERVERS:
            errors.append(FieldError("servers", f"At most {MAX_SERVERS} servers are supported."))

        seen_names: set[str] = set()
        for row, server in enumerate(self.servers):
            name = server.name.strip()
            host = server.host.strip()
            if not name:
                errors.append(FieldError("servers", "Server name is missing.", row, "name"))
            elif len(name) > MAX_NAME_LENGTH or not validation.is_hostname(name):
                errors.append(
                    FieldError(
                        "servers",
                        f'"{name}" is not a valid server name (expected e.g. cloudflare.com).',
                        row,
                        "name",
                    )
                )
            elif name.lower() in seen_names:
                errors.append(FieldError("servers", f'Duplicate server name "{name}".', row, "name"))
            seen_names.add(name.lower())

            if not host:
                errors.append(FieldError("servers", "Server IP is missing.", row, "host"))
            elif not validation.is_ipv4(host):
                errors.append(
                    FieldError(
                        "servers",
                        f'"{host}" is not a valid IPv4 address (expected e.g. 1.1.1.1).',
                        row,
                        "host",
                    )
                )

        errors.extend(
            _range_error("ping_threshold_healthy", "Ping Threshold Healthy",
                         self.ping_threshold_healthy, THRESHOLD_MIN, THRESHOLD_MAX)
        )
        errors.extend(
            _range_error("ping_threshold_degraded", "Ping Threshold Degraded",
                         self.ping_threshold_degraded, THRESHOLD_MIN, THRESHOLD_MAX)
        )
        if (
            THRESHOLD_MIN <= self.ping_threshold_healthy <= THRESHOLD_MAX
            and THRESHOLD_MIN <= self.ping_threshold_degraded <= THRESHOLD_MAX
            and self.ping_threshold_degraded < self.ping_threshold_healthy
        ):
            errors.append(
                FieldError(
                    "ping_threshold_degraded",
                    "Ping Threshold Degraded must be greater than or equal to Ping Threshold Healthy.",
                )
            )
        errors.extend(
            _range_error("ping_interval", "Ping Interval", self.ping_interval, INTERVAL_MIN, INTERVAL_MAX)
        )
        if self.preserved_minutes != PRESERVE_FOREVER:
            errors.extend(
                _range_error("preserved_minutes", "Preserved Minutes", self.preserved_minutes,
                             PRESERVED_MIN, PRESERVED_MAX, extra=" (or -1 to keep everything)")
            )
        return errors

    # -------------------------------------------------------------- persistence
    def to_json(self) -> dict[str, Any]:
        return {
            "servers": {server.name: server.host for server in self.servers},
            "ping_threshold_healthy": self.ping_threshold_healthy,
            "ping_threshold_degraded": self.ping_threshold_degraded,
            "ping_interval": self.ping_interval,
            "preserved_minutes": self.preserved_minutes,
            "close_to_tray": self.close_to_tray,
        }

    @classmethod
    def from_json(cls, data: Any) -> "Settings":
        """Lenient loader: anything invalid falls back to its default (and is logged)."""
        defaults = cls()
        if not isinstance(data, dict):
            if data is not None:
                LOGGER.warning("Settings file does not contain an object, using defaults")
            return defaults

        servers = _load_servers(data.get("servers"), defaults.servers)
        healthy = _load_int(data, "ping_threshold_healthy", defaults.ping_threshold_healthy,
                            THRESHOLD_MIN, THRESHOLD_MAX)
        degraded = _load_int(data, "ping_threshold_degraded", defaults.ping_threshold_degraded,
                             THRESHOLD_MIN, THRESHOLD_MAX)
        if degraded < healthy:
            LOGGER.warning("Degraded threshold below healthy threshold, raising it to %s", healthy)
            degraded = healthy
        interval = _load_int(data, "ping_interval", defaults.ping_interval, INTERVAL_MIN, INTERVAL_MAX)
        if _as_int(data.get("preserved_minutes")) == PRESERVE_FOREVER:
            preserved = PRESERVE_FOREVER
        else:
            preserved = _load_int(data, "preserved_minutes", defaults.preserved_minutes,
                                  PRESERVED_MIN, PRESERVED_MAX)
        close_to_tray = data.get("close_to_tray", defaults.close_to_tray)
        if not isinstance(close_to_tray, bool):
            close_to_tray = defaults.close_to_tray

        return cls(
            servers=servers,
            ping_threshold_healthy=healthy,
            ping_threshold_degraded=degraded,
            ping_interval=interval,
            preserved_minutes=preserved,
            close_to_tray=close_to_tray,
        )


SETTING_FIELDS = tuple(field.name for field in fields(Settings))


def settings_path(directory: Path | None = None) -> Path:
    return (directory or data_dir()) / SETTINGS_FILE_NAME


def load_settings(path: Path | None = None) -> Settings:
    path = path or settings_path()
    if not path.exists():
        return Settings()
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as error:
        LOGGER.warning("Could not read settings from %s (%s), using defaults", path, error)
        return Settings()
    return Settings.from_json(data)


def save_settings(settings: Settings, path: Path | None = None) -> None:
    """Write settings atomically, so a crash never leaves half a file (raises OSError)."""
    path = path or settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(settings.to_json(), indent=2, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------- helpers
def _range_error(field: str, label: str, value: int, minimum: int, maximum: int,
                 extra: str = "") -> list[FieldError]:
    if minimum <= value <= maximum:
        return []
    return [FieldError(field, f"{label} must be between {minimum} and {maximum}{extra}.")]


def _as_int(value: Any) -> int | None:
    """Whole number from JSON (int, integral float or numeric string), else None."""
    if isinstance(value, bool):
        return None
    try:
        if isinstance(value, str):
            value = float(value.strip())
        if isinstance(value, float):
            if not value.is_integer():
                return None
            return int(value)
        if isinstance(value, int):
            return value
    except (ValueError, OverflowError):
        return None
    return None


def _load_int(data: dict, key: str, default: int, minimum: int, maximum: int) -> int:
    raw = data.get(key, default)
    number = _as_int(raw)
    if number is None:
        LOGGER.warning("Invalid %s=%r in settings, using %s", key, raw, default)
        return default
    clamped = max(minimum, min(maximum, number))
    if clamped != number:
        LOGGER.warning("%s=%s out of range, clamped to %s", key, number, clamped)
    return clamped


def _load_servers(value: Any, default: tuple[ServerSpec, ...]) -> tuple[ServerSpec, ...]:
    items: list[tuple[Any, Any]]
    if isinstance(value, dict):
        items = list(value.items())
    elif isinstance(value, list):  # tolerate [{"name": ..., "host": ...}] too
        items = [
            (entry.get("name"), entry.get("host") or entry.get("ip"))
            for entry in value
            if isinstance(entry, dict)
        ]
    else:
        if value is not None:
            LOGGER.warning("Invalid servers in settings, using defaults")
        return default

    servers: list[ServerSpec] = []
    seen: set[str] = set()
    for raw_name, raw_host in items:
        name = str(raw_name or "").strip()
        host = str(raw_host or "").strip()
        if not name or not host or name.lower() in seen:
            continue
        seen.add(name.lower())
        servers.append(ServerSpec(name, host))
    if not servers:
        LOGGER.warning("No usable servers in settings, using defaults")
        return default
    return tuple(servers[:MAX_SERVERS])
