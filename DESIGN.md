# Project Structure

The Ping Monitor project has been reorganized into a more maintainable structure:

## 📁 Directory Structure

```
ping-monitor/
├── main.py                     # Main entry point
├── assets/                     # Static assets
│   └── icon.ico                # Application icon
├── src/                        # Source code
│   ├── core/                   # Core application logic
│   │   ├── config.py           # Configuration settings
│   │   ├── ping_monitor.py     # Main application orchestrator
│   │   └── ping_service.py     # Ping functionality
│   ├── gui/                    # GUI components
│   │   ├── main_window.py      # Main application window
│   │   └── system_tray.py      # System tray icon
│   └── utils/                  # Utility modules
│       ├── instance_lock.py    # Single instance management
│       ├── deviation_logger.py # High ping event logging
│       └── statistics.py       # Statistics calculations
├── config/                     # Configuration files (future use)
├── deviations.txt              # Log of high ping events
├── requirements.txt            # Python dependencies
├── run.vbs                     # Windows launcher script
├── setup.bat                   # Setup script
└── README.md                   # Project documentation
```

## 🏗️ Architecture

### Main Components

1. **PingMonitor** (`src/core/ping_monitor.py`)
   - Main orchestrator that coordinates all components
   - Manages application lifecycle and component communication

2. **PingService** (`src/core/ping_service.py`) 
   - Handles all ping operations and result processing
   - Manages concurrent pinging of multiple servers

3. **MainWindow** (`src/gui/main_window.py`)
   - Manages the main GUI with tabbed interface
   - Handles display updates, and user interactions
   - Features smooth highlight animation for new ping entries

4. **SystemTray** (`src/gui/system_tray.py`)
   - Manages system tray icon and context menu
   - Updates icon color based on network status

5. **Utilities**
   - **InstanceLock**: Prevents multiple app instances
   - **DeviationLogger**: Logs high ping events
   - **Statistics**: Calculates ping averages and metrics
