"""Offline self-test: a fixture batch that exercises every gate. No network.

Run with ``python -m outreachkit --self-test``. The MX gate uses an injected
static resolver and the store uses an in-memory SQLite database, so the whole
suite runs offline in well under a second.
"""
from __future__ import annotations

import datetime as dt
import os
import sqlite3
import tempfile

from .models import Draft, DraftStatus, OutreachConfig, load_sample_drafts
from .mx import StaticResolver
from .pipeline import process_batch
from .senders import MockSender, SenderNotConfiguredError, SMTPSender
from .store import SuppressionStore
from .templates import SAMPLE_TEMPLATE, TemplateError, render_template


def run_self_test() -> int:
    """Execute the offline test suite; return 0 on success, 1 on any failure."""
    failures: list[str] = []
    passed = 0

    def check(name: str, condition: bool, detail: str = "") -> None:
        nonlocal passed
        if condition:
            passed += 1
            print(f"  PASS  {name}")
        else:
            failures.append(name)
            print(f"  FAIL  {name}" + (f"  ({detail})" if detail else ""))

    print("outreachkit self-test (offline: injected MX resolver, in-memory DB)")
    print()

    drafts = load_sample_drafts()
    check("fixture batch loads (6 drafts)", len(drafts) == 6, f"got {len(drafts)}")

    resolver = StaticResolver({"dead-domain.example.net": False})
    store = SuppressionStore(":memory:")
    store.record_bounce("bounced-before.example.org")
    sender = MockSender()
    config = OutreachConfig(max_per_run=2, max_per_day=20, spacing_seconds=0)

    results = process_batch(
        drafts, config=config, store=store, resolver=resolver,
        sender=sender, dry_run=True)
    by = {r.draft.to_email: r for r in results}

    check("clean draft clears all gates (would_send)",
          by["purchasing@acme-wholesale.example.com"].status is DraftStatus.WOULD_SEND)
    check("dead-MX domain blocked before SMTP",
          by["sales@dead-domain.example.net"].status is DraftStatus.MX_DEAD)
    check("dead-MX domain auto-quarantined in suppression store",
          store.suppression_reason("dead-domain.example.net") == "mx_dead")
    check("previously bounced domain suppressed",
          by["info@bounced-before.example.org"].status is DraftStatus.SUPPRESSED)
    overclaim = by["trade@overclaim.example.com"]
    check("forbidden company-age claim demoted to needs_review",
          overclaim.status is DraftStatus.NEEDS_REVIEW
          and "company-age" in overclaim.detail
          and "tenure" in overclaim.detail)
    check("second clean draft still under run cap",
          by["orders@fresh-supplier.example.com"].status is DraftStatus.WOULD_SEND)
    check("run cap (2) defers the overflow draft",
          by["hello@overflow-supplier.example.com"].status is DraftStatus.CAPPED)
    check("dry run never touches the sender", not sender.sent)

    rerun = process_batch(
        [Draft("sales@dead-domain.example.net", "Retry", "Hello again.")],
        config=config, store=store, resolver=resolver, sender=sender, dry_run=True)
    check("quarantined domain stays suppressed on the next run",
          rerun[0].status is DraftStatus.SUPPRESSED)

    live = process_batch(
        [drafts[0]], config=config, store=store, resolver=resolver,
        sender=sender, dry_run=False)
    check("real send path delivers via sender and logs it",
          live[0].status is DraftStatus.SENT
          and len(sender.sent) == 1
          and store.sends_today() == 1)

    again = process_batch(
        [Draft("someone.else@acme-wholesale.example.com", "Another hello", "Hello.")],
        config=config, store=store, resolver=resolver, sender=sender, dry_run=True)
    check("no cold repeat: another address at a domain sent to today is held",
          again[0].status is DraftStatus.ALREADY_CONTACTED and again[0].gate == "recontact")
    by_address = OutreachConfig(spacing_seconds=0, recontact_scope="address")
    other_address = process_batch(
        [Draft("someone.else@acme-wholesale.example.com", "Another hello", "Hello.")],
        config=by_address, store=store, resolver=resolver, sender=sender, dry_run=True)
    check("no cold repeat: address scope lets a different address through",
          other_address[0].status is DraftStatus.WOULD_SEND)
    same_address = process_batch(
        [drafts[0]], config=by_address, store=store, resolver=resolver, sender=sender, dry_run=True)
    check("no cold repeat: the same address is held under address scope",
          same_address[0].status is DraftStatus.ALREADY_CONTACTED)
    off = process_batch(
        [drafts[0]], config=OutreachConfig(spacing_seconds=0, recontact_days=0),
        store=store, resolver=resolver, sender=sender, dry_run=True)
    check("no cold repeat: recontact_days=0 switches the gate off", off[0].status is DraftStatus.WOULD_SEND)
    pair = process_batch(
        [Draft("a@one-company.example.org", "Hello", "Hi."), Draft("b@one-company.example.org", "Hello", "Hi.")],
        config=config, store=SuppressionStore(":memory:"), resolver=resolver, sender=MockSender(), dry_run=True)
    check("no cold repeat: two drafts to one company in one batch send once",
          [r.status for r in pair] == [DraftStatus.WOULD_SEND, DraftStatus.ALREADY_CONTACTED])

    tight = OutreachConfig(max_per_run=5, max_per_day=1, spacing_seconds=0)
    capped = process_batch(
        [drafts[5]], config=tight, store=store, resolver=resolver,
        sender=sender, dry_run=True)
    check("daily cap counts sends already logged today",
          capped[0].status is DraftStatus.CAPPED)

    ramp = OutreachConfig(
        max_per_day=40, warmup_base=5, warmup_increment=5,
        warmup_start=dt.date.today() - dt.timedelta(days=21))
    check("warm-up ramp: week 3 cap = base + 3 increments",
          ramp.effective_daily_cap() == 20, f"got {ramp.effective_daily_cap()}")
    ceiling = OutreachConfig(
        max_per_day=10, warmup_base=5, warmup_increment=5,
        warmup_start=dt.date.today() - dt.timedelta(days=700))
    check("warm-up ramp never exceeds max_per_day",
          ceiling.effective_daily_cap() == 10)

    rendered = render_template(SAMPLE_TEMPLATE, {
        "contact_name": "Sam", "our_company": "Example Retail Ltd",
        "their_company": "ACME Wholesale", "sender_name": "Jordan Smith"})
    check("template renders with all fields filled", "ACME Wholesale" in rendered)
    try:
        render_template(SAMPLE_TEMPLATE, {"contact_name": "Sam"})
        check("template with missing fields raises TemplateError", False)
    except TemplateError:
        check("template with missing fields raises TemplateError", True)

    try:
        SMTPSender().send(drafts[0])
        check("unconfigured SMTP stub refuses to fire", False)
    except SenderNotConfiguredError:
        check("unconfigured SMTP stub refuses to fire", True)

    # bounce-rate pause: latched, min-volume guard, resume restarts the count
    def fresh_batch(n: int, tag: str) -> list[Draft]:
        return [Draft(f"hello@{tag}{i}.example.com", "Hi", "Hello.") for i in range(n)]

    roomy = OutreachConfig(max_per_run=5, max_per_day=500, spacing_seconds=0)
    quiet = SuppressionStore(":memory:")
    for i in range(10):
        quiet.record_send(f"x@small{i}.example.com", f"small{i}.example.com")
        if i < 5:
            quiet.record_bounce(f"small{i}.example.com")
    held = process_batch(fresh_batch(1, "q"), config=roomy, store=quiet, resolver=resolver, sender=MockSender(), dry_run=True)
    check("bounce pause: a tiny sample (5 of 10) never pauses (min-volume guard)",
          held[0].status is DraftStatus.WOULD_SEND)

    noisy = SuppressionStore(":memory:")
    for i in range(20):
        noisy.record_send(f"x@n{i}.example.com", f"n{i}.example.com")
    for i in range(2):
        noisy.record_bounce(f"n{i}.example.com")
    probe = MockSender()
    dry = process_batch(fresh_batch(2, "d"), config=roomy, store=noisy, resolver=resolver, sender=probe, dry_run=True)
    check("bounce pause: 2 of 20 bounced (10%) pauses a dry run without latching it",
          all(r.status is DraftStatus.PAUSED and r.gate == "bounce_pause" for r in dry) and noisy.paused() is None)
    live_run = process_batch(fresh_batch(2, "l"), config=roomy, store=noisy, resolver=resolver, sender=probe, dry_run=False)
    check("bounce pause: a live run is refused, nothing is sent, and the pause is latched",
          all(r.status is DraftStatus.PAUSED for r in live_run) and not probe.sent and noisy.paused() is not None)
    check("bounce pause: once latched it stays paused even if the rate would now be fine",
          noisy.bounce_stats()[0] == 20 and process_batch(
              fresh_batch(1, "m"), config=OutreachConfig(spacing_seconds=0, pause_bounce_rate=0.5), store=noisy,
              resolver=resolver, sender=probe, dry_run=True)[0].status is DraftStatus.PAUSED)
    check("bounce pause: resume clears it", noisy.resume() is True and noisy.paused() is None)
    after = process_batch(fresh_batch(1, "a"), config=roomy, store=noisy, resolver=resolver, sender=probe, dry_run=True)
    check("bounce pause: after a resume the old bounces cannot re-pause at once",
          after[0].status is DraftStatus.WOULD_SEND and noisy.bounce_stats() == (0, 0))
    for i in range(20):
        noisy.record_send(f"x@later{i}.example.com", f"later{i}.example.com")
    for i in range(3):
        noisy.record_bounce(f"later{i}.example.com")
    again = process_batch(fresh_batch(1, "z"), config=roomy, store=noisy, resolver=resolver, sender=probe, dry_run=False)
    check("bounce pause: a NEW spike after the resume pauses again",
          again[0].status is DraftStatus.PAUSED and noisy.paused() is not None)
    off_cfg = OutreachConfig(max_per_run=5, max_per_day=500, spacing_seconds=0, pause_bounce_rate=None)
    noisy.resume()
    for i in range(20):
        noisy.record_send(f"x@off{i}.example.com", f"off{i}.example.com")
        noisy.record_bounce(f"off{i}.example.com")
    disabled = process_batch(fresh_batch(1, "o"), config=off_cfg, store=noisy, resolver=resolver, sender=probe, dry_run=True)
    check("bounce pause: pause_bounce_rate=None switches the rate check off",
          disabled[0].status is DraftStatus.WOULD_SEND)

    # a database created before bounce tracking is migrated in place
    with tempfile.TemporaryDirectory() as tmp:
        legacy = os.path.join(tmp, "legacy.db")
        raw = sqlite3.connect(legacy)
        raw.executescript(
            "CREATE TABLE suppression (domain TEXT PRIMARY KEY, reason TEXT NOT NULL, created_at TEXT NOT NULL);"
            "CREATE TABLE send_log (id INTEGER PRIMARY KEY AUTOINCREMENT, to_email TEXT NOT NULL, domain TEXT NOT NULL,"
            " sent_at TEXT NOT NULL);"
            "INSERT INTO send_log (to_email, domain, sent_at) VALUES ('a@old.example.com', 'old.example.com', '2026-01-01T00:00:00');")
        raw.commit()
        raw.close()
        migrated = SuppressionStore(legacy)
        migrated.record_bounce("old.example.com")
        check("bounce pause: a pre-existing database gains the bounced column in place",
              migrated.bounce_stats() == (1, 1))
        migrated.close()

    store.close()
    print()
    total = passed + len(failures)
    if failures:
        print(f"SELF-TEST FAILED: {len(failures)}/{total} checks failed: {failures}")
        return 1
    print(f"SELF-TEST PASSED: {passed}/{total} checks green")
    return 0
