"""SMTP delivery of `OutgoingMail` (S5.4), with the standard library.

Any SMTP server, chosen by configuration like faclab-invoicing's (D-3): SMTPS
when SMTP_SECURE, otherwise STARTTLS, required when SMTP_REQUIRE_TLS (false only
locally, where Mailpit has no TLS). The message is sent inside the request: a
failure answers EMAIL_DELIVERY_FAILED and rolls the request back.
"""

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

import structlog
from wireup import injectable

from src.shared.app.mail import (
    EmailDeliveryFailedError,
    EmailDisabledError,
    Mailer,
    OutgoingMail,
)

logger = structlog.get_logger(__name__)


class SmtpMailer(Mailer):
    def __init__(
        self,
        host: str,
        port: int,
        sender: str,
        *,
        secure: bool = False,
        require_tls: bool = True,
        username: str | None = None,
        password: str | None = None,
        timeout: float = 20.0,
    ):
        self.host = host
        self.port = port
        self.sender = sender
        self.secure = secure
        self.require_tls = require_tls
        self.username = username
        self.password = password
        self.timeout = timeout

    def message(self, mail: OutgoingMail) -> EmailMessage:
        message = EmailMessage()
        message["From"] = formataddr((mail.sender_name or "", self.sender))
        message["To"] = mail.to
        message["Subject"] = mail.subject
        message["Message-ID"] = make_msgid(domain=self.sender.rpartition("@")[2])
        message.set_content(mail.text)
        for attachment in mail.attachments:
            maintype, _, subtype = attachment.content_type.partition("/")
            message.add_attachment(
                attachment.content,
                maintype=maintype,
                subtype=subtype,
                filename=attachment.filename,
            )
        return message

    def send(self, mail: OutgoingMail) -> None:
        message = self.message(mail)
        try:
            with self._connect() as smtp:
                if self.username:
                    smtp.login(self.username, self.password or "")
                smtp.send_message(message)
        except (smtplib.SMTPException, OSError) as exc:
            # The reason, without the address: logs don't carry emails
            logger.warning("email_delivery_failed", error=type(exc).__name__)
            raise EmailDeliveryFailedError(type(exc).__name__) from exc
        logger.info("email_sent", attachments=len(mail.attachments))

    def _connect(self) -> smtplib.SMTP:
        context = ssl.create_default_context()
        if self.secure:
            return smtplib.SMTP_SSL(
                self.host, self.port, timeout=self.timeout, context=context
            )
        smtp = smtplib.SMTP(self.host, self.port, timeout=self.timeout)
        smtp.ehlo()
        if smtp.has_extn("starttls"):
            smtp.starttls(context=context)
            smtp.ehlo()
        elif self.require_tls:
            smtp.quit()
            raise smtplib.SMTPNotSupportedError("The SMTP server offers no STARTTLS")
        return smtp


class DisabledMailer(Mailer):
    """EMAIL_ENABLED=false: every send answers EMAIL_DISABLED"""

    def send(self, mail: OutgoingMail) -> None:
        raise EmailDisabledError()


@injectable(lifetime="singleton")
def mailer() -> Mailer:
    from config import config

    if not config.EMAIL_ENABLED:
        return DisabledMailer()
    return SmtpMailer(
        config.SMTP_HOST,
        config.SMTP_PORT,
        config.EMAIL_FROM,
        secure=config.SMTP_SECURE,
        require_tls=config.SMTP_REQUIRE_TLS,
        username=config.SMTP_USER or None,
        password=config.SMTP_PASSWORD or None,
        timeout=config.SMTP_TIMEOUT_SECONDS,
    )
