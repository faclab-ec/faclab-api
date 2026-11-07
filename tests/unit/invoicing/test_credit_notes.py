"""Credit notes (S4.5): when a refund asks for one, the invoice of a cancelled sale,
asking again and applying the result of faclab-invoicing."""

from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.invoicing.app.commands.credit_notes import (
    ApplyCreditNoteResultCommand,
    ApplyCreditNoteResultCommandHandler,
    RequestCancelledSaleCreditNoteCommand,
    RequestCancelledSaleCreditNoteCommandHandler,
    RequestCreditNoteAgainCommand,
    RequestCreditNoteAgainCommandHandler,
    RequestRefundCreditNotesCommand,
    RequestRefundCreditNotesCommandHandler,
)
from src.invoicing.domain.entities import (
    CreditNote,
    CreditNoteStatus,
    DiscrepancyKind,
    DiscrepancyStatus,
    InvoiceDiscrepancy,
)
from src.invoicing.domain.events import CreditNoteRequested
from src.invoicing.domain.exceptions import (
    CreditNoteAlreadyAuthorizedError,
    CreditNoteAlreadyRequestedError,
    CreditNoteNotApplicableError,
    FinalConsumerCreditNoteError,
)
from src.pos.refund.domain.entities import Refund, RefundItem, RefundStatus
from src.sales.domain.entities import InvoiceStatus, Sale, SaleItem, SaleStatus
from src.shared.app.audit import AuditAction
from src.shared.domain.exceptions import NotFoundError
from tests.audit import FakeAuditTrail

AUTHORIZED_AT = datetime(2026, 11, 2, 15, 4, 20)


def _sale(**fields: Any) -> Sale:
    values: dict[str, Any] = {
        "id": 1,
        "customer_id": 5,
        "status": SaleStatus.INVOICED,
        "invoice_status": InvoiceStatus.AUTHORIZED,
        "invoice_id": "inv-1",
        "subtotal": Decimal("100"),
        "discount": Decimal("10"),
        "total": Decimal("103.50"),
    }
    return Sale(**{**values, **fields})


def _refund(id: int = 45, **fields: Any) -> Refund:
    values: dict[str, Any] = {
        "original_sale_id": 1,
        "status": RefundStatus.COMPLETED,
        "reason": "Producto con defecto",
        "subtotal": Decimal("10.00"),
        "tax": Decimal("1.50"),
        "total": Decimal("11.50"),
    }
    return Refund(id=id, **{**values, **fields})


def _note(**fields: Any) -> CreditNote:
    values: dict[str, Any] = {
        "id": 31,
        "sale_id": 1,
        "invoice_id": "inv-1",
        "reason": "Producto con defecto",
        "refund_id": 45,
        "total": Decimal("11.50"),
    }
    return CreditNote(**{**values, **fields})


class TestTheCreditNote:
    def test_is_authorized_once(self):
        note = _note()

        assert note.authorize("doc-1", "001-001-000000012", "0" * 49, AUTHORIZED_AT)
        assert note.status == CreditNoteStatus.AUTHORIZED
        assert (note.document_id, note.number) == ("doc-1", "001-001-000000012")
        assert not note.authorize("doc-1", "001-001-000000012", "0" * 49, AUTHORIZED_AT)

    def test_an_authorization_wins_over_a_rejection_that_came_first(self):
        note = _note(status=CreditNoteStatus.REJECTED, rejection_reason="ERROR 68")

        assert note.authorize("doc-2", "001-001-000000013", "1" * 49, AUTHORIZED_AT)
        assert note.rejection_reason is None

    def test_is_rejected_only_while_pending(self):
        note = _note()

        assert note.reject("doc-1", "ERROR 68", "001-001-000000012", "0" * 49)
        assert (note.status, note.rejection_reason) == (
            CreditNoteStatus.REJECTED,
            "ERROR 68",
        )
        assert not note.reject("doc-1", "ERROR 68")

        authorized = _note(status=CreditNoteStatus.AUTHORIZED)
        assert not authorized.reject("doc-9", "tarde")
        assert authorized.status == CreditNoteStatus.AUTHORIZED

    def test_a_repeated_rejection_doesnt_touch_it_after_asking_again(self):
        note = _note()
        note.reject("doc-1", "ERROR 68")
        note.request_again()

        assert not note.reject("doc-1", "ERROR 68")
        assert note.status == CreditNoteStatus.PENDING
        assert note.reject("doc-2", "ERROR 43")

    def test_asking_again_clears_the_rejection_but_never_an_authorization(self):
        note = _note(status=CreditNoteStatus.REJECTED, rejection_reason="ERROR 68")

        note.request_again()

        assert (note.status, note.rejection_reason) == (CreditNoteStatus.PENDING, None)
        assert note.requested_at is not None
        with pytest.raises(CreditNoteAlreadyAuthorizedError):
            _note(status=CreditNoteStatus.AUTHORIZED).request_again()


