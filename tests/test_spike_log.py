from datetime import datetime, timedelta

from src.core.models import PingResult, PingStatus
from src.core.spike_log import SessionMarker, SpikeEntry, SpikeLog, parse_line

NOW = datetime(2026, 11, 10, 12, 0, 0)


def result(seconds_ago: int, status=PingStatus.OK, rtt=80, server="cloudflare.com"):
    return PingResult(server, "1.1.1.1", NOW - timedelta(seconds=seconds_ago), status, rtt if status is PingStatus.OK else None)


def test_parse_lines():
    assert parse_line("[2026-11-10 01:46:37] cloudflare.com: 75ms") == SpikeEntry(
        datetime(2026, 11, 10, 1, 46, 37), "cloudflare.com", "spike", 75)
    assert parse_line("[2026-11-10 01:46:37] cloudflare.com: timeout") == SpikeEntry(
        datetime(2026, 11, 10, 1, 46, 37), "cloudflare.com", "timeout")
    assert parse_line("=== Session 2026-11-10 00:18:03 ===") == SessionMarker(datetime(2026, 11, 10, 0, 18, 3))
    assert parse_line("") is None
    assert parse_line("garbage") is None


def test_session_lifecycle_and_crash_safety(tmp_path):
    clock = [NOW]
    log = SpikeLog(tmp_path, clock=lambda: clock[0])
    log.start_session()
    log.record(result(10))
    log.record(result(5, PingStatus.TIMEOUT))
    assert [e.kind for e in log.current_entries()] == ["spike", "timeout"]
    assert log.previous_items() == []
    # Simulate a crash: no close(), next start archives the leftover session.
    clock[0] = NOW + timedelta(minutes=1)
    second = SpikeLog(tmp_path, clock=lambda: clock[0])
    second.start_session()
    items = second.previous_items()
    assert isinstance(items[0], SessionMarker)
    assert [i.kind for i in items[1:]] == ["spike", "timeout"]
    assert second.current_entries() == []
    second.close()
    log.close()


def test_sessions_without_spikes_are_not_archived(tmp_path):
    log = SpikeLog(tmp_path, clock=lambda: NOW)
    log.start_session()
    log.close()
    again = SpikeLog(tmp_path, clock=lambda: NOW)
    again.start_session()
    assert again.previous_items() == []
    again.close()


def test_retention_drops_old_entries_and_empty_sessions(tmp_path):
    previous = tmp_path / "ping_spikes.log"
    old = NOW - timedelta(hours=30)
    recent = NOW - timedelta(hours=2)
    previous.write_text(
        "\r\n".join([
            SessionMarker(old).to_line(),
            SpikeEntry(old, "a.com", "spike", 90).to_line(),
            SessionMarker(recent).to_line(),
            SpikeEntry(recent - timedelta(hours=23), "a.com", "spike", 91).to_line(),
            SpikeEntry(recent, "a.com", "spike", 92).to_line(),
        ]) + "\r\n",
        encoding="utf-8",
    )
    log = SpikeLog(tmp_path, clock=lambda: NOW)
    log.start_session()
    items = log.previous_items()
    assert items == [SessionMarker(recent), SpikeEntry(recent, "a.com", "spike", 92)]
    log.close()


def test_legacy_utf16_file_is_converted_and_extended(tmp_path):
    previous = tmp_path / "ping_spikes.log"
    previous.write_bytes(("[2026-11-10 11:00:00] a.com: 70ms\n").encode("utf-16"))
    log = SpikeLog(tmp_path, clock=lambda: NOW)
    log.start_session()
    log.record(result(1))
    log.close()
    assert previous.read_bytes().decode("utf-8").startswith("[2026-11-10 11:00:00] a.com: 70ms")
    again = SpikeLog(tmp_path, clock=lambda: NOW + timedelta(minutes=1))
    again.start_session()
    items = again.previous_items()
    assert items[0] == SpikeEntry(datetime(2026, 11, 10, 11, 0, 0), "a.com", "spike", 70)
    assert [i.kind for i in items if isinstance(i, SpikeEntry)] == ["spike", "spike"]
    again.close()


def test_leftover_is_never_archived_twice(tmp_path):
    log = SpikeLog(tmp_path, clock=lambda: NOW)
    log.start_session()
    log.record(result(3))
    log.close()
    leftover = (tmp_path / "ping_spikes_current.log").read_text(encoding="utf-8")
    second = SpikeLog(tmp_path, clock=lambda: NOW + timedelta(minutes=1))
    second.start_session()
    second.close()
    # Crash right after archiving: the old current file is still there.
    (tmp_path / "ping_spikes_current.log").write_text(leftover, encoding="utf-8")
    third = SpikeLog(tmp_path, clock=lambda: NOW + timedelta(minutes=2))
    third.start_session()
    entries = [i for i in third.previous_items() if isinstance(i, SpikeEntry)]
    assert len(entries) == 1
    third.close()


def test_file_errors_never_break_the_session(tmp_path):
    (tmp_path / "ping_spikes.log").mkdir()  # unreadable "file"
    log = SpikeLog(tmp_path, clock=lambda: NOW)
    log.start_session()
    log.record(result(2))
    assert len(log.current_entries()) == 1
    assert log.previous_items() == []
    log.cleanup()
    log.close()


def test_unreadable_leftover_is_kept(tmp_path, monkeypatch):
    import src.core.spike_log as module

    log = SpikeLog(tmp_path, clock=lambda: NOW)
    log.start_session()
    log.record(result(3))
    log.close()
    real_read = module.read_text

    def flaky(path):
        if path.name == "ping_spikes_current.log":
            raise PermissionError("locked")
        return real_read(path)

    monkeypatch.setattr(module, "read_text", flaky)
    second = SpikeLog(tmp_path, clock=lambda: NOW + timedelta(minutes=1))
    second.start_session()
    second.close()
    monkeypatch.setattr(module, "read_text", real_read)
    third = SpikeLog(tmp_path, clock=lambda: NOW + timedelta(minutes=2))
    third.start_session()
    assert [i.rtt_ms for i in third.previous_items() if isinstance(i, SpikeEntry)] == [80]
    third.close()
