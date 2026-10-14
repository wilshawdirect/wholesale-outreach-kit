"""The gate stack: suppression -> MX -> fact-check -> reputation cap -> send."""
from __future__ import annotations

import time
from typing import Sequence

from .gates import FactChecker
from .models import Draft, DraftResult, DraftStatus, OutreachConfig
from .mx import MXLookupError, MXResolver
from .senders import Sender
from .store import SuppressionStore


def process_batch(
    drafts: Sequence[Draft],
    *,
    config: OutreachConfig,
    store: SuppressionStore,
    resolver: MXResolver,
    sender: Sender,
    fact_checker: FactChecker | None = None,
    dry_run: bool = True,
) -> list[DraftResult]:
    """Run every draft through the gate stack, in order, and return results.

    Gate order is deliberate: durable memory first (suppression — free and
    final), then the network check (MX — a dead domain gets quarantined so it
    is never looked up again), then content (fact-check), then rate
    (per-run and per-day caps). Only drafts that clear all four gates are
    sent — or, in dry-run, reported as ``would_send`` without touching the
    sender or the send log.
    """
    checker = fact_checker or FactChecker()
    results: list[DraftResult] = []
    cleared = 0  # drafts that passed every gate this run
    sends_today = store.sends_today()
    daily_cap = config.effective_daily_cap()

    for draft in drafts:
        domain = draft.domain
        if not domain:
            results.append(DraftResult(
                draft, DraftStatus.INVALID, "parse",
                f"malformed recipient address: {draft.to_email!r}"))
            continue

        reason = store.suppression_reason(domain)
        if reason:
            results.append(DraftResult(
                draft, DraftStatus.SUPPRESSED, "suppression",
                f"domain on the never-contact list ({reason})"))
            continue

        try:
            if not resolver.has_mx(domain):
                store.suppress(domain, "mx_dead")
                results.append(DraftResult(
                    draft, DraftStatus.MX_DEAD, "mx",
                    "no MX record; domain quarantined, never reaches SMTP"))
                continue
        except MXLookupError as exc:
            results.append(DraftResult(
                draft, DraftStatus.MX_ERROR, "mx",
                f"lookup failed; deferred, NOT quarantined: {exc}"))
            continue

        violations = checker.violations(f"{draft.subject}\n{draft.body}")
        if violations:
            results.append(DraftResult(
                draft, DraftStatus.NEEDS_REVIEW, "fact_check", "; ".join(violations)))
            continue

        if cleared >= config.max_per_run or sends_today + cleared >= daily_cap:
            results.append(DraftResult(
                draft, DraftStatus.CAPPED, "reputation_cap",
                f"run cap {config.max_per_run} / daily cap {daily_cap} "
                f"({sends_today} already sent today)"))
            continue

        if dry_run:
            cleared += 1
            results.append(DraftResult(
                draft, DraftStatus.WOULD_SEND, None, "all gates passed"))
            continue

        if cleared and config.spacing_seconds > 0:
            time.sleep(config.spacing_seconds)
        sender.send(draft)
        store.record_send(draft.to_email, domain)
        cleared += 1
        results.append(DraftResult(draft, DraftStatus.SENT, None, "delivered"))

    return results
