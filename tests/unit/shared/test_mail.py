"""SMTP delivery of a quote's email (S5.4)"""

import smtplib
from unittest.mock import MagicMock

import pytest

from src.shared.app.mail import (
    EmailDeliveryFailedError,
    EmailDisabledError,
    MailAttachment,
    OutgoingMail,
)
from src.shared.infra.mail import DisabledMailer, SmtpMailer

MAIL = OutgoingMail(
    to="ana@example.com",
    subject="Cotización COT-001-000001 · El Clavo",
    text="Adjuntamos la cotización",
    sender_name="El Clavo",
    attachments=(MailAttachment("cotizacion-COT-001-000001.pdf", b"%PDF-1.4"),),
)


@pytest.fixture
def smtp(mocker):
    server = MagicMock()
    server.__enter__.return_value = server
    server.has_extn.return_value = True
    mocker.patch("src.shared.infra.mail.smtplib.SMTP", return_value=server)
    return server


def test_the_message_comes_from_the_company_with_its_attachment():
    message = SmtpMailer("smtp.example.com", 587, "no-reply@faclab.ec").message(MAIL)

    assert message["From"] == "El Clavo <no-reply@faclab.ec>"
    assert message["To"] == "ana@example.com"
    assert message["Subject"] == "Cotización COT-001-000001 · El Clavo"
    [attachment] = list(message.iter_attachments())
    assert attachment.get_filename() == "cotizacion-COT-001-000001.pdf"
    assert attachment.get_content_type() == "application/pdf"
    assert attachment.get_content() == b"%PDF-1.4"


def test_it_goes_over_starttls_and_logs_in(smtp):
    SmtpMailer(
        "smtp.example.com", 587, "no-reply@faclab.ec", username="u", password="p"
    ).send(MAIL)

    smtp.starttls.assert_called_once()
    smtp.login.assert_called_once_with("u", "p")
    smtp.send_message.assert_called_once()


def test_a_server_without_tls_is_refused_unless_allowed(smtp):
    smtp.has_extn.return_value = False

    with pytest.raises(EmailDeliveryFailedError):
        SmtpMailer("smtp.example.com", 587, "no-reply@faclab.ec").send(MAIL)
    smtp.send_message.assert_not_called()

    # Mailpit, locally
    SmtpMailer("mailpit", 1025, "no-reply@faclab.local", require_tls=False).send(MAIL)
    smtp.send_message.assert_called_once()
    smtp.login.assert_not_called()


def test_a_refusal_or_an_unreachable_server_fails_the_delivery(smtp, mocker):
    smtp.send_message.side_effect = smtplib.SMTPRecipientsRefused({})

    with pytest.raises(EmailDeliveryFailedError) as refused:
        SmtpMailer("smtp.example.com", 587, "no-reply@faclab.ec").send(MAIL)
    assert refused.value.detail == "SMTPRecipientsRefused"

    mocker.patch(
        "src.shared.infra.mail.smtplib.SMTP", side_effect=ConnectionRefusedError()
    )
    with pytest.raises(EmailDeliveryFailedError):
        SmtpMailer("smtp.example.com", 587, "no-reply@faclab.ec").send(MAIL)


def test_smtps_connects_with_tls_from_the_start(mocker):
    server = MagicMock()
    server.__enter__.return_value = server
    ssl_smtp = mocker.patch(
        "src.shared.infra.mail.smtplib.SMTP_SSL", return_value=server
    )

    SmtpMailer("smtp.example.com", 465, "no-reply@faclab.ec", secure=True).send(MAIL)

    ssl_smtp.assert_called_once()
    server.send_message.assert_called_once()


def test_with_email_off_nothing_is_sent():
    with pytest.raises(EmailDisabledError):
        DisabledMailer().send(MAIL)
