"""Fact-check gate: a pluggable content linter that hard-blocks forbidden claims."""
from __future__ import annotations

import re
from typing import Iterable

#: Default forbidden-claim patterns as ``(regex, reason)`` pairs. The shipped
#: defaults target fabricated company-age claims — the exact class of copy
#: that, once sent, cannot be unsent.
DEFAULT_FORBIDDEN: tuple[tuple[str, str], ...] = (
    (
        r"\btrading\s+since\s+\d{4}\b",
        "fabricated company-age claim ('trading since YYYY')",
    ),
    (
        r"\bestablished\s+(?:in\s+)?\d{4}\b",
        "fabricated company-age claim ('established YYYY')",
    ),
    (
        r"\b\d+\+?\s*years?\s+of\s+(?:experience|trading)\b",
        "fabricated tenure claim ('N years of experience')",
    ),
)


class FactChecker:
    """Content linter for outbound drafts.

    A single match against any forbidden pattern demotes the draft to
    ``needs_review`` — the gate never rewrites copy, it only refuses to
    let unverifiable claims reach the send path.
    """

    def __init__(self, patterns: Iterable[tuple[str, str]] = DEFAULT_FORBIDDEN) -> None:
        self._rules = [(re.compile(rx, re.IGNORECASE), reason) for rx, reason in patterns]

    def violations(self, text: str) -> list[str]:
        """Return the reason for every forbidden claim found in ``text``."""
        return [reason for rx, reason in self._rules if rx.search(text)]
