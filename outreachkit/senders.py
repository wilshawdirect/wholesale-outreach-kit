"""Send transports. The kit ships no ready-to-fire sender on purpose.

``MockSender`` records what would have gone out. ``SMTPSender`` contains a
complete STARTTLS implementation but refuses to run until every connection
detail is supplied explicitly — a cloned repo must not be able to email real
companies by accident.
"""
from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Protocol

from .models import Draft


class SenderNotConfiguredError(RuntimeError):
    """Raised when :class:`SMTPSender` is used before being fully configured."""


class Sender(Protocol):
    """Anything that can deliver a draft."""

    def send(self, draft: Draft) -> None:
        """Deliver one draft, raising on failure."""
        ...


class MockSender:
    """Records drafts instead of delivering them. Used by tests and demos."""

    def __init__(self) -> None:
        self.sent: list[Draft] = []

    def send(self, draft: Draft) -> None:
        """Append the draft to :attr:`sent`."""
        self.sent.append(draft)


class SMTPSender:
    """SMTP+STARTTLS transport. All five settings are required; none default.

    Pass ``host``, ``port``, ``username``, ``password`` and ``from_addr``
    explicitly (read them from your own secret store). Until every one is
    supplied, each call raises :class:`SenderNotConfiguredError`.
    """

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        username: str | None = None,
        password: str | None = None,
        from_addr: str | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.from_addr = from_addr

    def send(self, draft: Draft) -> None:
        """Deliver via SMTP+STARTTLS; refuses to run half-configured."""
        if not all([self.host, self.port, self.username, self.password, self.from_addr]):
            raise SenderNotConfiguredError(
                "SMTPSender ships unconfigured by design; supply host, port, "
                "username, password and from_addr before sending."
            )
        msg = EmailMessage()
        msg["From"] = self.from_addr
        msg["To"] = draft.to_email
        msg["Subject"] = draft.subject
        msg.set_content(draft.body)
        with smtplib.SMTP(self.host, self.port, timeout=30) as smtp:
            smtp.starttls()
            smtp.login(self.username, self.password)
            smtp.send_message(msg)
