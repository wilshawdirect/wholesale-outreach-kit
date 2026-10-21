# wholesale-outreach-kit

[![CI](https://github.com/Wilshawdirect/wholesale-outreach-kit/actions/workflows/ci.yml/badge.svg)](https://github.com/Wilshawdirect/wholesale-outreach-kit/actions/workflows/ci.yml)

A Python library and CLI for B2B supplier outreach — opening wholesale/trade
accounts at scale — where every draft must pass a four-gate safety stack before
it is allowed anywhere near a mail server. It encodes, as working code, the
hard lessons of running real outreach: dead domains burn sender reputation,
fabricated claims cannot be unsent, and unthrottled sending gets you
blocklisted.

## Why this exists

This kit was extracted from a production multi-agent automation system that
ran real supplier outreach for an e-commerce business. Each gate is a lesson
that was learned the expensive way:

| Gate | The lesson behind it |
|---|---|
| **1. MX validation** | A batch once went to domains that no longer had mail servers. Every bounce dents sender reputation. Now: resolve the recipient domain's MX records *before* a send is ever attempted. No MX → the domain goes to a quarantine list and never touches SMTP. |
| **2. Fact-check linter** | An early template contained a fabricated company-age claim ("trading since &lt;year&gt;"). Nine emails went out before anyone noticed — and an email cannot be unsent. Now: a pluggable content linter hard-blocks configurable forbidden claims (fabricated company age and tenure are the shipped defaults) and demotes violators to `needs_review` instead of sending. |
| **3. Reputation cap** | New sending domains that blast 50 emails on day one get flagged. Now: a max-sends-per-run cap, a per-day cap fed by the send log, spacing between sends, and a configurable warm-up ramp that grows the daily cap week by week. |
| **4. Suppression memory** | Re-contacting a domain that hard-bounced is the fastest way to a blocklist. Now: bounced and dead-MX domains are remembered in SQLite and never contacted again — across runs, across restarts. |

Gate order is deliberate: durable memory first (free and final), then the
network check, then content, then rate. A draft only sends if all four pass.

## Quickstart

Requires Python 3.11+. No external dependencies.

```
git clone https://github.com/Wilshawdirect/wholesale-outreach-kit.git
cd wholesale-outreach-kit

# Prove it works, fully offline (injected MX resolver, in-memory DB):
python -m outreachkit --self-test

# Dry-run the bundled sample batch and watch each gate fire:
python -m outreachkit process --dry-run --skip-mx

# Same, but with live MX lookups against real DNS:
python -m outreachkit process --dry-run --drafts outreachkit/data/sample_drafts.json
```

A drafts file is a JSON array of `{"to", "subject", "body"}` objects — see
`outreachkit/data/sample_drafts.json`.

Library use:

```python
from outreachkit import (
    Draft, MockSender, OutreachConfig, SuppressionStore, SystemResolver,
    process_batch,
)

drafts = [Draft("purchasing@acme-wholesale.example.com",
                "Trade account enquiry", "Hello ...")]
results = process_batch(
    drafts,
    config=OutreachConfig(max_per_run=5, max_per_day=20, spacing_seconds=60),
    store=SuppressionStore("outreachkit.db"),
    resolver=SystemResolver(),
    sender=MockSender(),
    dry_run=True,
)
for r in results:
    print(r.status, r.gate, r.detail)
```

## Architecture

```
outreachkit/
  models.py     Draft, DraftResult, DraftStatus, OutreachConfig (warm-up ramp)
  mx.py         MX gate: MXResolver protocol, StaticResolver (tests/offline),
                SystemResolver (stdlib-only UDP DNS client, QTYPE=MX)
  gates.py      FactChecker: regex content linter, forbidden-claim defaults
  store.py      SuppressionStore: SQLite never-contact list + send log
  templates.py  string.Template engine with required-field validation
  senders.py    Sender protocol, MockSender, deliberately unconfigured SMTPSender
  pipeline.py   process_batch(): the ordered gate stack
  selftest.py   offline fixture suite (python -m outreachkit --self-test)
  __main__.py   CLI
```

Two seams are injectable on purpose: the **MX resolver** (so tests and
offline runs never touch the network, and so you can swap in a caching or
DoH resolver) and the **sender** (so the pipeline is testable and
transport-agnostic).

One design point worth naming: an MX *lookup failure* (timeout, malformed
reply) is treated as "defer, do not quarantine" — a flaky nameserver must
never permanently blocklist a live supplier. Only a clean "no MX / NXDOMAIN"
answer quarantines.

## No cold repeats

Running the same drafts file twice used to send every email twice. Before the MX lookup the pipeline now checks the send log:
a recipient's **domain** (the default; use `recontact_scope="address"` for just the address) that was sent to in the last
`recontact_days` days (default 30) is held as `already_contacted`, and so is a second draft to the same company inside one batch.
It uses the send log, so it works across runs and restarts. `OutreachConfig(recontact_days=0)` switches it off, for example when
you are sending a deliberate follow-up.

## Why there is no ready-to-fire sender

`SMTPSender` contains a complete STARTTLS implementation, but every
connection setting is required and none has a default: until you explicitly
pass host, port, credentials and a from-address, it raises
`SenderNotConfiguredError`. The CLI only operates in `--dry-run`. This is
deliberate: a cloned repo with a filled-in `.env.example` should not be one
copy-paste away from emailing real companies. Wiring a live transport is a
decision the operator makes in their own code, with their own secrets.

## Limitations

- The MX check is a boolean over a single UDP DNS query: no TCP fallback for
  truncated replies, no IDN/punycode support, no MX-host connectivity probe.
  A domain can have an MX record and still reject your mail.
- The fact-check gate is regex-based. It catches known claim patterns, not
  novel phrasings; treat it as a tripwire, not a truth oracle.
- Per-day counting resets at UTC midnight and lives in a single-writer
  SQLite file — fine for one sender process, not for a distributed fleet.
- No unsubscribe handling, no consent tracking. Compliance with the
  anti-spam law in your jurisdiction (CAN-SPAM, PECR/GDPR, CASL, ...) is
  your responsibility; this kit only makes the mechanical failure modes
  harder to hit.

## License

MIT — see [LICENSE](LICENSE). Copyright 2026 ADZ.

## Roadmap

This is a maintained tool, not a snapshot - improvements land as the system it came from evolves:

- Warm-up scheduler daemon that advances the ramp automatically
- Bounce/complaint webhook ingestion interface feeding the suppression store
- DKIM/SPF/DMARC preflight checks on the sending domain
- Reply-tracking hooks so outcomes feed back into templates

See [CHANGELOG.md](CHANGELOG.md) for release history.