class TestTheRuleOfTheSale:
    @pytest.mark.parametrize(
        ("fields", "has_invoice"),
        [
            ({"status": SaleStatus.INVOICED}, True),
            (
                {
                    "status": SaleStatus.CONFIRMED,
                    "invoice_status": InvoiceStatus.PENDING,
                },
                True,
            ),
            (
                {
                    "status": SaleStatus.CONFIRMED,
                    "invoice_status": InvoiceStatus.REJECTED,
                },
                False,
            ),
            ({"status": SaleStatus.CONFIRMED, "invoice_status": None}, False),
        ],
    )
    def test_final_consumer_counts_an_invoice_on_its_way(self, fields, has_invoice):
        assert _sale(customer_id=5, **fields).has_invoice is has_invoice
        assert (
            _sale(customer_id=None, **fields).invoiced_to_final_consumer is has_invoice
        )
        assert _sale(customer_id=5, **fields).invoiced_to_final_consumer is False

    def test_the_flag_alone_doesnt_make_it_final_consumer(self):
        """The invoice goes to its customer whatever the flag says"""
        sale = _sale(customer_id=5, is_final_consumer=True)

        assert sale.invoiced_to_final_consumer is False


class TestAskingForTheCreditNotesOfARefund:
    def _handler(self, sale, refunds=(), notes=()):
        sales, refund_repo, credit_notes, publisher = (
            MagicMock(),
            MagicMock(),
            MagicMock(),
            MagicMock(),
        )
        sales.get_by_id.return_value = sale
        refund_repo.filter_by.return_value = list(refunds)
        credit_notes.of_refunds.return_value = list(notes)
        credit_notes.create.side_effect = lambda note: replace(note, id=31)
        session = MagicMock()
        handler = RequestRefundCreditNotesCommandHandler(
            sales, refund_repo, credit_notes, publisher, session
        )
        return handler, credit_notes, publisher, session

    def test_an_invoiced_sale_asks_in_the_transaction_of_the_refund(self):
        handler, credit_notes, publisher, session = self._handler(
            _sale(), refunds=[_refund()]
        )

        assert handler.handle(RequestRefundCreditNotesCommand(sale_id=1)) == [31]

        note = credit_notes.create.call_args.args[0]
        assert (note.sale_id, note.refund_id, note.invoice_id, note.reason) == (
            1,
            45,
            "inv-1",
            "Producto con defecto",
        )
        assert (note.subtotal, note.tax, note.total) == (
            Decimal("10.00"),
            Decimal("1.50"),
            Decimal("11.50"),
        )
        event = publisher.publish.call_args.args[0]
        assert isinstance(event, CreditNoteRequested)
        assert (event.credit_note_id, event.sale_id) == (31, 1)
        assert publisher.publish.call_args.kwargs["session"] is session

    @pytest.mark.parametrize(
        "sale",
        [
            _sale(status=SaleStatus.CONFIRMED, invoice_status=InvoiceStatus.PENDING),
            _sale(status=SaleStatus.CONFIRMED, invoice_status=InvoiceStatus.REJECTED),
            _sale(status=SaleStatus.CANCELLED),
        ],
        ids=["pending", "rejected", "cancelled"],
    )
    def test_a_sale_not_invoiced_yet_waits(self, sale):
        handler, credit_notes, publisher, _ = self._handler(sale, refunds=[_refund()])

        assert handler.handle(RequestRefundCreditNotesCommand(sale_id=1)) == []

        credit_notes.create.assert_not_called()
        publisher.publish.assert_not_called()

    def test_only_the_refunds_without_one(self):
        """Once invoiced, each refund made meanwhile gets its own, and only once"""
        handler, credit_notes, publisher, _ = self._handler(
            _sale(),
            refunds=[_refund(45), _refund(46)],
            notes=[_note(refund_id=45)],
        )

        handler.handle(RequestRefundCreditNotesCommand(sale_id=1))

        credit_notes.create.assert_called_once()
        assert credit_notes.create.call_args.args[0].refund_id == 46
        publisher.publish.assert_called_once()

    def test_a_refund_without_a_reason_says_what_it_is(self):
        """Made before its sale had an invoice: the XML requires a motivo"""
        handler, credit_notes, _, _ = self._handler(
            _sale(), refunds=[_refund(reason=None)]
        )

        handler.handle(RequestRefundCreditNotesCommand(sale_id=1))

        assert credit_notes.create.call_args.args[0].reason == "Devolución"

    def test_a_final_consumer_invoice_asks_for_nothing(self):
        """NAC-DGERCGC25-00000014, art. 3"""
        handler, credit_notes, publisher, _ = self._handler(
            _sale(customer_id=None), refunds=[_refund()]
        )

        assert handler.handle(RequestRefundCreditNotesCommand(sale_id=1)) == []

        credit_notes.create.assert_not_called()
        publisher.publish.assert_not_called()

    def test_a_sale_invoiced_before_its_id_was_kept_asks_for_nothing(self):
        handler, credit_notes, _, _ = self._handler(
            _sale(invoice_id=None), refunds=[_refund()]
        )

        assert handler.handle(RequestRefundCreditNotesCommand(sale_id=1)) == []

        credit_notes.create.assert_not_called()

    def test_a_missing_sale(self):
        handler, *_ = self._handler(None)

        with pytest.raises(NotFoundError):
            handler.handle(RequestRefundCreditNotesCommand(sale_id=1))


