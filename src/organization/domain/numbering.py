from enum import StrEnum


class DocumentType(StrEnum):
    """Documentos internos que el core numera (ADR-0012): ventas, devoluciones y
    cotizaciones (S5.4) por sucursal; órdenes de compra y abonos de clientes
    (S5.5) por empresa"""

    SALE = "SALE"
    REFUND = "REFUND"
    PURCHASE_ORDER = "PURCHASE_ORDER"
    QUOTE = "QUOTE"
    CUSTOMER_PAYMENT = "CUSTOMER_PAYMENT"


_PREFIXES = {
    DocumentType.SALE: "V",
    DocumentType.REFUND: "D",
    DocumentType.PURCHASE_ORDER: "PO",
    DocumentType.QUOTE: "COT",
    DocumentType.CUSTOMER_PAYMENT: "AB",
}


def document_number(doc_type: DocumentType, establishment_code: str, value: int) -> str:
    """Número visible de un documento: prefijo, código de establecimiento de la
    sucursal y correlativo de seis dígitos (`V-001-000123`). Se guarda así en el
    documento, que conserva el código con el que se emitió."""
    return f"{_PREFIXES[doc_type]}-{establishment_code}-{value:06d}"


def tenant_document_number(doc_type: DocumentType, year: int, value: int) -> str:
    """Número de un documento de toda la empresa: prefijo, año y correlativo de
    cuatro dígitos (`PO-2026-0001`). El correlativo no vuelve a 1 cada año: el
    año solo dice cuándo se emitió."""
    return f"{_PREFIXES[doc_type]}-{year}-{value:04d}"
