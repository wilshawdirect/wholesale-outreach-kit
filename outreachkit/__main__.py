"""Command-line interface: ``python -m outreachkit``."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .models import OutreachConfig, drafts_from_json, load_sample_drafts
from .mx import StaticResolver, SystemResolver
from .pipeline import process_batch
from .senders import MockSender
from .store import SuppressionStore


def _cmd_process(args: argparse.Namespace) -> int:
    """Run a drafts file through the gate stack and print a per-draft report."""
    if not args.dry_run:
        print(
            "This kit ships no configured sender (by design). Re-run with "
            "--dry-run, or wire your own Sender via the library API "
            "(see README, 'Why there is no ready-to-fire sender').",
            file=sys.stderr,
        )
        return 2
    if args.drafts:
        drafts = drafts_from_json(Path(args.drafts).read_text("utf-8"))
    else:
        drafts = load_sample_drafts()
        print("(no --drafts given; using the bundled sample batch)\n")

    config = OutreachConfig(
        max_per_run=args.max_per_run,
        max_per_day=args.max_per_day,
        spacing_seconds=args.spacing,
    )
    resolver = StaticResolver() if args.skip_mx else SystemResolver()
    store = SuppressionStore(args.db)
    try:
        results = process_batch(
            drafts, config=config, store=store, resolver=resolver,
            sender=MockSender(), dry_run=True)
    finally:
        store.close()

    for r in results:
        gate = f"[{r.gate}]" if r.gate else "[-]"
        print(f"{r.status.value:<13} {gate:<17} {r.draft.to_email:<42} {r.detail}")
    would = sum(1 for r in results if r.status.value == "would_send")
    print(f"\n{len(results)} drafts: {would} would send, {len(results) - would} held by gates")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch to the requested command."""
    parser = argparse.ArgumentParser(
        prog="outreachkit",
        description="B2B supplier outreach with pre-send safety gates.")
    parser.add_argument(
        "--self-test", action="store_true",
        help="run the offline test suite and exit")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("process", help="run a batch of drafts through the gate stack")
    p.add_argument("--drafts", help="path to a JSON drafts file (default: bundled sample batch)")
    p.add_argument("--dry-run", action="store_true",
                   help="report what WOULD send and which gate blocked what (required)")
    p.add_argument("--self-test", action="store_true",
                   help="run the offline test suite and exit")
    p.add_argument("--db", default="outreachkit.db",
                   help="SQLite path for suppression memory + send log")
    p.add_argument("--skip-mx", action="store_true",
                   help="skip the live MX lookup (offline demo; treats all domains as live)")
    p.add_argument("--max-per-run", type=int, default=5, help="send cap per run")
    p.add_argument("--max-per-day", type=int, default=20, help="send cap per UTC day")
    p.add_argument("--spacing", type=float, default=60.0,
                   help="seconds between real sends (ignored in dry-run)")

    args = parser.parse_args(argv)
    if getattr(args, "self_test", False):
        from .selftest import run_self_test

        return run_self_test()
    if args.command == "process":
        return _cmd_process(args)
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
