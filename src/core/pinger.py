"""
ICMP echo implementations.

``WindowsIcmpPinger`` talks to the Windows ICMP API (``IcmpSendEcho`` from
iphlpapi.dll) directly through ctypes – the same API ``ping.exe`` uses, but
without spawning a process (and a hidden console) for every single ping, and
without parsing localized ``ping.exe`` output. No admin rights are needed.

``SubprocessPinger`` is a fallback for development on Linux/WSL and
``SimulatedPinger`` produces fake but realistic data for demos and tests
(``PING_MONITOR_SIMULATE=1``).
"""

import ctypes
import logging
import math
import os
import random
import re
import socket
import subprocess
import threading
import time
import zlib
from typing import Protocol

from src.core import validation
from src.core.models import PingReply, PingStatus

LOGGER = logging.getLogger(__name__)

SIMULATE_ENV = "PING_MONITOR_SIMULATE"


class Pinger(Protocol):
    def ping(self, host: str, timeout_ms: int) -> PingReply: ...

    def close(self) -> None: ...


# --------------------------------------------------------------------------- DNS
class HostResolver:
    """Resolves host names to IPv4 addresses with a small time-based cache.

    Failures are cached too, so a dead DNS server does not stall every ping.
    """

    TTL_SECONDS = 300.0
    FAILURE_TTL_SECONDS = 60.0

    def __init__(self) -> None:
        self._cache: dict[str, tuple[str, float]] = {}
        self._failures: dict[str, tuple[OSError, float]] = {}

    def resolve(self, host: str) -> str:
        host = host.strip()
        if validation.is_ipv4(host):
            return host
        now = time.monotonic()
        cached = self._cache.get(host)
        if cached and now - cached[1] < self.TTL_SECONDS:
            return cached[0]
        failed = self._failures.get(host)
        if failed and now - failed[1] < self.FAILURE_TTL_SECONDS:
            if cached:  # keep using the last known address
                return cached[0]
            raise failed[0]
        try:
            infos = socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_STREAM)
        except OSError as error:
            self._failures[host] = (error, time.monotonic())
            if cached:  # keep using the last known address
                return cached[0]
            raise
        address = str(infos[0][4][0])
        self._cache[host] = (address, time.monotonic())
        self._failures.pop(host, None)
        return address


def resolve_ipv4(host: str) -> str:
    """One-off blocking lookup (used by the config UI to auto-fill IPs)."""
    infos = socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_STREAM)
    return str(infos[0][4][0])


# ------------------------------------------------------------------ Windows ICMP
# Status codes from ipexport.h
IP_SUCCESS = 0
IP_BUF_TOO_SMALL = 11001
IP_REQ_TIMED_OUT = 11010
IP_GENERAL_FAILURE = 11050
ERROR_NETWORK_UNREACHABLE = 1231
ERROR_HOST_UNREACHABLE = 1232

_UNREACHABLE_CODES = {
    11002: "Destination network unreachable",
    11003: "Destination host unreachable",
    11004: "Destination protocol unreachable",
    11005: "Destination port unreachable",
    11012: "Bad route",
    11013: "TTL expired in transit",
    11014: "TTL expired during reassembly",
    11018: "Bad destination",
    IP_GENERAL_FAILURE: "Network is unavailable",
    ERROR_NETWORK_UNREACHABLE: "Network unreachable",
    ERROR_HOST_UNREACHABLE: "Host unreachable",
}
# Remaining IP_* status codes (ipexport.h). They overlap with Winsock error
# numbers, so FormatError would return unrelated text for them.
_IP_STATUS_TEXT = {
    IP_BUF_TOO_SMALL: "Reply buffer too small",
    11006: "Not enough resources",
    11007: "Bad IP option",
    11008: "Hardware error",
    11009: "Packet too big",
    11011: "Bad request",
    11015: "Parameter problem",
    11016: "Source quench",
    11017: "IP option too big",
}


class IP_OPTION_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("Ttl", ctypes.c_ubyte),
        ("Tos", ctypes.c_ubyte),
        ("Flags", ctypes.c_ubyte),
        ("OptionsSize", ctypes.c_ubyte),
        ("OptionsData", ctypes.c_void_p),
    ]


