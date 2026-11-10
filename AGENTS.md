# Ping Monitor - Agent Guide

This file is for coding agents working on this repository.

## Environment And Paths

- Runtime target is **Windows** (Python 3.14+, PySide6). The app is started with `run.vbs` (hidden `pythonw.exe`), set up with `setup.bat` (`uv sync --frozen --no-dev` into `venv`).
- The project lives at `C:\Users\matka\projects\ping-monitor` (from WSL: `/mnt/c/Users/matka/projects/ping-monitor`).
- Development and tests also work on Linux/WSL: `PING_MONITOR_SIMULATE=1` replaces real pings with simulated ones and `QT_QPA_PLATFORM=offscreen` runs the UI without a display (the tests set it themselves).
- `PING_MONITOR_DATA_DIR=<folder>` redirects settings and logs (tests use a temp folder).
- `setup.bat` and `run.vbs` are Windows scripts: from WSL run them with `cmd.exe /c setup.bat` and `wscript.exe run.vbs`.

## Structure

```
ping-monitor/
├── main.py                  # entry point (reports missing dependencies in a message box)
├── run.vbs / setup.bat      # Windows launcher / installer (CRLF, see .gitattributes)
├── assets/                  # icon, background picture, fonts (OFL), Lucide icons (ISC)
├── src/
│   ├── app.py               # AppController: wires everything, run()
│   ├── core/                # no Qt imports - unit-testable anywhere
│   │   ├── models.py        # PingResult, PingStatus, HealthStatus, LatencyLevel, ServerSpec
│   │   ├── pinger.py        # Windows IcmpSendEcho (ctypes), ping-command fallback, simulator
│   │   ├── engine.py        # PingEngine: one worker thread per server on a wall-clock grid
│   │   ├── stats.py         # ServerHistory: window stats (O(1)), health, session counters
│   │   ├── spike_log.py     # current / previous session logs
│   │   ├── alerts.py        # when to notify "failing" / "healthy again"
│   │   ├── settings.py      # Settings dataclass, validation, JSON persistence
│   │   ├── autostart.py     # "Start with Windows" (HKCU Run key)
│   │   ├── fileio.py        # atomic writes
│   │   ├── paths.py         # assets / data folders (source vs. frozen exe)
│   │   └── validation.py    # IPv4 / domain / number checks
│   ├── ui/                  # PySide6
│   │   ├── theme.py         # design tokens, fonts, global stylesheet, UI scale, motion flags
│   │   ├── main_window.py   # tabs, actions, pages, overlays, toasts, background
│   │   ├── server_page.py   # header + status pill, chart, stream, stats bar
│   │   ├── latency_chart.py # custom painted chart (cached static layer + animated head)
│   │   ├── ping_stream.py   # virtualized list (model/delegate/view)
│   │   ├── fast_list.py     # FastListView: one-column table used as a fast list
│   │   ├── overlay.py       # in-window overlays (blur + dim), Panel base, ConfirmDialog
│   │   ├── config_panel.py  # Config overlay
│   │   ├── logs_panel.py    # Logs overlay
│   │   ├── toast.py         # toasts
│   │   ├── tray.py          # tray icon + menu
│   │   ├── controls.py      # IconButton, TextButton, CheckBox, Tween, fade()
│   │   ├── scrollbar.py, tab_strip.py, menus.py, icons.py, win32.py
│   └── utils/               # logging setup, single instance (QLocalServer)
├── tests/                   # pytest (core + offscreen UI)
└── untracked/TODO.md        # task list (git-ignored)
```

## Data Flow

1. `PingEngine` workers ping all servers in parallel on a shared grid; the first ping is immediate. Missed slots become one `GAP` result (never fake pings).
2. Workers call the engine callback, which emits a Qt signal; `AppController._on_result` receives it on the GUI thread (queued connection).
3. The controller drops results of removed/changed servers or while paused, updates `ServerHistory`, records spikes/losses in `SpikeLog`, then updates the page, the tab and (for the first server) the tray and `HealthAlerts` (notifications).
4. Pages read everything from their `ServerHistory` (`reload()` after resets or settings changes).

## Constraints And Practical Notes

- Qt objects are touched only on the GUI thread. Worker threads only call the engine callback.
- Time math uses `PingResult.epoch` (DST-proof); `timestamp` is for display only.
- All file writes go through `fileio.atomic_write_text` or are wrapped so file errors never stop the app.
- Settings stay backward compatible with older `app_config.json` files.
- Only `PySide6-Essentials` at runtime. Update `uv.lock` (`uv lock`) whenever `pyproject.toml` changes.

## UI Conventions

- Colors, fonts, sizes and durations come from `THEME` (`theme.py`); sizes go through `THEME.px()` so the UI scales between windowed and full screen.
- **Anything clickable shows the pointer (hand) cursor on hover.** Info icons use the help cursor.
- No instant state changes: hovers, shows/hides and color changes fade or glide (`Tween`, `fade()`, `THEME.duration()` returns 0 when Windows animations are off). Ambient motion pauses while an overlay is open.
- Text uses the text colors; green/yellow/red only mark status (with a label or value next to them).
- New panels subclass `overlay.Panel`; confirmations use `ConfirmDialog`, feedback uses the toasts. Fonts and sizes set in a panel go through `Panel.themed()` so they follow scale changes; panels keep the keyboard focus inside (Tab cycles, window shortcuts wait).
- Fonts: Montserrat for UI, JetBrains Mono for ping rows and logs.
- Long lists use `FastListView` (fixed row height): `QListView` re-lays out every row through the Python model on each insert.
- Animation pitfalls: connect `QVariantAnimation.valueChanged` with `controls.connect_running()` (a stopped animation emits stale values while being reconfigured), call `settle_fades()` before putting a graphics effect on an ancestor (Qt cannot nest effects), and stop timers when hidden or minimized.

## Change Workflow For Agents

1. Read `untracked/TODO.md` and update task statuses when you start/finish a section.
2. Prefer incremental patches over broad rewrites; keep `src/core` free of Qt.
3. Run the tests: `uv run pytest` on Windows; from WSL use a Linux environment outside `/mnt/c`, e.g. `UV_PROJECT_ENVIRONMENT=~/.venvs/pm uv run pytest -q -p no:cacheprovider` (a `.venv` inside the Windows folder is slow and clashes with the Windows one).
4. For UI changes, look at the result: run the app with `PING_MONITOR_SIMULATE=1 PING_MONITOR_DATA_DIR=$(mktemp -d)` so fake spikes never reach the real `logs/` (on Windows, quit the running app first: a second start only shows its window). Offscreen `QWidget.grab()` screenshots work too.
5. Keep naming consistent (`ping_spike`, `healthy/degraded/failing`).
6. When debugging, inspect `logs/app.log` early (worker stalls, gaps and file errors are logged there).

## Response Handoff Requirement

- End responses with a concise summary (short paragraph and/or compact bullet list) focused on what changed and what remains.
- Do not include exact file/line references in this handoff summary.
- If any requirement was intentionally not implemented or implemented differently, call it out clearly and briefly.

## Post-Change Instruction

- If dependencies changed: ask user to run `setup.bat`.
- Otherwise: ask user to run `run.vbs`.
