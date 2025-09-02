"""
Configuration settings for the Ping Monitor application.
"""

# Server configuration
SERVERS = {
    "cloudflare.com": "1.1.1.1",
    "google.com": "8.8.8.8",
    "seznam.cz": "77.75.77.222",
    "matejkadlec.cz": "37.9.175.163",
}

# Ping configuration
PING_THRESHOLD = 60  # ms (for deviation logging)
PING_INTERVAL = 1  # seconds between pings
PRESERVED_MINUTES = 10  # minutes to preserve and display per tab

# UI Theme configuration
THEME = {
    "bg_color": "#111111",
    "accent_color": "#ffb400",
    "text_color": "#ffffff",
    "log_bg_color": "#1e1e1e",
    "bg_highlight_color": "#3a3a3a",
}

# Animation settings
ANIMATION_SETTINGS = {
    "enabled": True,
    "duration": 800,  # milliseconds
    "steps": 8,
}

# File paths
DEVIATIONS_FILE = "deviations.txt"
ICON_FILE = "assets/icon.ico"
VERSION = "v1.1.0"