class TestTheInvoiceOfACancelledSale:
    def _handler(self, discrepancy, sale=None, existing=None):
        discrepancies, sales, credit_notes, publisher = (
            MagicMock(),
            MagicMock(),
            MagicMock(),
            MagicMock(),
        )
        discrepancies.get_by_id.return_value = discrepancy
        sales.get_by_id.return_value = sale
        credit_notes.of_cancelled_sale.return_value = existing
        credit_notes.create.side_effect = lambda note: replace(note, id=32)
        audit = FakeAuditTrail()
        session = MagicMock()
        handler = RequestCancelledSaleCreditNoteCommandHandler(
            discrepancies, sales, credit_notes, publisher, audit, session
        )
        return handler, credit_notes, publisher, audit

    def _discrepancy(self, **fields: Any) -> InvoiceDiscrepancy:
        values: dict[str, Any] = {
            "id": 7,
            "sale_id": 1,
            "kind": DiscrepancyKind.AUTHORIZED_ON_CANCELLED,
            "invoice_id": "inv-9",
        }
        return InvoiceDiscrepancy(**{**values, **fields})

    def _command(self) -> RequestCancelledSaleCreditNoteCommand:
        return RequestCancelledSaleCreditNoteCommand(
            discrepancy_id=7, reason="Venta anulada"
        )

    def test_credits_the_whole_invoice_of_the_discrepancy(self):
        handler, credit_notes, publisher, audit = self._handler(
            self._discrepancy(),
            _sale(status=SaleStatus.CANCELLED, invoice_id=None, branch_id=2),
        )

        result = handler.handle(self._command())

        note = credit_notes.create.call_args.args[0]
        # The sale's invoice_id never got the id: its authorization came after
        assert (note.invoice_id, note.refund_id, note.reason) == (
            "inv-9",
            None,
            "Venta anulada",
        )
        # Net of its global discount, like the invoice
        assert (note.subtotal, note.tax, note.total) == (
            Decimal("90"),
            Decimal("13.50"),
            Decimal("103.50"),
        )
        assert result["id"] == 32
        publisher.publish.assert_called_once()
        [entry] = audit.entries
        assert entry.action == AuditAction.CREDIT_NOTE_REQUESTED
        assert (entry.resource_id, entry.branch_id) == (32, 2)

    @pytest.mark.parametrize(
        "fields",
        [
            {"kind": DiscrepancyKind.CONFIRMED_WITHOUT_RESULT},
            {"status": DiscrepancyStatus.RESOLVED},
            {"invoice_id": None},
        ],
        ids=["another-kind", "resolved", "no-invoice"],
    )
    def test_only_an_authorized_invoice_of_a_cancelled_sale(self, fields):
        handler, credit_notes, *_ = self._handler(self._discrepancy(**fields), _sale())

        with pytest.raises(CreditNoteNotApplicableError):
            handler.handle(self._command())

        credit_notes.create.assert_not_called()

    def test_a_reviewed_one_still_can(self):
        handler, credit_notes, *_ = self._handler(
            self._discrepancy(status=DiscrepancyStatus.REVIEWED),
            _sale(status=SaleStatus.CANCELLED),
        )

        handler.handle(self._command())

        credit_notes.create.assert_called_once()

    def test_the_final_consumer_stays_for_a_manual_review(self):
        handler, credit_notes, publisher, audit = self._handler(
            self._discrepancy(), _sale(customer_id=None)
        )

        with pytest.raises(FinalConsumerCreditNoteError):
            handler.handle(self._command())

        credit_notes.create.assert_not_called()
        publisher.publish.assert_not_called()
        assert audit.entries == []

    def test_once_per_sale(self):
        handler, credit_notes, *_ = self._handler(
            self._discrepancy(), _sale(), existing=_note(refund_id=None)
        )

        with pytest.raises(CreditNoteAlreadyRequestedError):
            handler.handle(self._command())

        credit_notes.create.assert_not_called()

    def test_missing_discrepancy_and_sale(self):
        with pytest.raises(NotFoundError):
            self._handler(None)[0].handle(self._command())
        with pytest.raises(NotFoundError):
            self._handler(self._discrepancy(), None)[0].handle(self._command())


