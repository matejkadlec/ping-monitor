import ctypes
import os

import pytest

from src.core import pinger as pinger_module
from src.core.models import PingStatus
from src.core.pinger import (
    ICMP_ECHO_REPLY,
    IP_REQ_TIMED_OUT,
    IP_SUCCESS,
    SimulatedPinger,
    SubprocessPinger,
    create_pinger,
    ipv4_to_ipaddr,
    reply_for_status,
)


@pytest.mark.skipif(ctypes.sizeof(ctypes.c_void_p) != 8, reason="64-bit layout")
def test_icmp_echo_reply_layout_matches_windows_x64():
    assert ctypes.sizeof(ICMP_ECHO_REPLY) == 40
    assert ICMP_ECHO_REPLY.Status.offset == 4
    assert ICMP_ECHO_REPLY.RoundTripTime.offset == 8
    assert ICMP_ECHO_REPLY.Data.offset == 16
    assert ICMP_ECHO_REPLY.Options.offset == 24


def test_reply_parsing_from_raw_buffer():
    buffer = ctypes.create_string_buffer(ctypes.sizeof(ICMP_ECHO_REPLY) + 64)
    reply = ICMP_ECHO_REPLY.from_buffer(buffer)
    reply.Status = IP_SUCCESS
    reply.RoundTripTime = 23
    parsed = ICMP_ECHO_REPLY.from_buffer(buffer)
    assert reply_for_status(parsed.Status, parsed.RoundTripTime).rtt_ms == 23


def test_status_mapping():
    assert reply_for_status(IP_SUCCESS, 0).status is PingStatus.OK
    assert reply_for_status(IP_SUCCESS, 0).rtt_ms == 0
    assert reply_for_status(IP_REQ_TIMED_OUT, None).status is PingStatus.TIMEOUT
    assert reply_for_status(11003, None).status is PingStatus.UNREACHABLE
    assert reply_for_status(11050, None).status is PingStatus.UNREACHABLE
    error = reply_for_status(9999, None)
    assert error.status is PingStatus.ERROR and "9999" in error.detail
    assert "buffer" in reply_for_status(11001, None).detail.lower()
    assert reply_for_status(11042, None).detail == "ICMP status 11042"


def test_resolver_caches_failures(monkeypatch):
    from src.core.pinger import HostResolver

    calls = []

    def fake_getaddrinfo(host, *args):
        calls.append(host)
        raise OSError("no such host")

    monkeypatch.setattr(pinger_module.socket, "getaddrinfo", fake_getaddrinfo)
    resolver = HostResolver()
    for _ in range(3):
        with pytest.raises(OSError):
            resolver.resolve("example.org")
    assert calls == ["example.org"]
    assert resolver.resolve(" 1.1.1.1 ") == "1.1.1.1"


def test_ipaddr_is_network_order_in_memory():
    value = ipv4_to_ipaddr("1.2.3.4")
    assert value.to_bytes(4, "little") == bytes([1, 2, 3, 4])


def test_simulator_is_plausible():
    sim = SimulatedPinger(seed=1, sleep=False)
    replies = [sim.ping("1.1.1.1", 900) for _ in range(2000)]
    ok = [r.rtt_ms for r in replies if r.status is PingStatus.OK]
    assert len(ok) > 1900
    assert min(ok) >= 8 and max(ok) < 200


def test_create_pinger_honours_simulation(monkeypatch):
    monkeypatch.setenv(pinger_module.SIMULATE_ENV, "1")
    assert isinstance(create_pinger(), SimulatedPinger)
    monkeypatch.setenv(pinger_module.SIMULATE_ENV, "0")
    if os.name != "nt":
        assert isinstance(create_pinger(), SubprocessPinger)


def test_subprocess_parsing(monkeypatch):
    class Completed:
        def __init__(self, returncode, stdout):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = ""

    outputs = iter([
        Completed(0, "64 bytes from 1.1.1.1: icmp_seq=1 ttl=57 time=12.6 ms"),
        Completed(0, "Reply from 1.1.1.1: bytes=32 time<1ms TTL=57"),
        Completed(0, "Odpověď od 1.1.1.1: bajty=32 čas=14ms TTL=57"),
        Completed(0, "Reply from 192.168.1.1: Destination host unreachable."),
        Completed(1, "Request timed out."),
    ])
    monkeypatch.setattr(pinger_module.subprocess, "run", lambda *a, **k: next(outputs))
    sub = SubprocessPinger()
    assert sub.ping("1.1.1.1", 900).rtt_ms == 13
    assert sub.ping("1.1.1.1", 900).rtt_ms == 1
    assert sub.ping("1.1.1.1", 900).rtt_ms == 14
    assert sub.ping("1.1.1.1", 900).status is PingStatus.UNREACHABLE
    assert sub.ping("1.1.1.1", 900).status is PingStatus.TIMEOUT


def test_resolver_reuses_last_good_address(monkeypatch):
    from src.core.pinger import HostResolver

    answers = iter([[(0, 0, 0, "", ("1.2.3.4", 0))]])

    def fake_getaddrinfo(host, *args):
        try:
            return next(answers)
        except StopIteration:
            raise OSError("dns down") from None

    monkeypatch.setattr(pinger_module.socket, "getaddrinfo", fake_getaddrinfo)
    resolver = HostResolver()
    resolver.TTL_SECONDS = 0  # force re-resolving
    assert [resolver.resolve("example.org") for _ in range(3)] == ["1.2.3.4"] * 3
