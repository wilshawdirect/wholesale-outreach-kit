"""Offline self-test: a fixture batch that exercises every gate. No network.

Run with ``python -m outreachkit --self-test``. The MX gate uses an injected
static resolver and the store uses an in-memory SQLite database, so the whole
suite runs offline in well under a second.
"""
from __future__ import annotations

import datetime as dt

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

    store.close()
    print()
    total = passed + len(failures)
    if failures:
        print(f"SELF-TEST FAILED: {len(failures)}/{total} checks failed: {failures}")
        return 1
    print(f"SELF-TEST PASSED: {passed}/{total} checks green")
    return 0
