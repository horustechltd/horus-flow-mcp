# -*- coding: utf-8 -*-
"""
Horus Flow API — outgoing mail (Zoho SMTP over SSL).
Sends only when SMTP_HOST, SMTP_USER and SMTP_PASSWORD are set and this is not a test instance.
"""
import asyncio
import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from app.config import TEST_INSTANCE

logger = logging.getLogger("API.Mailer")

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
MAIL_FROM = os.getenv("MAIL_FROM", "Horus Flow <noreply@horustek.pro>")


def configured() -> bool:
    return bool(SMTP_HOST and SMTP_USER and SMTP_PASSWORD) and not TEST_INSTANCE


def _send(to: str, subject: str, text: str) -> None:
    msg = EmailMessage()
    msg["From"] = MAIL_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = make_msgid(domain=MAIL_FROM.rsplit("@", 1)[-1].strip(">"))
    msg.set_content(text)
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=20, context=ssl.create_default_context()) as s:
        s.login(SMTP_USER, SMTP_PASSWORD)
        s.send_message(msg)


async def send_mail(to: str, subject: str, text: str) -> bool:
    """True when the message was handed to the mail server."""
    if not configured():
        return False
    try:
        await asyncio.to_thread(_send, to, subject, text)
        return True
    except (smtplib.SMTPException, OSError) as e:
        logger.error(f"mail to {to} failed: {e!r}")
        return False
