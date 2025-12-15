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
PING_THRESHOLD = 60  # ms (for deviation logging)
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
CLOSE_TO_TRAY = None

# Animation settings
ANIMATION_SETTINGS = {
    "enabled": True,
    "duration": 800,  # milliseconds
    "steps": 8,
}

# File paths
DEVIATIONS_FILE = "deviations.txt"
ICON_FILE = "assets/icon.ico"
BACKGROUND_FILE = "assets/background.png"
