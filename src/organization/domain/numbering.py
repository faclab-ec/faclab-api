from enum import StrEnum


class DocumentType(StrEnum):
    """Documentos internos que el core numera por sucursal (ADR-0012)"""

    SALE = "SALE"
    REFUND = "REFUND"


_PREFIXES = {DocumentType.SALE: "V", DocumentType.REFUND: "D"}


def document_number(doc_type: DocumentType, establishment_code: str, value: int) -> str:
    """Número visible de un documento: prefijo, código de establecimiento de la
    sucursal y correlativo de seis dígitos (`V-001-000123`). Se guarda así en el
    documento, que conserva el código con el que se emitió."""
    return f"{_PREFIXES[doc_type]}-{establishment_code}-{value:06d}"
