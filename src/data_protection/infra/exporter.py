"""The ZIP of a company's data (S8.7): one CSV per table and a manifest.

Tables come from `Base.metadata`, so a new one is exported without touching this
file: every table with a `tenant_id` (the business ones with row-level security
and the platform ones with no policy: memberships, branch accesses), plus the
company's own `tenants` row and the `users` of its memberships. Rows are read
as faclab_worker (no row-level security), so each query filters by tenant itself.

Left out, and said in the manifest: what is technical and not the company's data
(idempotency keys, the outbox, sessions, dead letters, the integrations'
directory) and every secret (password hashes, secret hashes, encrypted
secrets, refresh token ids).
"""

import csv
import io
import json
import os
import zipfile
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import Table, select
from sqlalchemy.orm import Session

from src.shared.infra.database import Base

BATCH = 1000

# Technical tables: they hold no data of the company that isn't somewhere else
EXCLUDED_TABLES = {
    "idempotency_keys": "stored responses of retried requests",
    "outbox_messages": "messages on their way to other services",
    "dead_letters": "messages the consumer gave up on",
    "auth_sessions": "login sessions",
    "integration_client_directory": "lookup of client ids",
    "export_jobs": "this export's own records",
}
# Columns that are secrets, by name (and any `*_ciphertext`)
EXCLUDED_COLUMNS = {
    "password_hash",
    "secret_hash",
    "refresh_jti",
    "previous_refresh_jti",
}
NOTE = (
    "Electronic invoices and credit notes (signed XML and RIDE PDF) are kept by "
    "faclab-invoicing and exported there (docs/offboarding-runbook.md)."
)


def _is_secret(column: str) -> bool:
    return column in EXCLUDED_COLUMNS or column.endswith("_ciphertext")


def export_tables() -> list[Table]:
    """The tables of the export, in dependency order"""
    tables = []
    for table in Base.metadata.sorted_tables:
        if table.name in EXCLUDED_TABLES:
            continue
        if table.name in ("tenants", "users") or "tenant_id" in table.c:
            tables.append(table)
    return tables


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, default=str)
    if isinstance(value, (bytes, memoryview)):
        return bytes(value).hex()
    return str(value)


def _statement(table: Table, tenant_id: UUID):
    columns = [c for c in table.columns if not _is_secret(c.name)]
    statement = select(*columns)
    if table.name == "tenants":
        statement = statement.where(table.c.id == tenant_id)
    elif table.name == "users":
        memberships = Base.metadata.tables["memberships"]
        statement = statement.where(
            table.c.id.in_(
                select(memberships.c.user_id).where(
                    memberships.c.tenant_id == tenant_id
                )
            )
        )
    else:
        statement = statement.where(table.c.tenant_id == tenant_id)
    return statement.order_by(*table.primary_key.columns), [c.name for c in columns]


def write_export(session: Session, tenant_id: UUID, path: Path) -> dict[str, int]:
    """Writes the ZIP to `path` (through a temporary file, so a half-written one
    is never there) and returns the rows per table"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".part")
    counts: dict[str, int] = {}
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            for table in export_tables():
                statement, header = _statement(table, tenant_id)
                counts[table.name] = _write_table(
                    archive, session, table.name, statement, header
                )
            archive.writestr(
                "manifest.json",
                json.dumps(
                    _manifest(session, tenant_id, counts),
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return counts


def _write_table(
    archive: zipfile.ZipFile, session: Session, name: str, statement, header: list[str]
) -> int:
    rows = 0
    with archive.open(f"{name}.csv", "w", force_zip64=True) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
        writer = csv.writer(text)
        writer.writerow(header)
        result = session.execute(statement.execution_options(stream_results=True))
        for partition in result.partitions(BATCH):
            for row in partition:
                writer.writerow([_cell(value) for value in row])
            rows += len(partition)
        text.flush()
        text.detach()
    return rows


def _manifest(session: Session, tenant_id: UUID, counts: dict[str, int]) -> dict:
    tenants = Base.metadata.tables["tenants"]
    tenant = session.execute(
        select(tenants.c.ruc, tenants.c.legal_name).where(tenants.c.id == tenant_id)
    ).one()
    return {
        "format": "faclab-export",
        "version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "tenant": {
            "id": str(tenant_id),
            "ruc": tenant.ruc,
            "legal_name": tenant.legal_name,
        },
        "encoding": "UTF-8 with BOM, comma separated, dates ISO 8601, JSON columns as JSON text",
        "tables": counts,
        "excluded_tables": EXCLUDED_TABLES,
        "excluded_columns": sorted(EXCLUDED_COLUMNS) + ["*_ciphertext"],
        "note": NOTE,
    }
