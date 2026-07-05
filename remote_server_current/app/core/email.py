"""
app/core/email.py
===================
Fire-and-forget SMTP email helper.
Call ``send_email(to, subject, html)`` to dispatch asynchronously.
If SMTP is not configured the call is a no-op (logged warning).
"""
from __future__ import annotations

import asyncio
import logging
import smtplib
from email.mime.text import MIMEText

from app.core.config import settings

logger = logging.getLogger("app.core.email")


async def send_email(to: str, subject: str, html: str) -> None:
    """
    Send an HTML email via SMTP in a background thread.

    Fire-and-forget: callers should **not** await this function in
    request handlers (use ``asyncio.create_task(send_email(...))`` instead).

    When SMTP_HOST is empty (unconfigured) the email is skipped and a
    warning is logged.
    """
    if not settings.SMTP_HOST:
        logger.warning("SMTP not configured — skipping email to %s (subject=%r)", to, subject)
        return

    def _send() -> None:
        msg = MIMEText(html, "html")
        msg["Subject"] = subject
        msg["From"] = settings.SMTP_FROM
        msg["To"] = to

        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            server.starttls()
            if settings.SMTP_USER:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(msg)

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _send)
    logger.info("Email sent to %s (subject=%r)", to, subject)
