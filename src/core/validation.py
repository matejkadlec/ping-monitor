"""
Input validation shared by the settings loader and the config UI.
"""

import ipaddress
import re

_DIGITS = frozenset("0123456789")
_LABEL_RE = re.compile(r"(?!-)[a-z0-9-]{1,63}(?<!-)\Z", re.IGNORECASE | re.ASCII)
_TLD_RE = re.compile(r"[a-z]{2,63}\Z", re.IGNORECASE | re.ASCII)


def is_ipv4(value: str) -> bool:
    """Dotted-quad IPv4 address made of plain ASCII digits only (e.g. ``1.1.1.1``)."""
    if not value or any(ch not in _DIGITS and ch != "." for ch in value):
        return False
    if value.count(".") != 3:
        return False
    try:
        ipaddress.IPv4Address(value)
    except ValueError:
        return False
    return True


def is_hostname(value: str) -> bool:
    """Domain-like server name: at least ``x.yz`` (labels of letters, digits and dashes)."""
    if not value or len(value) > 253:
        return False
    labels = value.split(".")
    if len(labels) < 2:
        return False
    if not all(_LABEL_RE.match(label) for label in labels):
        return False
    return bool(_TLD_RE.match(labels[-1]))


def parse_int(text: str) -> int | None:
    """Parse an optionally negative integer typed by the user, ``None`` if invalid."""
    text = text.strip()
    body = text[1:] if text.startswith("-") else text
    if not body or any(ch not in _DIGITS for ch in body):
        return None
    return int(text)