class TestAskingAgain:
    def _handler(self, note):
        credit_notes, sales, publisher = MagicMock(), MagicMock(), MagicMock()
        credit_notes.get_by_id.return_value = note
        credit_notes.update.side_effect = lambda n: n
        sales.get_by_id.return_value = _sale(branch_id=2)
        audit = FakeAuditTrail()
        handler = RequestCreditNoteAgainCommandHandler(
            credit_notes, sales, publisher, audit, MagicMock()
        )
        return handler, publisher, audit

    def test_a_rejected_one_goes_again_with_a_new_event(self):
        handler, publisher, audit = self._handler(
            _note(status=CreditNoteStatus.REJECTED, rejection_reason="ERROR 68")
        )
        command = RequestCreditNoteAgainCommand(credit_note_id=31)

        result = handler.handle(command)

        assert result["status"] == CreditNoteStatus.PENDING
        assert publisher.publish.call_args.args[0].credit_note_id == 31
        [entry] = audit.entries
        assert entry.action == AuditAction.CREDIT_NOTE_REQUESTED_AGAIN
        assert entry.before == {
            "status": CreditNoteStatus.REJECTED,
            "rejection_reason": "ERROR 68",
        }
        assert entry.branch_id == 2

        first = publisher.publish.call_args.args[0].event_id
        handler.handle(command)
        assert publisher.publish.call_args.args[0].event_id != first

    def test_a_pending_one_goes_again_too(self):
        """Its result may never have arrived"""
        handler, publisher, _ = self._handler(_note())

        handler.handle(RequestCreditNoteAgainCommand(credit_note_id=31))

        publisher.publish.assert_called_once()

    def test_an_authorized_one_doesnt(self):
        handler, publisher, audit = self._handler(
            _note(status=CreditNoteStatus.AUTHORIZED)
        )

        with pytest.raises(CreditNoteAlreadyAuthorizedError):
            handler.handle(RequestCreditNoteAgainCommand(credit_note_id=31))

        publisher.publish.assert_not_called()
        assert audit.entries == []

    def test_a_missing_one(self):
        with pytest.raises(NotFoundError):
            self._handler(None)[0].handle(
                RequestCreditNoteAgainCommand(credit_note_id=31)
            )


