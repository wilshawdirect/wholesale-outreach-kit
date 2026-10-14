"""Minimal draft template engine: ``string.Template`` + required-field checks.

No conditional logic, no filters — and deliberately no placeholders for claims
the sender cannot substantiate. Company age, tenure, and track record are not
template variables here; if you want them in your copy, you type them yourself
and the fact-check gate will still challenge them.
"""
from __future__ import annotations

from string import Template
from typing import Mapping

SAMPLE_TEMPLATE = """\
Hello $contact_name,

I run $our_company, an online retailer, and I would like to open a trade
account with $their_company. Could you share your account application form
and current price list?

Best regards,
$sender_name
$our_company
"""


class TemplateError(ValueError):
    """Raised when a template cannot be rendered safely."""


def render_template(template: str, fields: Mapping[str, str]) -> str:
    """Render ``template`` with ``fields``; every placeholder must be filled.

    Raises :class:`TemplateError` if any placeholder is missing or any supplied
    value is blank — a half-rendered outreach email must never reach the send
    path.
    """
    blank = [k for k, v in fields.items() if not str(v).strip()]
    if blank:
        raise TemplateError(f"blank template fields: {', '.join(sorted(blank))}")
    try:
        return Template(template).substitute(fields)
    except (KeyError, ValueError) as exc:
        raise TemplateError(f"unfilled or invalid placeholder: {exc}") from exc