class ICMP_ECHO_REPLY(ctypes.Structure):
    # ULONG is 32 bits on Windows; spelled out so the layout is the same everywhere.
    _fields_ = [
        ("Address", ctypes.c_uint32),
        ("Status", ctypes.c_uint32),
        ("RoundTripTime", ctypes.c_uint32),
        ("DataSize", ctypes.c_uint16),
        ("Reserved", ctypes.c_uint16),
        ("Data", ctypes.c_void_p),
        ("Options", IP_OPTION_INFORMATION),
    ]


def reply_for_status(code: int, rtt_ms: int | None) -> PingReply:
    """Translate an ICMP status / Win32 error code into a PingReply."""
    if code == IP_SUCCESS:
        return PingReply(PingStatus.OK, int(rtt_ms or 0))
    if code == IP_REQ_TIMED_OUT:
        return PingReply(PingStatus.TIMEOUT, None, "Request timed out")
    if code in _UNREACHABLE_CODES:
        return PingReply(PingStatus.UNREACHABLE, None, _UNREACHABLE_CODES[code])
    return PingReply(PingStatus.ERROR, None, _format_error(code))


def _format_error(code: int) -> str:
    if code in _IP_STATUS_TEXT:
        return f"{_IP_STATUS_TEXT[code]} (ICMP status {code})"
    if 11000 <= code < 12000:
        return f"ICMP status {code}"
    format_error = getattr(ctypes, "FormatError", None)
    if format_error is not None:
        try:
            message = format_error(code).strip()
            if message:
                return f"{message} (code {code})"
        except Exception:  # pragma: no cover - best effort only
            pass
    return f"ICMP error {code}"


_ICMP_API = None
_ICMP_API_LOCK = threading.Lock()


def _icmp_api():
    """Load iphlpapi.dll once and declare the function signatures."""
    global _ICMP_API
    with _ICMP_API_LOCK:
        if _ICMP_API is None:
            from ctypes import wintypes

            dll = ctypes.WinDLL("iphlpapi.dll", use_last_error=True)
            dll.IcmpCreateFile.argtypes = []
            dll.IcmpCreateFile.restype = wintypes.HANDLE
            dll.IcmpCloseHandle.argtypes = [wintypes.HANDLE]
            dll.IcmpCloseHandle.restype = wintypes.BOOL
            dll.IcmpSendEcho.argtypes = [
                wintypes.HANDLE,  # IcmpHandle
                ctypes.c_uint32,  # DestinationAddress (IPAddr, network byte order)
                ctypes.c_void_p,  # RequestData
                wintypes.WORD,  # RequestSize
                ctypes.c_void_p,  # RequestOptions
                ctypes.c_void_p,  # ReplyBuffer
                wintypes.DWORD,  # ReplySize
                wintypes.DWORD,  # Timeout (ms)
            ]
            dll.IcmpSendEcho.restype = wintypes.DWORD
            _ICMP_API = dll
        return _ICMP_API


def ipv4_to_ipaddr(address: str) -> int:
    """IPv4 string -> IPAddr value (network byte order bytes in a little-endian ULONG)."""
    return int.from_bytes(socket.inet_aton(address), "little")


class WindowsIcmpPinger:
    """One ICMP handle per instance; create one pinger per worker thread."""

    PAYLOAD = b"abcdefghijklmnopqrstuvwabcdefghi"  # same 32 bytes as ping.exe

    def __init__(self) -> None:
        self._api = _icmp_api()
        handle = self._api.IcmpCreateFile()
        if not handle or handle == ctypes.c_void_p(-1).value:
            raise OSError(ctypes.get_last_error(), "IcmpCreateFile failed")
        self._handle = handle
        self._request = ctypes.create_string_buffer(self.PAYLOAD, len(self.PAYLOAD))
        # Room for one reply + echoed payload + an ICMP error message, with slack.
        self._reply_size = ctypes.sizeof(ICMP_ECHO_REPLY) + len(self.PAYLOAD) + 8 + 64
        self._reply = ctypes.create_string_buffer(self._reply_size)
        self._resolver = HostResolver()

    def ping(self, host: str, timeout_ms: int) -> PingReply:
        if self._handle is None:
            return PingReply(PingStatus.ERROR, None, "Pinger is closed")
        try:
            address = self._resolver.resolve(host)
        except OSError as error:
            return PingReply(PingStatus.UNREACHABLE, None, f"DNS lookup failed ({error})")

        count = self._api.IcmpSendEcho(
            self._handle,
            ipv4_to_ipaddr(address),
            self._request,
            len(self.PAYLOAD),
            None,
            self._reply,
            self._reply_size,
            max(1, int(timeout_ms)),
        )
        if count == 0:
            return reply_for_status(ctypes.get_last_error(), None)
        reply = ICMP_ECHO_REPLY.from_buffer(self._reply)
        return reply_for_status(reply.Status, reply.RoundTripTime)

    def close(self) -> None:
        if self._handle is not None:
            try:
                self._api.IcmpCloseHandle(self._handle)
            finally:
                self._handle = None


