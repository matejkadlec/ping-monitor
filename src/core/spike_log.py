"""
Ping spikes log with "current session" and "previous sessions".

Files (in the data folder):

* ``ping_spikes_current.log`` – spikes of the running session. It always exists
  while the app runs, so a crash never loses data.
* ``ping_spikes.log`` – all previous sessions (kept for ``retention``).

On start, whatever is left in the current-session file (normal exit *or*
crash) is merged into ``ping_spikes.log`` in one atomic rewrite (old entries
past the retention are dropped at the same time, and legacy encodings are
converted to UTF-8). A session that is already archived is never merged twice.
Entry format (unchanged from older versions)::

    === Session 2026-11-10 00:18:03 ===
    [2026-11-10 01:46:37] cloudflare.com: 75ms
    [2026-11-10 01:52:10] cloudflare.com: timeout

File errors (antivirus or a sync client holding the file, read-only folder...)
are logged and never stop the app; entries are then only kept in memory.
"""

import logging
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from src.core.fileio import atomic_write_text
from src.core.models import PingResult, PingStatus

LOGGER = logging.getLogger(__name__)

CURRENT_FILE_NAME = "ping_spikes_current.log"
PREVIOUS_FILE_NAME = "ping_spikes.log"
DEFAULT_RETENTION = timedelta(hours=24)
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"

_ENTRY_RE = re.compile(r"^\[(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})\] (.+): (?:(\d+)ms|([a-z]+))\s*$")
_SESSION_RE = re.compile(r"^=== Session (\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2}) ===\s*$")


@dataclass(frozen=True, slots=True)
class SpikeEntry:
    timestamp: datetime
    server: str
    kind: str  # "spike" | "timeout" | "unreachable" | "error"
    rtt_ms: int | None = None

    def to_line(self) -> str:
        value = f"{self.rtt_ms}ms" if self.kind == "spike" else self.kind
        return f"[{self.timestamp.strftime(TIMESTAMP_FORMAT)}] {self.server}: {value}"


@dataclass(frozen=True, slots=True)
class SessionMarker:
    started_at: datetime

    def to_line(self) -> str:
        return f"=== Session {self.started_at.strftime(TIMESTAMP_FORMAT)} ==="


LogItem = SpikeEntry | SessionMarker


@dataclass(frozen=True, slots=True)
class RecentItems:
    """The newest entries of previous sessions (oldest first, with their markers)."""

    items: list[LogItem]
    truncated: bool  # older entries exist in the file but are not included
    partial_first: bool  # the oldest included session misses some of its entries


def entry_from_result(result: PingResult) -> SpikeEntry:
    stamp = result.timestamp.replace(microsecond=0)
    if result.status is PingStatus.OK:
        return SpikeEntry(stamp, result.server, "spike", result.rtt_ms)
    return SpikeEntry(stamp, result.server, result.status.value)


def _stamp(groups: tuple[str, ...]) -> datetime:
    year, month, day, hour, minute, second = (int(value) for value in groups)
    return datetime(year, month, day, hour, minute, second)


def parse_line(line: str) -> LogItem | None:
    line = line.strip()
    if not line:
        return None
    try:
        if line.startswith("==="):
            session = _SESSION_RE.match(line)
            return SessionMarker(_stamp(session.groups())) if session else None
        match = _ENTRY_RE.match(line)
        if not match:
            return None
        stamp = _stamp(match.groups()[:6])
        if match.group(8) is not None:
            return SpikeEntry(stamp, match.group(7), "spike", int(match.group(8)))
        return SpikeEntry(stamp, match.group(7), match.group(9))
    except ValueError:
        return None


