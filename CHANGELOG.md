# Changelog

## Unreleased

- No cold repeats: a recipient's domain (or address, `recontact_scope="address"`) sent to in the last `recontact_days` days (default 30)
  is held as `already_contacted`; so is a second draft to the same company in one batch. Running the same drafts twice no longer sends twice.
  `recontact_days=0` turns it off.

## 0.1.0 - 2026-07-31

Initial release, extracted and generalized from a private production multi-agent automation system.

- Full offline self-test (`python -m outreachkit --self-test`)
- MIT licensed

See the Roadmap section of the README for planned improvements - this is a maintained tool, not a snapshot.
