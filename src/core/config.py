"""
Configuration settings for the Ping Monitor application.
"""

import json
import sys
from pathlib import Path

# Server configuration
DEFAULT_SERVERS = {
    "cloudflare.com": "1.1.1.1",
    "google.com": "8.8.8.8",
    "seznam.cz": "77.75.77.222",
}

# Ping configuration
DEFAULT_PING_THRESHOLD_HEALTHY = 40  # ms (upper bound for healthy)
DEFAULT_PING_THRESHOLD_DEGRADED = 60  # ms (upper bound for degraded)
DEFAULT_PING_INTERVAL = 1  # seconds between pings
DEFAULT_PRESERVED_MINUTES = 10  # minutes to preserve and display per tab

# UI Theme configuration
THEME = {
    "bg_color": "#0a192f",  # Dark Blue for main container
    "accent_color": "#ffffff",  # White for icons/headers
    "text_color": "#ffffff",  # White for UI labels
    "log_bg_color": "#112240",  # Darker blue-grey for measurement area
    "log_text_color": "#e6f1ff",  # Light blue-white text for log area
    "bg_highlight_color": "#233554",  # Slightly lighter blue for new pings
    "inactive_tab_bg": "#172a45",  # Slightly lighter dark blue for inactive tabs
    "inactive_tab_fg": "#8892b0",  # Grey-blue for inactive tab text
}

# App behavior configuration
# Set to None to ask user on startup. True = minimize to tray, False = exit app.
DEFAULT_CLOSE_TO_TRAY = False

# Animation settings
ANIMATION_SETTINGS = {
    "enabled": True,
    "duration": 800,  # milliseconds
    "steps": 8,
}

# Overlay effect settings
LOGS_OVERLAY_BLUR_RADIUS = 2  # Lower value = less blur

# File paths
LOGS_DIR = "logs"
PING_SPIKES_FILE = "logs/ping_spikes.log"
DEVIATIONS_FILE = PING_SPIKES_FILE  # Backward-compatible alias
ICON_FILE = "assets/icon.ico"
BACKGROUND_FILE = "assets/background.png"
RUNTIME_CONFIG_FILE = "logs/app_config.json"


def _project_root():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def _runtime_config_path():
    return _project_root() / RUNTIME_CONFIG_FILE


def _sanitize_servers(value):
    if not isinstance(value, dict):
        return dict(DEFAULT_SERVERS)

    sanitized = {}
    for key, ip in value.items():
        name = str(key).strip()
        address = str(ip).strip()
        if name and address:
            sanitized[name] = address

    return sanitized or dict(DEFAULT_SERVERS)


def _sanitize_int(value, default_value, min_value, max_value):
    try:
        as_int = int(value)
    except (TypeError, ValueError):
        return default_value
    return max(min_value, min(max_value, as_int))


def _sanitize_bool(value, default_value):
    if isinstance(value, bool):
        return value
    return default_value


def _default_runtime_config():
    return {
        "servers": dict(DEFAULT_SERVERS),
        "ping_threshold_healthy": DEFAULT_PING_THRESHOLD_HEALTHY,
        "ping_threshold_degraded": DEFAULT_PING_THRESHOLD_DEGRADED,
        "ping_interval": DEFAULT_PING_INTERVAL,
        "preserved_minutes": DEFAULT_PRESERVED_MINUTES,
        "close_to_tray": DEFAULT_CLOSE_TO_TRAY,
    }


def _sanitize_runtime_config(candidate):
    defaults = _default_runtime_config()
    source = candidate if isinstance(candidate, dict) else {}

    healthy = _sanitize_int(
        source.get("ping_threshold_healthy"),
        defaults["ping_threshold_healthy"],
        1,
        999,
    )
    degraded = _sanitize_int(
        source.get("ping_threshold_degraded"),
        defaults["ping_threshold_degraded"],
        1,
        999,
    )
    if degraded < healthy:
        degraded = healthy

    return {
        "servers": _sanitize_servers(source.get("servers")),
        "ping_threshold_healthy": healthy,
        "ping_threshold_degraded": degraded,
        "ping_interval": _sanitize_int(
            source.get("ping_interval"), defaults["ping_interval"], 1, 999
        ),
        "preserved_minutes": _sanitize_int(
            source.get("preserved_minutes"), defaults["preserved_minutes"], 1, 999
        ),
        "close_to_tray": _sanitize_bool(
            source.get("close_to_tray"), defaults["close_to_tray"]
        ),
    }


def load_runtime_config():
    path = _runtime_config_path()
    if not path.exists():
        return _default_runtime_config()

    try:
        with open(path, "r", encoding="utf-8") as file_handle:
            data = json.load(file_handle)
    except Exception:
        return _default_runtime_config()

    return _sanitize_runtime_config(data)


def save_runtime_config(runtime_config):
    sanitized = _sanitize_runtime_config(runtime_config)
    path = _runtime_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as file_handle:
        json.dump(sanitized, file_handle, indent=2, ensure_ascii=False)
    return sanitized


def get_runtime_config_snapshot():
    return {
        "servers": dict(SERVERS),
        "ping_threshold_healthy": PING_THRESHOLD_HEALTHY,
        "ping_threshold_degraded": PING_THRESHOLD_DEGRADED,
        "ping_interval": PING_INTERVAL,
        "preserved_minutes": PRESERVED_MINUTES,
        "close_to_tray": CLOSE_TO_TRAY,
    }


def apply_runtime_config(runtime_config):
    global SERVERS
    global PING_THRESHOLD_HEALTHY
    global PING_THRESHOLD_DEGRADED
    global PING_THRESHOLD
    global PING_INTERVAL
    global PRESERVED_MINUTES
    global CLOSE_TO_TRAY

    sanitized = _sanitize_runtime_config(runtime_config)

    SERVERS = dict(sanitized["servers"])
    PING_THRESHOLD_HEALTHY = sanitized["ping_threshold_healthy"]
    PING_THRESHOLD_DEGRADED = sanitized["ping_threshold_degraded"]
    PING_THRESHOLD = PING_THRESHOLD_DEGRADED  # Backward-compatible alias
    PING_INTERVAL = sanitized["ping_interval"]
    PRESERVED_MINUTES = sanitized["preserved_minutes"]
    CLOSE_TO_TRAY = sanitized["close_to_tray"]

    return sanitized


apply_runtime_config(load_runtime_config())
