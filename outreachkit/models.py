"""Core data types shared across the outreach kit."""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from enum import StrEnum


class DraftStatus(StrEnum):
    """Terminal state assigned to a draft by the gate stack."""

    SENT = "sent"
    WOULD_SEND = "would_send"
    SUPPRESSED = "suppressed"
    MX_DEAD = "mx_dead"
    MX_ERROR = "mx_error"
    NEEDS_REVIEW = "needs_review"
    CAPPED = "capped"
    ALREADY_CONTACTED = "already_contacted"
    INVALID = "invalid"


@dataclass(frozen=True)
class Draft:
    """A single outbound email draft."""

    to_email: str
    subject: str
    body: str

    @property
    def domain(self) -> str:
        """Recipient domain, lower-cased, or ``''`` if the address is malformed."""
        local, sep, dom = self.to_email.partition("@")
        if not sep or not local.strip() or not dom.strip():
            return ""
        return dom.strip().lower()


@dataclass(frozen=True)
class DraftResult:
    """Outcome of running one draft through the gate stack."""

    draft: Draft
    status: DraftStatus
    gate: str | None = None
    detail: str = ""


@dataclass
class OutreachConfig:
    """Tunable limits for a campaign.

    Warm-up ramp: when ``warmup_start`` is set, the effective daily cap starts
    at ``warmup_base`` and grows by ``warmup_increment`` per full week elapsed,
    never exceeding ``max_per_day``.

    No cold repeats: a recipient (``recontact_scope="address"``) or any address at
    its domain (``"domain"``, the default) that was sent to in the last
    ``recontact_days`` days is not cold-emailed again. ``0`` switches the gate off.
    """

    max_per_run: int = 5
    max_per_day: int = 20
    spacing_seconds: float = 60.0
    warmup_start: dt.date | None = None
    warmup_base: int = 5
    warmup_increment: int = 5
    recontact_days: int = 30
    recontact_scope: str = "domain"

    def __post_init__(self) -> None:
        if self.recontact_scope not in ("domain", "address"):
            raise ValueError(f"recontact_scope must be 'domain' or 'address', got {self.recontact_scope!r}")

    def effective_daily_cap(self, today: dt.date | None = None) -> int:
        """Return the daily send cap after applying the warm-up ramp."""
        if self.warmup_start is None:
            return self.max_per_day
        today = today or dt.date.today()
        weeks = max(0, (today - self.warmup_start).days // 7)
        return min(self.max_per_day, self.warmup_base + self.warmup_increment * weeks)


def drafts_from_json(text: str) -> list[Draft]:
    """Parse a JSON array of ``{"to", "subject", "body"}`` objects into drafts."""
    return [Draft(d["to"], d["subject"], d["body"]) for d in json.loads(text)]


def load_sample_drafts() -> list[Draft]:
    """Load the fixture batch bundled with the package (used by the self-test)."""
    from importlib import resources

    text = resources.files(__package__).joinpath("data/sample_drafts.json").read_text("utf-8")
    return drafts_from_json(text)
