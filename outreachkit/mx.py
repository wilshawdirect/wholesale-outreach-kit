"""MX validation gate: never hand a dead domain to SMTP.

The resolver is injectable so tests and offline runs never touch the network.
``SystemResolver`` is a minimal stdlib-only DNS client (one UDP question,
QTYPE=MX). A transport failure is deliberately a *different* outcome from
"no MX record" — a flaky nameserver must never quarantine a live domain.
"""
from __future__ import annotations

import secrets
import socket
import struct
from typing import Mapping, Protocol

_QTYPE_MX = 15


class MXLookupError(Exception):
    """Raised when an MX lookup could not be completed (network/DNS failure)."""


class MXResolver(Protocol):
    """Anything that can answer: does this domain publish an MX record?"""

    def has_mx(self, domain: str) -> bool:
        """Return True if ``domain`` has at least one MX record."""
        ...


class StaticResolver:
    """Table-driven resolver for tests and offline dry-runs."""

    def __init__(self, table: Mapping[str, bool] | None = None, default: bool = True) -> None:
        self._table = {k.lower(): v for k, v in (table or {}).items()}
        self._default = default

    def has_mx(self, domain: str) -> bool:
        """Answer from the static table; unknown domains get the default."""
        return self._table.get(domain.lower(), self._default)


class SystemResolver:
    """Stdlib-only DNS MX lookup over UDP.

    Sends a single MX question to ``nameserver`` and scans the answer section
    for a type-15 record. NXDOMAIN and empty answers mean "no MX"; timeouts
    and malformed replies raise :class:`MXLookupError`.
    """

    def __init__(self, nameserver: str = "1.1.1.1", timeout: float = 3.0) -> None:
        self.nameserver = nameserver
        self.timeout = timeout

    def has_mx(self, domain: str) -> bool:
        """Query the configured nameserver; True iff an MX answer comes back."""
        qid = secrets.randbits(16)
        try:
            query = _encode_mx_query(domain, qid)
        except UnicodeEncodeError as exc:
            raise MXLookupError(f"non-ASCII domain not supported: {domain!r}") from exc
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.settimeout(self.timeout)
                sock.sendto(query, (self.nameserver, 53))
                reply = sock.recv(4096)
        except OSError as exc:
            raise MXLookupError(f"DNS transport failure for {domain!r}: {exc}") from exc
        return _reply_has_mx(reply, qid, domain)


def _encode_mx_query(domain: str, qid: int) -> bytes:
    """Build a standard recursive DNS query for ``domain``, QTYPE=MX."""
    header = struct.pack(">HHHHHH", qid, 0x0100, 1, 0, 0, 0)
    qname = b"".join(
        bytes([len(label)]) + label.encode("ascii")
        for label in domain.rstrip(".").split(".")
    )
    return header + qname + b"\x00" + struct.pack(">HH", _QTYPE_MX, 1)


def _skip_name(data: bytes, offset: int) -> int:
    """Advance past a (possibly compressed) DNS name; return the new offset."""
    while True:
        length = data[offset]
        if length == 0:
            return offset + 1
        if length & 0xC0 == 0xC0:  # compression pointer terminates the name
            return offset + 2
        offset += 1 + length


def _reply_has_mx(reply: bytes, qid: int, domain: str) -> bool:
    """Parse a DNS reply; True iff the answer section holds an MX record."""
    if len(reply) < 12:
        raise MXLookupError(f"truncated DNS reply for {domain!r}")
    rid, flags, qdcount, ancount, _, _ = struct.unpack(">HHHHHH", reply[:12])
    if rid != qid:
        raise MXLookupError(f"DNS transaction-id mismatch for {domain!r}")
    rcode = flags & 0x000F
    if rcode == 3:  # NXDOMAIN: the domain does not exist at all
        return False
    if rcode != 0:
        raise MXLookupError(f"DNS rcode {rcode} for {domain!r}")
    try:
        offset = 12
        for _ in range(qdcount):
            offset = _skip_name(reply, offset) + 4
        for _ in range(ancount):
            offset = _skip_name(reply, offset)
            rtype, _, _, rdlength = struct.unpack_from(">HHIH", reply, offset)
            if rtype == _QTYPE_MX:
                return True
            offset += 10 + rdlength
    except (IndexError, struct.error) as exc:
        raise MXLookupError(f"malformed DNS reply for {domain!r}") from exc
    return False