# ----------------------------------------------------------- subprocess fallback
# Language independent: matches "time=12ms", "čas=12ms", "time<1ms", "time=12.6 ms"...
_TIME_RE = re.compile(r"[=<]\s*(\d+(?:[.,]\d+)?)\s*ms\b", re.IGNORECASE)


class SubprocessPinger:
    """Fallback using the system ``ping`` command (development on Linux/WSL)."""

    def __init__(self) -> None:
        self._is_windows = os.name == "nt"

    def ping(self, host: str, timeout_ms: int) -> PingReply:
        if self._is_windows:
            command = ["ping", "-n", "1", "-w", str(int(timeout_ms)), host]
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        else:
            command = ["ping", "-c", "1", "-W", str(max(1, math.ceil(timeout_ms / 1000))), host]
            flags = 0
        env = {**os.environ, "LC_ALL": "C", "LANG": "C"}
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_ms / 1000 + 2,
                creationflags=flags,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return PingReply(PingStatus.TIMEOUT, None, "Request timed out")
        except OSError as error:
            return PingReply(PingStatus.ERROR, None, f"Cannot run ping ({error})")

        match = _TIME_RE.search(completed.stdout)
        if completed.returncode == 0 and match:
            return PingReply(PingStatus.OK, max(0, round(float(match.group(1).replace(",", ".")))))
        if completed.returncode == 0:
            # Windows ping returns 0 for "Destination host unreachable" replies.
            return PingReply(PingStatus.UNREACHABLE, None, "Destination host unreachable")
        if completed.returncode == 1:
            return PingReply(PingStatus.TIMEOUT, None, "Request timed out")
        detail = (completed.stderr or completed.stdout).strip().splitlines()
        return PingReply(PingStatus.ERROR, None, detail[-1] if detail else "ping failed")

    def close(self) -> None:
        pass


# --------------------------------------------------------------------- simulator
class SimulatedPinger:
    """Fake but plausible latencies (per-host baseline, jitter, rare spikes and losses)."""

    def __init__(self, seed: int | None = None, sleep: bool = True) -> None:
        self._seed = seed
        self._sleep = sleep
        self._rngs: dict[str, random.Random] = {}

    def _rng(self, host: str) -> random.Random:
        if host not in self._rngs:
            seed = zlib.crc32(host.encode()) if self._seed is None else self._seed
            self._rngs[host] = random.Random(seed ^ int(time.time() // 3600))
        return self._rngs[host]

    def ping(self, host: str, timeout_ms: int) -> PingReply:
        rng = self._rng(host)
        base = 8 + (zlib.crc32(host.encode()) % 18)
        roll = rng.random()
        if roll < 0.003:
            if self._sleep:
                time.sleep(min(timeout_ms, 400) / 1000)
            return PingReply(PingStatus.TIMEOUT, None, "Request timed out")
        rtt = base + abs(rng.gauss(0, 1.6))
        if roll < 0.02:
            rtt += rng.uniform(25, 110)
        elif roll < 0.06:
            rtt += rng.uniform(10, 25)
        rtt_ms = int(round(rtt))
        if self._sleep:
            time.sleep(rtt_ms / 1000)
        return PingReply(PingStatus.OK, rtt_ms)

    def close(self) -> None:
        pass


def create_pinger() -> Pinger:
    """Best pinger for this platform (one instance per worker thread)."""
    if os.environ.get(SIMULATE_ENV, "").strip() not in ("", "0", "false", "no"):
        return SimulatedPinger()
    if os.name == "nt":
        try:
            return WindowsIcmpPinger()
        except Exception:  # pragma: no cover - only on broken Windows installs
            LOGGER.exception("Windows ICMP API unavailable, falling back to ping.exe")
    return SubprocessPinger()
