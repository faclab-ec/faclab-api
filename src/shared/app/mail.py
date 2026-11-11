"""Outgoing email (S5.4): a port like `EventPublisher`, so the modules that send
a document (quotes) don't know the SMTP server. `src/shared/infra/mail.py`
implements it."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from src.shared.domain.exceptions import ApplicationError


@dataclass(frozen=True)
class MailAttachment:
    filename: str
    content: bytes
    content_type: str = "application/pdf"


@dataclass(frozen=True)
class OutgoingMail:
    """A message to one address. `sender_name` is the name it comes from (the
    company's); the address is the platform's (EMAIL_FROM)"""

    to: str
    subject: str
    text: str
    sender_name: str | None = None
    attachments: tuple[MailAttachment, ...] = field(default_factory=tuple)


class Mailer(ABC):
    @abstractmethod
    def send(self, mail: OutgoingMail) -> None:
        """Delivers the message to the SMTP server or raises
        `EmailDeliveryFailedError`"""


class EmailDisabledError(ApplicationError):
    error_code = "EMAIL_DISABLED"

    def __init__(self):
        super().__init__("Sending email is turned off (EMAIL_ENABLED=false)")


class EmailDeliveryFailedError(ApplicationError):
    """The SMTP server refused the message or couldn't be reached (502)"""

    error_code = "EMAIL_DELIVERY_FAILED"

    def __init__(self, reason: str):
        super().__init__("The email could not be sent", detail=reason)
