"""
The Config overlay: servers table (inline editing) and monitoring settings.
"""

import threading
from collections.abc import Callable

import shiboken6
from PySide6.QtCore import QObject, QRegularExpression, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QRegularExpressionValidator, QValidator
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.core import autostart, validation
from src.core.models import PingStatus, ServerSpec
from src.core.pinger import create_pinger, resolve_ipv4
from src.core.settings import (
    INTERVAL_MAX,
    INTERVAL_MIN,
    MAX_SERVERS,
    PRESERVED_MAX,
    PRESERVED_MIN,
    THRESHOLD_MAX,
    THRESHOLD_MIN,
    FieldError,
    Settings,
)
from src.ui import icons
from src.ui.controls import CheckBox, IconButton, TextButton, fade
from src.ui.overlay import ConfirmDialog, OverlayHost, Panel
from src.ui.scrollbar import SmoothScrollBar
from src.ui.theme import THEME
from src.ui.toast import ToastManager

HOST_CHECK_TIMEOUT_MS = 1500
HOST_CHECK_ATTEMPTS = 2


class _Signals(QObject):
    hostsChecked = Signal(object, object)  # token, list of failed hosts
    resolved = Signal(object, str, str)  # row, name, address ("" on failure)


class NumberValidator(QValidator):
    """Digits only (plus -1 when allowed); refuses values above the maximum."""

    def __init__(self, maximum: int, allow_forever: bool, on_too_big: Callable[[], None], parent=None) -> None:
        super().__init__(parent)
        self.maximum = maximum
        self.allow_forever = allow_forever
        self.on_too_big = on_too_big

    def validate(self, text: str, pos: int):
        if text == "" or (self.allow_forever and text == "-"):
            return QValidator.State.Intermediate, text, pos
        value = validation.parse_int(text)
        if value is None or text != text.strip():
            return QValidator.State.Invalid, text, pos
        if value < 0 and not (self.allow_forever and value == -1):
            return QValidator.State.Invalid, text, pos
        if value > self.maximum:
            self.on_too_big()
            return QValidator.State.Invalid, text, pos
        return QValidator.State.Acceptable, text, pos


class _InfoIcon(QLabel):
    """White info glyph with a tooltip and the "help" cursor."""

    def __init__(self, tooltip: str) -> None:
        super().__init__()
        self.setToolTip(tooltip)
        self.setCursor(Qt.CursorShape.WhatsThisCursor)
        self.setStyleSheet("background: transparent;")
        self.apply_theme()

    def apply_theme(self) -> None:
        size = THEME.px(17)
        self.setPixmap(icons.pixmap("info", THEME.colors.ink, size, stroke=2.4))
        self.setFixedSize(size, size)


class _AutoHeightScroll(QScrollArea):
    """Scroll area that asks for its content's full height (the overlay caps it)."""

    def sizeHint(self) -> QSize:
        widget = self.widget()
        if widget is None:
            return super().sizeHint()
        hint = widget.sizeHint()
        return QSize(hint.width(), hint.height() + 2)


class _ServerRow:
    def __init__(self, panel: "ConfigPanel", name: str, host: str) -> None:
        self.panel = panel
        self.name = QLineEdit(name)
        self.name.setPlaceholderText("cloudflare.com")
        self.name.setToolTip("Domain name, e.g. cloudflare.com. Press Enter to fill in the IP automatically.")
        self.host = QLineEdit(host)
        self.host.setPlaceholderText("1.1.1.1")
        self.host.setToolTip("IPv4 address, digits only, e.g. 1.1.1.1.")
        self.host.setValidator(QRegularExpressionValidator(QRegularExpression(r"[0-9.]{0,15}"), self.host))
        self.delete = IconButton("trash-2", "Delete this record", size=32, icon_size=17)
        for edit in (self.name, self.host):
            panel.themed(edit, lambda e=edit: e.setFont(THEME.font(13)))
            edit.textChanged.connect(panel._changed)
            edit.textEdited.connect(lambda _text, e=edit: panel._set_invalid(e, False))
        self.name.returnPressed.connect(lambda: panel._name_entered(self))
        self.host.returnPressed.connect(lambda: panel._host_entered(self))
        self.delete.clicked.connect(lambda: panel._delete_row(self))

    def spec(self) -> ServerSpec:
        return ServerSpec(self.name.text().strip(), self.host.text().strip())

    def is_empty(self) -> bool:
        return not self.name.text().strip() or not self.host.text().strip()

    def widgets(self) -> tuple[QWidget, QWidget, QWidget]:
        return self.name, self.host, self.delete


