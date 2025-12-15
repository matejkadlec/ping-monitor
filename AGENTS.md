# 🤖 Agents Documentation

This project is maintained with the assistance of AI agents. This file documents the project structure and key components to help future agents understand the codebase quickly.

## 🏗️ Project Structure

```
ping_monitor/
├── main.py                 # Entry point
├── run.vbs                 # Windows runner (hidden console)
├── setup.bat               # Setup script
├── src/
│   ├── core/
│   │   ├── config.py       # Configuration constants
│   │   ├── ping_monitor.py # Main controller class
│   │   └── ping_service.py # Ping logic & threading
│   ├── gui/
│   │   ├── main_window.py  # Main GUI controller
│   │   ├── system_tray.py  # System tray icon logic
│   │   ├── components/     # Reusable GUI components
│   │   │   └── server_tab.py # Individual server tab logic
│   │   ├── dialogs/        # Dialog windows
│   │   │   └── first_run.py  # First run configuration dialog
│   │   └── utils/          # GUI utilities
│   │       └── animations.py # Animation logic
│   └── utils/
│       ├── deviation_logger.py # Logging logic
│       ├── instance_lock.py    # Single instance enforcement
│       └── statistics.py       # Stats calculation
└── assets/                 # Images and icons
```

## 🧩 Key Components

### Core

- **PingMonitor (`src/core/ping_monitor.py`)**: The central controller. It initializes the GUI, PingService, and SystemTray. It coordinates the startup flow, ensuring configuration is set before background services start.
- **PingService (`src/core/ping_service.py`)**: Handles the actual pinging of servers in a background thread. It puts results into a queue for the GUI to consume.
- **Config (`src/core/config.py`)**: Contains all static configuration. `CLOSE_TO_TRAY` is a special variable that can be updated by the app at runtime (and persisted to the file).

### GUI

- **MainWindow (`src/gui/main_window.py`)**: The main Tkinter window. It manages the high-level layout and the update loop. It delegates specific tasks to components.
- **ServerTab (`src/gui/components/server_tab.py`)**: Encapsulates the UI and logic for a single server tab (text widget, status label, updates).
- **FirstRunDialog (`src/gui/dialogs/first_run.py`)**: Handles the initial setup flow if `CLOSE_TO_TRAY` is not configured.
- **AnimationUtils (`src/gui/utils/animations.py`)**: Handles smooth scrolling and highlight fading effects.

## 🔄 Data Flow

1. `PingService` pings servers in a background thread.
2. Results are placed in a thread-safe `queue`.
3. `MainWindow` polls this queue in its main loop (`_start_gui_update_thread`).
4. Results are dispatched to the appropriate `ServerTab` for display.
5. `SystemTray` is updated with the status of the first server.

## 🛠️ Development Notes

- **Theme**: The app uses a dark theme defined in `config.py`.
- **Icons**: Icons are drawn programmatically using Pillow (PIL) in `MainWindow` to avoid external dependencies for simple assets.
- **Threading**: Tkinter runs in the main thread. Network operations run in background threads. `queue` is used for communication.
