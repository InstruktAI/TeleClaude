"""Email notification sender via Brevo SMTP.

Provides async email delivery with HTML and plain text support.
"""

from __future__ import annotations

import asyncio
import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from instrukt_ai_logging import get_logger

logger = get_logger(__name__)


async def send_email(
    to: str,
    subject: str,
    html_body: str,
    text_body: str | None = None,
    *,
    smtp_host: str = "smtp-relay.brevo.com",
    smtp_port: int = 587,
) -> None:
    """Send email via Brevo SMTP.

    Args:
        to: Recipient email address
        subject: Email subject line
        html_body: HTML email body
        text_body: Plain text alternative (optional, extracted from html if not provided)
        smtp_host: SMTP server hostname
        smtp_port: SMTP server port

    Raises:
        ValueError: If required credentials are missing
        RuntimeError: If SMTP delivery fails
    """
    # Read credentials from environment
    smtp_user = os.getenv("BREVO_SMTP_USER")
    smtp_pass = os.getenv("BREVO_SMTP_PASS")
    sender_email = os.getenv("BREVO_SENDER_EMAIL")
    sender_name = os.getenv("BREVO_SENDER_NAME", "TeleClaude")

    if not smtp_user or not smtp_pass or not sender_email:
        raise ValueError(
            "Missing required Brevo SMTP credentials: BREVO_SMTP_USER, BREVO_SMTP_PASS, BREVO_SENDER_EMAIL must be set"
        )

    # Build MIME message
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{sender_name} <{sender_email}>"
    msg["To"] = to

    # Add plain text alternative
    if text_body:
        msg.attach(MIMEText(text_body, "plain"))
    else:
        # Basic HTML stripping for text fallback
        text_fallback = re.sub(r"<[^>]+>", "", html_body)
        msg.attach(MIMEText(text_fallback, "plain"))

    # Add HTML body
    msg.attach(MIMEText(html_body, "html"))

    # Send via SMTP in thread (smtplib is blocking)
    def _send_smtp() -> None:
        try:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.sendmail(sender_email, to, msg.as_string())
            logger.info("Email sent to %s: %s", to, subject)
        except Exception as e:
            logger.error("SMTP delivery failed to %s: %s", to, e)
            raise RuntimeError(f"SMTP delivery failed: {e}") from e

    await asyncio.to_thread(_send_smtp)
