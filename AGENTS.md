# Ping Monitor - Agent Guide

This file is for coding agents working on this repository.

## Environment And Paths

- Runtime target is **Windows**.
- Development shell is usually **WSL (Ubuntu/Linux)** inside VS Code.
- Project is physically stored on Windows at:
  - `C:\Users\matka\My Drive\python_scripts\ping_monitor`
- Same path from WSL:
  - `/mnt/c/Users/matka/My Drive/python_scripts/ping_monitor`
- Because the folder is mounted in WSL, file access from VS Code + WSL works like a normal Linux workspace.

## Current Structure (important files)

```
ping_monitor/
├── main.py
├── run.vbs
├── setup.bat
├── src/
│   ├── core/
│   │   ├── config.py
│   │   ├── ping_monitor.py
│   │   └── ping_service.py
│   ├── gui/
│   │   ├── main_window.py
│   │   ├── system_tray.py
│   │   ├── components/server_tab.py
│   │   ├── dialogs/first_run.py
│   │   └── utils/
│   │       └── animations.py
│   └── utils/
│       ├── ping_spike_logger.py
│       ├── deviation_logger.py   # compatibility alias wrapper
│       ├── instance_lock.py
│       └── statistics.py
├── assets/
├── README.md
└── untracked/TODO.md
```

## Architecture Summary

- `PingMonitor` (`src/core/ping_monitor.py`) orchestrates services, stats, and shutdown lifecycle.
- `PingService` (`src/core/ping_service.py`) runs ping loops in background threads and pushes results into a queue.
- `MainWindow` (`src/gui/main_window.py`) owns Tk root, toolbar, tabs, and GUI polling (`root.after`).
- `ServerTab` (`src/gui/components/server_tab.py`) renders per-server stream and footer stats.
- `SystemTray` (`src/gui/system_tray.py`) controls tray icon/menu and health status color/title.
- `PingSpikeLogger` (`src/utils/ping_spike_logger.py`) stores high-ping events to `logs/ping_spikes.log` with cleanup.

## Data Flow

1. `PingService` pings all configured servers concurrently.
2. Results are queued (`queue.Queue`).
3. `MainWindow` periodic callback drains queue and calls `PingMonitor._process_ping_result`.
4. `PingMonitor` updates statistics + ping spike counters and dispatches to UI.
5. `ServerTab` renders text and footer metrics.
6. `SystemTray` updates icon and hover title from first-server health state.

## Constraints And Practical Notes

- Tkinter UI must run in the main thread.
- Ping command in this app is Windows-style (`ping -n -w`), so app execution should use Windows Python (`run.vbs`).
- `setup.bat` and `run.vbs` are Windows scripts; do not expect native execution from Linux shell without `cmd.exe /c`.
- Keep changes focused and minimal; preserve current UX unless task explicitly asks for redesign.
- Logs UI intentionally uses a separate `Toplevel` window instead of the originally requested in-frame blurred overlay, to preserve stability and allow logs + live metrics side-by-side.

## Change Workflow For Agents

1. Read `untracked/TODO.md` and update task statuses when you start/finish a section.
2. Prefer incremental patches over broad rewrites.
3. Validate with quick static/error checks after edits.
4. Keep naming consistent (`ping_spike`, `healthy/degraded/failing`).

## Post-Change Instruction

- If dependencies changed: ask user to run `setup.bat`.
- Otherwise: ask user to run `run.vbs`.
