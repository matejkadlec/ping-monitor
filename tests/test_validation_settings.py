import json

import pytest

from src.core import validation
from src.core.models import ServerSpec
from src.core.settings import (
    PRESERVE_FOREVER,
    Settings,
    load_settings,
    save_settings,
)


@pytest.mark.parametrize("value", ["1.1.1.1", "8.8.8.8", "77.75.77.222", "0.0.0.0", "255.255.255.255"])
def test_ipv4_valid(value):
    assert validation.is_ipv4(value)


@pytest.mark.parametrize(
    "value",
    ["", "1.1.1", "1.1.1.1.1", "256.1.1.1", "1.1.1.a", " 1.1.1.1", "1.1.1.1 ", "01.1.1.1",
     "１.1.1.1", "1..1.1", "-1.1.1.1", "1.1.1.²"],
)
def test_ipv4_invalid(value):
    assert not validation.is_ipv4(value)


@pytest.mark.parametrize("value", ["cloudflare.com", "seznam.cz", "a.bc", "my-server.example.org", "X.YZ"])
def test_hostname_valid(value):
    assert validation.is_hostname(value)


@pytest.mark.parametrize(
    "value",
    ["", "localhost", "cloudflare", "-a.com", "a-.com", "a..com", "a.c", "a.c0m", "exa mple.com",
     "ex_ample.com", "příklad.cz", "a." + "b" * 64 + ".com", "1.1.1.1"],
)
def test_hostname_invalid(value):
    assert not validation.is_hostname(value)


@pytest.mark.parametrize("text,expected", [("10", 10), (" 7 ", 7), ("-1", -1), ("", None), ("1e3", None),
                                           ("+5", None), ("--1", None), ("٣", None), ("12a", None)])
def test_parse_int(text, expected):
    assert validation.parse_int(text) == expected


def test_defaults_are_valid():
    assert Settings().validate() == []


def test_validate_reports_cells_and_fields():
    settings = Settings(
        servers=(ServerSpec("cloudflare.com", "1.1.1.1"), ServerSpec("bad name", "300.1.1.1"),
                 ServerSpec("Cloudflare.com", "1.0.0.1")),
        ping_threshold_healthy=50,
        ping_threshold_degraded=40,
        ping_interval=0,
        preserved_minutes=1000,
    )
    errors = settings.validate()
    cells = {(e.row, e.column) for e in errors if e.field == "servers"}
    assert (1, "name") in cells and (1, "host") in cells and (2, "name") in cells
    fields = {e.field for e in errors}
    assert {"ping_threshold_degraded", "ping_interval", "preserved_minutes"} <= fields


def test_preserve_forever_is_valid():
    assert Settings(preserved_minutes=PRESERVE_FOREVER).validate() == []


def test_roundtrip(tmp_path):
    path = tmp_path / "app_config.json"
    settings = Settings(
        servers=(ServerSpec("google.com", "8.8.8.8"),),
        ping_threshold_healthy=30,
        ping_threshold_degraded=80,
        ping_interval=2,
        preserved_minutes=PRESERVE_FOREVER,
        close_to_tray=False,
        notifications=False,
        background_image=True,
    )
    save_settings(settings, path)
    assert load_settings(path) == settings
    assert list(tmp_path.iterdir()) == [path]  # no temp files left behind


def test_loads_legacy_file_and_sanitizes(tmp_path):
    path = tmp_path / "app_config.json"
    path.write_text(json.dumps({
        "servers": {"cloudflare.com": "1.1.1.1", "": "2.2.2.2", "My Router": "192.168.1.1"},
        "ping_threshold_healthy": 70,
        "ping_threshold_degraded": 50,
        "ping_interval": "3",
        "preserved_minutes": 5000,
        "close_to_tray": "yes",
    }), encoding="utf-8")
    settings = load_settings(path)
    # Lenient loading keeps legacy names, the UI flags them on save.
    assert settings.servers == (ServerSpec("cloudflare.com", "1.1.1.1"), ServerSpec("My Router", "192.168.1.1"))
    assert settings.ping_threshold_degraded == 70
    assert settings.ping_interval == 3
    assert settings.preserved_minutes == 999
    assert settings.close_to_tray is True


def test_corrupted_file_gives_defaults(tmp_path):
    path = tmp_path / "app_config.json"
    path.write_text("{not json", encoding="utf-8")
    assert load_settings(path) == Settings()
    assert load_settings(tmp_path / "missing.json") == Settings()


@pytest.mark.parametrize("raw,expected", [("Infinity", 10), (1e999, 10), ("-1", -1), (-1.0, -1), (12.0, 12),
                                          ("12", 12), (12.5, 10), (True, 10)])
def test_preserved_minutes_loading(tmp_path, raw, expected):
    path = tmp_path / "app_config.json"
    text = json.dumps({"preserved_minutes": raw}) if raw != "Infinity" else '{"preserved_minutes": Infinity}'
    path.write_text(text, encoding="utf-8")
    assert load_settings(path).preserved_minutes == expected


def test_app_version_matches_pyproject():
    import tomllib
    from pathlib import Path

    from src.core.paths import APP_VERSION

    pyproject = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
    assert APP_VERSION == pyproject["project"]["version"]


def test_the_exe_takes_over_the_settings_of_the_source_version(tmp_path, monkeypatch):
    import sys

    from src.core import settings as settings_module
    from src.core.paths import source_data_dirs

    project = tmp_path / "ping-monitor"
    (project / "dist").mkdir(parents=True)
    (project / "logs").mkdir()
    (project / "logs" / "app_config.json").write_text('{"ping_interval": 7}', encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(project / "dist" / "PingMonitor.exe"))
    assert project / "logs" in source_data_dirs()
    exe_data = tmp_path / "LocalAppData" / "PingMonitor"
    exe_data.mkdir(parents=True)
    loaded = settings_module.load_settings(exe_data / "app_config.json")
    assert loaded.ping_interval == 7
