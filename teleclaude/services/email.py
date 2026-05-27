"""Email delivery helpers via an SMTP relay (e.g. Brevo)."""

from __future__ import annotations

import asyncio
import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import parseaddr

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.config.validation import is_section_available

logger = get_logger(__name__)

_DEFAULT_SMTP_RELAY = "smtp-relay.brevo.com:587"


def _parse_relay(relay: str) -> tuple[str, int]:
    """Split a ``host:port`` relay string; default the port to 587."""
    host, _, port_str = relay.partition(":")
    return host, int(port_str) if port_str.isdigit() else 587


async def send_email(
    to: str,
    subject: str,
    html_body: str,
    text_body: str | None = None,
) -> None:
    """Send email via the configured SMTP relay.

    Credentials and sender identity come from the environment:
    ``SMTP_USERNAME``, ``SMTP_KEY``, ``SMTP_RELAY`` (``host:port``),
    ``EMAIL_FROM`` (``Name <addr>``), and optional ``EMAIL_REPLYTO``.

    Raises:
        RuntimeError: If email is disabled/unconfigured, or SMTP delivery fails
    """
    # Single availability gate, shared with adapters: enabled flag + required creds.
    if not is_section_available("email", getattr(config, "email", None)):
        raise RuntimeError(
            "Email is disabled or not configured (set email.enabled and SMTP_USERNAME / SMTP_KEY / EMAIL_FROM)"
        )

    # Presence guaranteed by the availability gate above; defaults keep types str.
    smtp_user = os.getenv("SMTP_USERNAME", "")
    smtp_pass = os.getenv("SMTP_KEY", "")
    email_from = os.getenv("EMAIL_FROM", "")
    reply_to = os.getenv("EMAIL_REPLYTO")
    smtp_host, smtp_port = _parse_relay(os.getenv("SMTP_RELAY", _DEFAULT_SMTP_RELAY))

    sender_email = parseaddr(email_from)[1] or email_from

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = email_from
    msg["To"] = to
    if reply_to:
        msg["Reply-To"] = reply_to

    if text_body:
        msg.attach(MIMEText(text_body, "plain"))
    else:
        text_fallback = re.sub(r"<[^>]+>", "", html_body)
        msg.attach(MIMEText(text_fallback, "plain"))

    msg.attach(MIMEText(html_body, "html"))

    def _send_smtp() -> None:
        try:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.sendmail(sender_email, to, msg.as_string())
            logger.info("Email sent")
        except Exception as e:
            logger.error("SMTP delivery failed: %s", e)
            raise RuntimeError(f"SMTP delivery failed: {e}") from e

    await asyncio.to_thread(_send_smtp)
