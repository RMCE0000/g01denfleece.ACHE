"""Send the sponsorship payment link through the same mailbox Chatwoot uses."""

import os
import smtplib
from contextvars import ContextVar
from email.message import EmailMessage

from app.errors import G01Error

mail_override: ContextVar = ContextVar("g01_mail_override", default=None)


def smtp_settings() -> dict | None:
    host = os.environ.get("SMTP_ADDRESS", "").strip()
    if not host:
        return None
    starttls = os.environ.get("SMTP_ENABLE_STARTTLS_AUTO", "false").strip().casefold() in {"1", "true", "yes"}
    return {
        "host": host,
        "port": int(os.environ.get("SMTP_PORT") or "587"),
        "starttls": starttls,
        "username": os.environ.get("SMTP_USERNAME", "").strip(),
        "password": os.environ.get("SMTP_PASSWORD", ""),
        "sender": os.environ.get("MAILER_SENDER_EMAIL", "").strip() or "Jane <jane@g01denfleece.com>",
    }


def send_sponsor_payment_link(*, to: str, company: str, url: str) -> None:
    """Mail the Stripe payment link. Tests replace this with mail_override."""
    override = mail_override.get()
    if override is not None:
        override(to, company, url)
        return
    settings = smtp_settings()
    if settings is None:
        raise G01Error("payment email is not configured", 503)
    message = EmailMessage()
    message["To"] = to
    message["From"] = settings["sender"]
    message["Subject"] = f"g01 sponsorship payment for {company}"
    message.set_content(
        f"The secure payment link for {company} is:\n\n{url}\n\n"
        "The listing turns on after Stripe marks this payment paid.\n"
    )
    try:
        with smtplib.SMTP(settings["host"], settings["port"], timeout=20) as smtp:
            if settings["starttls"]:
                smtp.starttls()
            if settings["username"]:
                smtp.login(settings["username"], settings["password"])
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise G01Error("payment email could not be sent", 503) from exc
