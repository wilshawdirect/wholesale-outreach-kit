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
    sent_at  TEXT NOT NULL,
    bounced  INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class SuppressionStore:
    """SQLite-backed suppression list + send log. Pass ``":memory:"`` for tests."""

    def __init__(self, path: str = "outreachkit.db") -> None:
        self._conn = sqlite3.connect(path)
        self._conn.executescript(_SCHEMA)
        # a database created before bounce tracking gains the column in place
        if "bounced" not in {r[1] for r in self._conn.execute("PRAGMA table_info(send_log)")}:
            self._conn.execute("ALTER TABLE send_log ADD COLUMN bounced INTEGER NOT NULL DEFAULT 0")
            self._conn.commit()

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
        """Remember a hard bounce; the domain is never contacted again, and its logged sends count as bounced."""
        self.suppress(domain, "hard_bounce")
        self._conn.execute("UPDATE send_log SET bounced = 1 WHERE lower(domain) = ?", (domain.lower(),))
        self._conn.commit()

    def bounce_stats(self, window: int = 100) -> tuple[int, int]:
        """``(sent, bounced)`` over the newest ``window`` sends logged since the last :meth:`resume`."""
        rows = self._conn.execute(
            "SELECT bounced FROM send_log WHERE id > ? ORDER BY id DESC LIMIT ?",
            (self._baseline_id(), max(1, window)),
        ).fetchall()
        return len(rows), sum(int(r[0]) for r in rows)

    def paused(self) -> str | None:
        """Why sending is paused, or None. A pause is latched in the database until :meth:`resume`."""
        row = self._conn.execute("SELECT value FROM state WHERE key = 'paused'").fetchone()
        return row[0] if row else None

    def pause(self, reason: str) -> None:
        """Latch a pause (idempotent; the first reason stays)."""
        self._conn.execute("INSERT OR IGNORE INTO state (key, value) VALUES ('paused', ?)", (reason,))
        self._conn.commit()

    def resume(self) -> bool:
        """Clear a pause. Counting restarts from the newest send, so the bounces that caused the pause cannot
        re-trigger it at once, while a fresh spike still can. Returns True if a pause was cleared."""
        was_paused = self.paused() is not None
        newest = self._conn.execute("SELECT COALESCE(MAX(id), 0) FROM send_log").fetchone()[0]
        self._conn.execute("INSERT OR REPLACE INTO state (key, value) VALUES ('baseline_id', ?)", (str(newest),))
        self._conn.execute("DELETE FROM state WHERE key = 'paused'")
        self._conn.commit()
        return was_paused

    def _baseline_id(self) -> int:
        row = self._conn.execute("SELECT value FROM state WHERE key = 'baseline_id'").fetchone()
        return int(row[0]) if row else 0

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
