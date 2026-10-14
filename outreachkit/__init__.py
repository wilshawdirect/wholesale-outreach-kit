"""outreachkit — B2B supplier outreach with pre-send safety gates.

A library and CLI for opening wholesale/trade accounts at scale without
burning your sender reputation or your credibility. Every draft passes a
four-gate stack (suppression memory, MX validation, fact-check linting,
reputation caps) before anything is allowed near a mail server.
"""
from __future__ import annotations

from .gates import DEFAULT_FORBIDDEN, FactChecker
from .models import Draft, DraftResult, DraftStatus, OutreachConfig
from .mx import MXLookupError, MXResolver, StaticResolver, SystemResolver
from .pipeline import process_batch
from .senders import MockSender, Sender, SenderNotConfiguredError, SMTPSender
from .store import SuppressionStore
from .templates import SAMPLE_TEMPLATE, TemplateError, render_template

__version__ = "1.0.0"

__all__ = [
    "DEFAULT_FORBIDDEN",
    "Draft",
    "DraftResult",
    "DraftStatus",
    "FactChecker",
    "MXLookupError",
    "MXResolver",
    "MockSender",
    "OutreachConfig",
    "SAMPLE_TEMPLATE",
    "SMTPSender",
    "Sender",
    "SenderNotConfiguredError",
    "StaticResolver",
    "SuppressionStore",
    "SystemResolver",
    "TemplateError",
    "process_batch",
    "render_template",
]