def decode_text(raw: bytes) -> str:
    """Decode with fallbacks for legacy Windows/BOM log files."""
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return raw.decode("utf-16")
        except UnicodeDecodeError:
            pass
    for encoding in ("utf-8-sig", "cp1250", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def read_text(path: Path) -> str:
    return decode_text(path.read_bytes())


class SpikeLog:
    def __init__(
        self,
        directory: Path,
        retention: timedelta = DEFAULT_RETENTION,
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.directory = Path(directory)
        self.current_path = self.directory / CURRENT_FILE_NAME
        self.previous_path = self.directory / PREVIOUS_FILE_NAME
        self.retention = retention
        self._clock = clock
        self._lock = threading.Lock()
        self._handle = None
        self._session_entries: list[SpikeEntry] = []
        self.session_started_at: datetime | None = None

    # -------------------------------------------------------------- lifecycle
    def start_session(self) -> None:
        """Archive the leftover session, drop old entries and open a fresh session."""
        with self._lock:
            try:
                self.directory.mkdir(parents=True, exist_ok=True)
            except OSError:
                LOGGER.exception("Cannot create the log folder %s", self.directory)
            archived = self._archive_and_clean_locked(include_leftover=True)
            self.session_started_at = self._clock().replace(microsecond=0)
            self._session_entries = []
            # If the leftover could not be archived, keep it: the new session is
            # appended and both get archived on a later start.
            mode = "w" if archived else "a"
            try:
                self._handle = open(self.current_path, mode, encoding="utf-8", newline="\n")
                self._handle.write(SessionMarker(self.session_started_at).to_line() + "\n")
                self._handle.flush()
            except OSError:
                LOGGER.exception("Cannot open %s; spikes of this session stay in memory only",
                                 self.current_path)
                self._handle = None

    def close(self) -> None:
        with self._lock:
            if self._handle is not None:
                try:
                    self._handle.close()
                except OSError:
                    LOGGER.exception("Closing the spike log failed")
                finally:
                    self._handle = None

    # ----------------------------------------------------------------- writes
    def record(self, result: PingResult) -> SpikeEntry:
        entry = entry_from_result(result)
        with self._lock:
            self._session_entries.append(entry)
            if self._handle is not None:
                try:
                    self._handle.write(entry.to_line() + "\n")
                    self._handle.flush()
                except OSError:
                    LOGGER.exception("Writing a ping spike failed")
        return entry

    def cleanup(self) -> None:
        """Drop previous-session entries older than the retention period."""
        with self._lock:
            self._archive_and_clean_locked(include_leftover=False)

    # ------------------------------------------------------------------ reads
    def current_entries(self, limit: int | None = None) -> list[SpikeEntry]:
        """Entries of this session, oldest first (only the newest ``limit``)."""
        with self._lock:
            if limit is not None and len(self._session_entries) > limit:
                return self._session_entries[-limit:] if limit > 0 else []
            return list(self._session_entries)

    def session_entry_count(self) -> int:
        with self._lock:
            return len(self._session_entries)

    def previous_items(self) -> list[LogItem]:
        """Parsed previous sessions, oldest first (markers + entries)."""
        with self._lock:
            text = self._read(self.previous_path)
        return [item for item in map(parse_line, text.splitlines()) if item is not None]

    def recent_previous_items(self, limit: int) -> RecentItems:
        """The newest ``limit`` entries of previous sessions. Only those lines are
        parsed, so it stays fast with a day of entries in the file.

        Raises OSError when the file exists but cannot be read.
        """
        with self._lock:
            if not self.previous_path.exists():
                return RecentItems([], False, False)
            raw = self.previous_path.read_bytes()
        lines = decode_text(raw).splitlines()
        items: list[LogItem] = []
        entries = 0
        truncated = partial_first = False
        for index in range(len(lines) - 1, -1, -1):
            item = parse_line(lines[index])
            if item is None:
                continue
            if isinstance(item, SpikeEntry):
                if entries >= limit:
                    truncated = True
                    if items and isinstance(items[-1], SpikeEntry):
                        # The oldest included session continues further up:
                        # add its header and mark it as incomplete.
                        partial_first = True
                        for earlier in range(index - 1, -1, -1):
                            if lines[earlier].lstrip().startswith("==="):
                                marker = parse_line(lines[earlier])  # None if damaged
                                if marker is not None:
                                    items.append(marker)
                                break  # never borrow the header of an older session
                    break
                entries += 1
            items.append(item)
        items.reverse()
        return RecentItems(items, truncated, partial_first)

    # --------------------------------------------------------------- internal
    def _read(self, path: Path) -> str:
        try:
            return read_text(path) if path.exists() else ""
        except OSError:
            LOGGER.exception("Reading %s failed", path)
            return ""

    def _archive_and_clean_locked(self, include_leftover: bool) -> bool:
        """Returns False when a leftover session exists but could not be archived."""
        try:
            original = self.previous_path.read_bytes() if self.previous_path.exists() else b""
        except OSError:
            LOGGER.exception("Reading %s failed; leaving it untouched", self.previous_path)
            return not (include_leftover and self.current_path.exists())
        previous_lines = [line.rstrip() for line in decode_text(original).splitlines()]

        leftover_lines: list[str] = []
        if include_leftover:
            try:
                leftover_text = read_text(self.current_path) if self.current_path.exists() else ""
            except OSError:
                LOGGER.exception("Reading the leftover session failed; keeping it for later")
                return False
            leftover = [line.rstrip() for line in leftover_text.splitlines() if line.strip()]
            has_entries = any(isinstance(parse_line(line), SpikeEntry) for line in leftover)
            first = parse_line(leftover[0]) if leftover else None
            already_archived = isinstance(first, SessionMarker) and leftover[0] in previous_lines
            if has_entries and not already_archived:
                leftover_lines = leftover

        cutoff = self._clock() - self.retention
        kept: list[str] = []
        pending_marker: str | None = None
        for line in previous_lines + leftover_lines:
            item = parse_line(line)
            if isinstance(item, SessionMarker):
                pending_marker = line
                continue
            if isinstance(item, SpikeEntry):
                if item.timestamp < cutoff:
                    continue
                if pending_marker is not None:
                    kept.append(pending_marker)
                    pending_marker = None
                kept.append(line)
            elif line.strip():
                kept.append(line)  # unknown legacy line: keep it

        new_text = "\n".join(kept) + ("\n" if kept else "")
        if new_text.encode("utf-8") != original:
            try:
                if kept or self.previous_path.exists():
                    atomic_write_text(self.previous_path, new_text)
            except OSError:
                LOGGER.exception("Updating %s failed", self.previous_path)
                return not leftover_lines
        if leftover_lines:
            LOGGER.info("Archived %d lines of the previous session", len(leftover_lines))
        return True