class ConfigPanel(Panel):
    def __init__(self, settings: Settings, on_save: Callable[[Settings], None],
                 overlay: OverlayHost, toasts: ToastManager) -> None:
        super().__init__("Config", width=620)
        self._initial = settings
        self._autostart_initial = autostart.is_enabled() if autostart.is_supported() else None
        self._on_save = on_save
        self._overlay = overlay
        self._toasts = toasts
        self._rows: list[_ServerRow] = []
        self._check_token: object | None = None
        self._closing = False  # saved: fading out, takes no more input
        self._signals = _Signals()
        self._signals.hostsChecked.connect(self._hosts_checked)
        self._signals.resolved.connect(self._resolved)

        body = QWidget()
        body.setStyleSheet("background: transparent;")
        self._body = QVBoxLayout(body)
        self.themed(body, lambda: (self._body.setContentsMargins(0, 0, THEME.px(10), 0),
                                   self._body.setSpacing(THEME.px(10))))
        self._build_servers(settings)
        self._build_settings(settings)
        self._body.addStretch(1)

        scroll = _AutoHeightScroll()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBar(SmoothScrollBar(scroll))
        scroll.setWidget(body)
        self._scroll = scroll
        # New fonts mean a new content height, known once the other handlers ran.
        self.themed(scroll, lambda: QTimer.singleShot(0, scroll, scroll.updateGeometry))
        self.outer.addWidget(scroll, 1)

        footer = QHBoxLayout()
        self.themed(self, lambda: footer.setSpacing(THEME.px(10)))
        footer.addStretch(1)
        self.cancel_button = TextButton("Cancel", "secondary")
        self.save_button = TextButton("Save", "primary")
        self.cancel_button.clicked.connect(self.request_close)
        self.save_button.clicked.connect(self._save)
        footer.addWidget(self.cancel_button)
        footer.addWidget(self.save_button)
        self.outer.addSpacing(THEME.px(2))
        self.outer.addLayout(footer)
        self._changed()

    # ------------------------------------------------------------- building
    def _section_title(self, text: str) -> QLabel:
        label = QLabel(text)
        self.themed(label, lambda: label.setFont(THEME.font(14, QFont.Weight.Bold)))
        label.setStyleSheet(f"color: {THEME.colors.ink}; background: transparent;")
        return label

    def _build_servers(self, settings: Settings) -> None:
        header = QHBoxLayout()
        header.addWidget(self._section_title("Servers"))
        header.addStretch(1)
        self.add_button = TextButton("Add", "secondary", icon_name="plus", min_width=0)
        self.add_button.setToolTip("Add a server")
        self.add_button.clicked.connect(self._add_row)
        header.addWidget(self.add_button)
        self._body.addLayout(header)

        self._table = QGridLayout()
        self.themed(self, lambda: (self._table.setHorizontalSpacing(THEME.px(8)),
                                   self._table.setVerticalSpacing(THEME.px(8))))
        self._table.setColumnStretch(0, 3)
        self._table.setColumnStretch(1, 2)
        for column, text in enumerate(("Name", "IP")):
            label = QLabel(text)
            self.themed(label, lambda label=label: label.setFont(THEME.font(11.5, QFont.Weight.DemiBold)))
            label.setStyleSheet(f"color: {THEME.colors.ink3}; background: transparent;")
            self._table.addWidget(label, 0, column)
        self._body.addLayout(self._table)
        for server in settings.servers:
            self._append_row(server.name, server.host)

    def _build_settings(self, settings: Settings) -> None:
        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet(f"background: {THEME.colors.hairline}; border: none;")
        self._body.addSpacing(THEME.px(8))
        self._body.addWidget(divider)
        self._body.addSpacing(THEME.px(8))

        grid = QGridLayout()
        self.themed(self, lambda: (grid.setHorizontalSpacing(THEME.px(14)), grid.setVerticalSpacing(THEME.px(12))))
        grid.setColumnStretch(2, 1)
        self._grid = grid
        self.healthy = self._number_row(
            0, "Ping Threshold Healthy", "ms", settings.ping_threshold_healthy, THRESHOLD_MAX,
            f"Pings up to this value are healthy (green). In milliseconds, {THRESHOLD_MIN}–{THRESHOLD_MAX}.")
        self.degraded = self._number_row(
            1, "Ping Threshold Degraded", "ms", settings.ping_threshold_degraded, THRESHOLD_MAX,
            "Pings above the healthy threshold up to this value are degraded (yellow); anything above "
            f"is a spike (red) and gets logged. In milliseconds, {THRESHOLD_MIN}–{THRESHOLD_MAX}, "
            "at least the healthy threshold.")
        self.interval = self._number_row(
            2, "Ping Interval", "s", settings.ping_interval, INTERVAL_MAX,
            f"Seconds between pings, {INTERVAL_MIN}–{INTERVAL_MAX}.")
        self.preserved = self._number_row(
            3, "Preserved Minutes", "min", settings.preserved_minutes, PRESERVED_MAX,
            f"Minutes to preserve and display per tab, {PRESERVED_MIN}–{PRESERVED_MAX}. "
            "Use -1 to keep everything until the app is closed.", allow_forever=True)
        self.close_to_tray = CheckBox()
        self.close_to_tray.set_checked(settings.close_to_tray, animate=False)
        self.close_to_tray.toggled.connect(self._changed)
        self._label_row(4, "Close To Tray", "App will minimize to system tray icon instead of closing.",
                        self.close_to_tray)
        first = settings.servers[0].name if settings.servers else "the first server"
        self.notifications = self._check_row(
            5, "Notifications", settings.notifications,
            f"Show a Windows notification when {first} (the tray icon server) starts failing "
            "and when it is healthy again.")
        self.background_image = self._check_row(
            6, "Background Image", settings.background_image,
            "Show the blue background picture behind the app instead of the plain dark color.")
        self.start_with_windows: CheckBox | None = None
        if self._autostart_initial is not None:
            self.start_with_windows = self._check_row(
                7, "Start With Windows", self._autostart_initial,
                "Start Ping Monitor in the tray when you sign in to Windows.")
        self._body.addLayout(grid)

    def _check_row(self, row: int, text: str, checked: bool, tooltip: str) -> CheckBox:
        checkbox = CheckBox()
        checkbox.set_checked(checked, animate=False)
        checkbox.toggled.connect(self._changed)
        self._label_row(row, text, tooltip, checkbox)
        return checkbox

    def _label_row(self, row: int, text: str, tooltip: str, widget: QWidget) -> None:
        label_box = QHBoxLayout()
        label_box.setSpacing(THEME.px(8))
        label = QLabel(text)
        self.themed(label, lambda: label.setFont(THEME.font(13, QFont.Weight.Medium)))
        label.setStyleSheet(f"color: {THEME.colors.ink}; background: transparent;")
        label_box.addWidget(label)
        info = _InfoIcon(tooltip)
        self.themed(info, info.apply_theme)
        label_box.addWidget(info, 0, Qt.AlignmentFlag.AlignVCenter)
        label_box.addStretch(1)
        self._grid.addLayout(label_box, row, 0, Qt.AlignmentFlag.AlignVCenter)
        self._grid.addWidget(widget, row, 1, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

    def _number_row(self, row: int, text: str, unit: str, value: int, maximum: int, tooltip: str,
                    allow_forever: bool = False) -> QLineEdit:
        edit = QLineEdit(str(value))
        self.themed(edit, lambda: (edit.setFont(THEME.font(13, tabular=True)), edit.setFixedWidth(THEME.px(76))))
        edit.setValidator(NumberValidator(maximum, allow_forever,
                                          lambda: self._toasts.warning(f"{text} can be at most {maximum}."), edit))
        edit.textChanged.connect(self._changed)
        edit.textEdited.connect(lambda _t, e=edit: self._set_invalid(e, False))
        holder = QWidget()
        holder.setStyleSheet("background: transparent;")
        box = QHBoxLayout(holder)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(THEME.px(8))
        box.addWidget(edit)
        unit_label = QLabel(unit)
        unit_label.setStyleSheet(f"color: {THEME.colors.ink3}; background: transparent;")
        box.addWidget(unit_label)
        self._label_row(row, text, tooltip, holder)
        return edit

    # ------------------------------------------------------------- servers
    def _append_row(self, name: str, host: str, animate: bool = False) -> _ServerRow:
        row = _ServerRow(self, name, host)
        previous = self._rows[-1] if self._rows else None
        self._rows.append(row)
        index = self._table.rowCount()  # below everything (a deleted row may still be fading out)
        for column, widget in enumerate(row.widgets()):
            self._table.addWidget(widget, index, column)
            if animate:
                fade(widget, True, THEME.NORMAL)
        if previous is not None:
            # New widgets go to the end of the Tab order: put them after the previous row.
            QWidget.setTabOrder(previous.delete, row.name)
            QWidget.setTabOrder(row.name, row.host)
            QWidget.setTabOrder(row.host, row.delete)
        self._update_delete_buttons()
        self._scroll_content_changed()
        return row

    def _scroll_content_changed(self) -> None:
        if hasattr(self, "_scroll"):
            self._scroll.updateGeometry()  # the overlay re-places (grows) the panel
        self.updateGeometry()

    def _relayout_rows(self) -> None:
        for row in self._rows:
            for widget in row.widgets():
                self._table.removeWidget(widget)
        for index, row in enumerate(self._rows, start=1):
            for column, widget in enumerate(row.widgets()):
                self._table.addWidget(widget, index, column)
        self._update_delete_buttons()

    def _update_delete_buttons(self) -> None:
        only_one = len(self._rows) <= 1
        for row in self._rows:
            row.delete.setToolTip("At least one server is required" if only_one else "Delete this record")

    def _busy(self) -> bool:
        """Checking the new servers or closing: the form takes no structural changes."""
        if self._closing:
            return True
        if self._check_token is not None:
            self._toasts.warning("Wait until the servers are checked.")
            return True
        return False

    def _add_row(self) -> None:
        if self._busy():
            return
        empty = next((row for row in self._rows if row.is_empty()), None)
        if empty is not None:
            self._toasts.warning("Fill in the empty row first.")
            (empty.name if not empty.name.text().strip() else empty.host).setFocus()
            return
        if len(self._rows) >= MAX_SERVERS:
            self._toasts.warning(f"You can monitor up to {MAX_SERVERS} servers.")
            return
        row = self._append_row("", "", animate=True)
        self._changed()

        def focus_new_row() -> None:
            row.name.setFocus()
            self._scroll.ensureWidgetVisible(row.delete)

        QTimer.singleShot(0, row.name, focus_new_row)

    def _delete_row(self, row: _ServerRow) -> None:
        if self._busy():
            return
        if len(self._rows) <= 1:
            self._toasts.warning("At least one server is required.")
            return

        def answered(yes: bool) -> None:
            if not yes or not shiboken6.isValid(self) or self._closing or row not in self._rows:
                return
            self._rows.remove(row)
            self._update_delete_buttons()
            self._changed()
            remaining = list(row.widgets())

            def faded(widget: QWidget) -> None:
                remaining.remove(widget)
                if not remaining and shiboken6.isValid(self):
                    for item in row.widgets():
                        self._table.removeWidget(item)
                        item.deleteLater()
                    self._relayout_rows()
                    self._scroll_content_changed()

            for widget in row.widgets():
                fade(widget, False, THEME.FAST, on_finished=lambda w=widget: faded(w))

        label = row.name.text().strip() or "this record"
        self._overlay.open(ConfirmDialog(
            "Delete server", f"Are you sure you want to delete {label}?", answered,
            yes_text="Yes, delete", no_text="No", danger=True))

    def _name_entered(self, row: _ServerRow) -> None:
        name = row.name.text().strip()
        if not row.host.text().strip() and validation.is_hostname(name):
            row.host.setPlaceholderText("Looking up…")
            threading.Thread(target=self._resolve_worker, args=(row, name), daemon=True).start()
        row.host.setFocus()

    def _resolve_worker(self, row: _ServerRow, name: str) -> None:
        try:
            address = resolve_ipv4(name)
        except OSError:
            address = ""
        self._signals.resolved.emit(row, name, address)

    def _resolved(self, row: _ServerRow, name: str, address: str) -> None:
        if row not in self._rows:
            return
        row.host.setPlaceholderText("1.1.1.1")
        if row.name.text().strip() != name or row.host.text().strip():
            return  # the user kept typing
        if address:
            row.host.setText(address)
            self._toasts.success(f"Found {name} at {address}.")
        else:
            self._toasts.warning(f"Could not find an IP address for {name}.")

    def _host_entered(self, row: _ServerRow) -> None:
        if row not in self._rows:
            return
        index = self._rows.index(row)
        if index + 1 < len(self._rows):
            self._rows[index + 1].name.setFocus()
        elif self.save_button.isEnabled():
            self.save_button.setFocus()  # Enter again saves (buttons click on Enter)

    # -------------------------------------------------------------- state
    def _collect(self) -> Settings | None:
        values = {}
        for key, edit in (("ping_threshold_healthy", self.healthy), ("ping_threshold_degraded", self.degraded),
                          ("ping_interval", self.interval), ("preserved_minutes", self.preserved)):
            value = validation.parse_int(edit.text())
            values[key] = value if value is not None else -999
        return self._initial.with_changes(
            servers=tuple(row.spec() for row in self._rows if row.name.text().strip() or row.host.text().strip()),
            close_to_tray=self.close_to_tray.isChecked(),
            notifications=self.notifications.isChecked(),
            background_image=self.background_image.isChecked(),
            **values,
        )

    def _autostart_changed(self) -> bool:
        return (self.start_with_windows is not None
                and self.start_with_windows.isChecked() != self._autostart_initial)

    def is_dirty(self) -> bool:
        if not hasattr(self, "background_image"):
            return False  # still building
        current = self._collect()
        return (current != self._initial or self._autostart_changed()
                or any(row.is_empty() and (row.name.text() or row.host.text()) for row in self._rows))

    def _changed(self, *_args) -> None:
        if hasattr(self, "save_button"):
            self.save_button.setEnabled(self._check_token is None and not self._closing and self.is_dirty())

    def _set_invalid(self, edit: QLineEdit, invalid: bool) -> None:
        if bool(edit.property("invalid")) != invalid:
            edit.setProperty("invalid", invalid)
            edit.style().unpolish(edit)
            edit.style().polish(edit)

    def _field_widget(self, error: FieldError) -> QLineEdit | None:
        if error.field == "servers" and error.row is not None:
            filled = [row for row in self._rows if row.name.text().strip() or row.host.text().strip()]
            if error.row < len(filled):
                return filled[error.row].name if error.column == "name" else filled[error.row].host
            return None
        return {
            "ping_threshold_healthy": self.healthy,
            "ping_threshold_degraded": self.degraded,
            "ping_interval": self.interval,
            "preserved_minutes": self.preserved,
        }.get(error.field)

    # -------------------------------------------------------------- saving
    def _save(self) -> None:
        if self._check_token is not None or self._closing:
            return
        for row in self._rows:
            self._set_invalid(row.name, False)
            self._set_invalid(row.host, False)
        for edit in (self.healthy, self.degraded, self.interval, self.preserved):
            self._set_invalid(edit, False)

        settings = self._collect()
        errors = settings.validate()
        if errors:
            first_widget = None
            for error in errors:
                widget = self._field_widget(error)
                if widget is not None:
                    self._set_invalid(widget, True)
                    first_widget = first_widget or widget
            self._toasts.error(errors[0].message)
            if first_widget is not None:
                first_widget.setFocus()
                self._scroll.ensureWidgetVisible(first_widget)
            return

        known_hosts = {server.host for server in self._initial.servers}
        new_hosts = sorted({server.host for server in settings.servers if server.host not in known_hosts})
        if not new_hosts:
            self._commit(settings)
            return
        token = object()
        self._check_token = token
        self._pending = settings
        self.save_button.set_busy(True, "Checking…")
        self.save_button.setEnabled(False)
        threading.Thread(target=self._check_worker, args=(token, new_hosts), daemon=True).start()

    def _check_worker(self, token: object, hosts: list[str]) -> None:
        failed = []
        pinger = None
        try:
            pinger = create_pinger()
            for host in hosts:
                ok = False
                for _ in range(HOST_CHECK_ATTEMPTS):
                    if pinger.ping(host, HOST_CHECK_TIMEOUT_MS).status is PingStatus.OK:
                        ok = True
                        break
                if not ok:
                    failed.append(host)
        except Exception:
            failed = list(hosts)
        finally:
            if pinger is not None:
                try:
                    pinger.close()
                except Exception:
                    pass
        self._signals.hostsChecked.emit(token, failed)

    def _cancel_check(self) -> None:
        if self._check_token is not None:
            self._check_token = None
            self.save_button.set_busy(False, "Save")
            self._changed()

    def _hosts_checked(self, token: object, failed: list[str]) -> None:
        if token is not self._check_token:
            return
        self._check_token = None
        self.save_button.set_busy(False, "Save")
        settings = getattr(self, "_pending", None)
        if failed:
            self._changed()
            for row in self._rows:
                if row.host.text().strip() in failed:
                    self._set_invalid(row.host, True)
            hosts = ", ".join(failed)
            self._toasts.error(f"The server IP is invalid: {hosts} did not answer.")
            return
        if settings is not None and settings == self._collect() and self._overlay.top_panel() is self:
            self._commit(settings)
        else:
            self._changed()  # edited while checking: let the user save again

    def _commit(self, settings: Settings) -> None:
        try:
            self._on_save(settings)
        except OSError as error:
            self._toasts.error(f"Could not save the config: {error}")
            return
        self._initial = settings
        if self._autostart_changed():
            enabled = self.start_with_windows.isChecked()
            try:
                autostart.set_enabled(enabled)
                self._autostart_initial = enabled
            except OSError as error:
                self._toasts.error(f"Could not change Start With Windows: {error}")
                self._changed()
                return
        self._closing = True
        self._changed()
        self._toasts.success("Config saved.")
        self.closeRequested.emit()

    def sync_close_to_tray(self, enabled: bool) -> None:
        """Close To Tray was toggled in the tray menu while this panel is open."""
        untouched = self.close_to_tray.isChecked() == self._initial.close_to_tray
        self._initial = self._initial.with_changes(close_to_tray=enabled)
        if untouched:
            self.close_to_tray.set_checked(enabled)
        self._changed()

    # ------------------------------------------------------------- closing
    def request_close(self) -> None:
        if self._closing:
            return
        self._cancel_check()
        if not self.is_dirty():
            self.closeRequested.emit()
            return

        def answered(yes: bool) -> None:
            if yes and shiboken6.isValid(self) and not self._closing:
                self.closeRequested.emit()

        self._overlay.open(ConfirmDialog(
            "Unsaved changes",
            "You have unsaved changes that will be discarded if you continue. Do you wish to proceed?",
            answered, yes_text="Yes, discard", no_text="No", danger=True))

    def on_shown(self) -> None:
        if self._rows:
            self._rows[0].name.setFocus()
            self._rows[0].name.end(False)

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        return QSize(self.preferred_width(), hint.height())

