"""Suppression memory and send log, backed by SQLite.

The store is the kit's durable memory: which domains must never be contacted
again (hard bounces, dead MX), and what was actually sent when (which feeds
the per-day reputation cap).
"""
from __future__ import annotations

import datetime as dt
import sqlite3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS suppression (
    domain     TEXT PRIMARY KEY,
    reason     TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS send_log (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    to_email TEXT NOT NULL,
    domain   TEXT NOT NULL,
    sent_at  TEXT NOT NULL
);
"""


class SuppressionStore:
    """SQLite-backed suppression list + send log. Pass ``":memory:"`` for tests."""

    def __init__(self, path: str = "outreachkit.db") -> None:
        self._conn = sqlite3.connect(path)
        self._conn.executescript(_SCHEMA)

    def suppression_reason(self, domain: str) -> str | None:
        """Return why ``domain`` is suppressed, or None if it is contactable."""
        row = self._conn.execute(
            "SELECT reason FROM suppression WHERE domain = ?", (domain.lower(),)
        ).fetchone()
        return row[0] if row else None

    def suppress(self, domain: str, reason: str) -> None:
        """Add ``domain`` to the never-contact list (idempotent; first reason wins)."""
        self._conn.execute(
            "INSERT OR IGNORE INTO suppression (domain, reason, created_at) VALUES (?, ?, ?)",
            (domain.lower(), reason, _utcnow()),
        )
        self._conn.commit()

    def record_bounce(self, domain: str) -> None:
        """Remember a hard bounce; the domain is never contacted again."""
        self.suppress(domain, "hard_bounce")

    def record_send(self, to_email: str, domain: str) -> None:
        """Log a completed send (feeds the per-day reputation cap)."""
        self._conn.execute(
            "INSERT INTO send_log (to_email, domain, sent_at) VALUES (?, ?, ?)",
            (to_email, domain.lower(), _utcnow()),
        )
        self._conn.commit()

    def recently_contacted(self, to_email: str, domain: str, days: int, scope: str = "domain") -> str | None:
        """UTC time of the newest send within ``days`` days to this address (``scope="address"``) or to any
        address at ``domain`` (``scope="domain"``); None if there is none. ``days <= 0`` always answers None."""
        if days <= 0:
            return None
        cutoff = (dt.datetime.now(dt.UTC) - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
        column, value = ("to_email", to_email.lower()) if scope == "address" else ("domain", domain.lower())
        row = self._conn.execute(
            f"SELECT sent_at FROM send_log WHERE lower({column}) = ? AND sent_at >= ? ORDER BY sent_at DESC LIMIT 1",
            (value, cutoff),
        ).fetchone()
        return row[0] if row else None

    def sends_today(self) -> int:
        """Return the number of sends logged since UTC midnight."""
        midnight = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT00:00:00")
        row = self._conn.execute(
            "SELECT COUNT(*) FROM send_log WHERE sent_at >= ?", (midnight,)
        ).fetchone()
        return int(row[0])

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._conn.close()


def _utcnow() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%S")
