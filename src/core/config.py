"""
Configuration settings for the Ping Monitor application.
"""

# Server configuration
SERVERS = {
    "cloudflare.com": "1.1.1.1",
    "google.com": "8.8.8.8",
    "seznam.cz": "77.75.77.222",
}

# Ping configuration
PING_THRESHOLD_HEALTHY = 50  # ms before the tray/footer status becomes degraded
PING_THRESHOLD_DEGRADED = 60  # ms before pings are treated as failing/spikes
PING_THRESHOLD = PING_THRESHOLD_DEGRADED  # Backward-compatible alias
PING_INTERVAL = 1  # seconds between pings
PRESERVED_MINUTES = 10  # minutes to preserve and display per tab

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
CLOSE_TO_TRAY = False

# Animation settings
ANIMATION_SETTINGS = {
    "enabled": True,
    "duration": 800,  # milliseconds
    "steps": 8,
}

# File paths
DEVIATIONS_FILE = "deviations.txt"
PING_SPIKES_FILE = "logs/ping_spikes.log"
ICON_FILE = "assets/icon.ico"
BACKGROUND_FILE = "assets/background.png"