class TestApplyingTheResult:
    def _handler(
        self,
        note,
        sale=None,
        sale_items=(),
        refunds=(),
        refund_items=(),
        notes=(),
        discrepancies=(),
    ):
        credit_notes, sales, sale_item_repo, refund_repo, refund_item_repo, disc = (
            MagicMock(),
            MagicMock(),
            MagicMock(),
            MagicMock(),
            MagicMock(),
            MagicMock(),
        )
        credit_notes.get_by_id.return_value = note
        credit_notes.update.side_effect = lambda n: n
        credit_notes.of_refunds.side_effect = lambda ids: list(ids) and list(notes)
        sales.get_by_id.return_value = sale or _sale()
        sale_item_repo.filter_by.return_value = list(sale_items)
        refund_repo.filter_by.return_value = list(refunds)
        refund_item_repo.filter_by.side_effect = lambda refund_id: [
            item for item in refund_items if item.refund_id == refund_id
        ]
        disc.unresolved.return_value = list(discrepancies)
        handler = ApplyCreditNoteResultCommandHandler(
            credit_notes, sales, sale_item_repo, refund_repo, refund_item_repo, disc
        )
        return handler, credit_notes, sales, disc

    def _authorized(self) -> ApplyCreditNoteResultCommand:
        return ApplyCreditNoteResultCommand(
            credit_note_id=31,
            document_id="doc-1",
            authorized=True,
            number="001-002-000000012",
            access_code="0" * 49,
            authorized_at=AUTHORIZED_AT,
        )

    def _item(self, id: int = 10, quantity: int = 2) -> SaleItem:
        return SaleItem(
            id=id,
            sale_id=1,
            product_id=7,
            quantity=Decimal(quantity),
            unit_price=Decimal("10"),
        )

    def _refunded(self, refund_id: int, quantity: int) -> RefundItem:
        return RefundItem(
            refund_id=refund_id,
            original_sale_item_id=10,
            product_id=7,
            quantity=Decimal(quantity),
            unit_price=Decimal("10"),
        )

    def test_keeps_the_number_and_the_document(self):
        note = _note()
        handler, credit_notes, *_ = self._handler(note)

        result = handler.handle(self._authorized())

        assert result["status"] == CreditNoteStatus.AUTHORIZED
        assert (note.number, note.document_id, note.authorized_at) == (
            "001-002-000000012",
            "doc-1",
            AUTHORIZED_AT,
        )
        credit_notes.update.assert_called_once()

    def test_a_partial_refund_doesnt_credit_the_whole_invoice(self):
        sale = _sale()
        note = _note()
        handler, _, sales, _ = self._handler(
            note,
            sale=sale,
            sale_items=[self._item(quantity=2)],
            refunds=[_refund(45)],
            refund_items=[self._refunded(45, 1)],
            notes=[note],
        )

        handler.handle(self._authorized())

        assert sale.invoice_status == InvoiceStatus.AUTHORIZED
        sales.update.assert_not_called()

    def test_everything_refunded_and_authorized_credits_the_invoice(self):
        """The sale stays INVOICED: cash and reports count its refunds"""
        sale = _sale()
        first = _note(id=30, refund_id=44, status=CreditNoteStatus.AUTHORIZED)
        note = _note()
        handler, _, sales, _ = self._handler(
            note,
            sale=sale,
            sale_items=[self._item(quantity=2)],
            refunds=[_refund(44), _refund(45)],
            refund_items=[self._refunded(44, 1), self._refunded(45, 1)],
            notes=[first, note],
        )

        handler.handle(self._authorized())

        assert sale.invoice_status == InvoiceStatus.CREDITED
        assert sale.status == SaleStatus.INVOICED
        sales.update.assert_called_once_with(sale)

    def test_waits_for_every_credit_note_of_the_sale(self):
        sale = _sale()
        other = _note(id=30, refund_id=44, status=CreditNoteStatus.PENDING)
        note = _note()
        handler, *_ = self._handler(
            note,
            sale=sale,
            sale_items=[self._item(quantity=2)],
            refunds=[_refund(44), _refund(45)],
            refund_items=[self._refunded(44, 1), self._refunded(45, 1)],
            notes=[other, note],
        )

        handler.handle(self._authorized())

        assert sale.invoice_status == InvoiceStatus.AUTHORIZED

    def test_the_invoice_of_a_cancelled_sale_resolves_its_discrepancy(self):
        sale = _sale(status=SaleStatus.CANCELLED, invoice_id=None, invoice_status=None)
        discrepancy = InvoiceDiscrepancy(
            id=7,
            sale_id=1,
            kind=DiscrepancyKind.AUTHORIZED_ON_CANCELLED,
            invoice_id="inv-9",
        )
        handler, _, sales, discrepancies = self._handler(
            _note(refund_id=None, invoice_id="inv-9"),
            sale=sale,
            discrepancies=[discrepancy],
        )

        handler.handle(self._authorized())

        assert (sale.invoice_status, sale.invoice_id) == (
            InvoiceStatus.CREDITED,
            "inv-9",
        )
        assert sale.status == SaleStatus.CANCELLED
        sales.update.assert_called_once_with(sale)
        assert discrepancy.status == DiscrepancyStatus.RESOLVED
        discrepancies.update.assert_called_once_with(discrepancy)

    def test_a_repeated_result_changes_nothing(self):
        note = _note(status=CreditNoteStatus.AUTHORIZED, document_id="doc-1")
        handler, credit_notes, sales, _ = self._handler(note)

        handler.handle(self._authorized())

        credit_notes.update.assert_not_called()
        sales.update.assert_not_called()

    def test_a_rejection_keeps_the_reason_and_leaves_the_sale_alone(self):
        note = _note()
        handler, credit_notes, sales, _ = self._handler(note)

        result = handler.handle(
            ApplyCreditNoteResultCommand(
                credit_note_id=31,
                document_id="doc-1",
                authorized=False,
                number="001-002-000000012",
                reason="ERROR 68: Documento sustento",
            )
        )

        assert result["status"] == CreditNoteStatus.REJECTED
        assert note.rejection_reason == "ERROR 68: Documento sustento"
        credit_notes.update.assert_called_once()
        sales.update.assert_not_called()

    def test_a_repeated_rejection_changes_nothing(self):
        note = _note(status=CreditNoteStatus.REJECTED, document_id="doc-1")
        handler, credit_notes, *_ = self._handler(note)

        handler.handle(
            ApplyCreditNoteResultCommand(
                credit_note_id=31, document_id="doc-1", authorized=False
            )
        )

        credit_notes.update.assert_not_called()

    def test_a_missing_one(self):
        handler, *_ = self._handler(None)

        with pytest.raises(NotFoundError):
            handler.handle(self._authorized())
