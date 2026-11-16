"""Clientes y proveedores (S5.8): uno por identificación, validada como cédula o
RUC ecuatoriano cuando es de ese tipo."""

from collections.abc import Iterable
from typing import Any

from wireup import injectable

from src.customers.app.commands.customer import (
    ChangeCustomerPriceListCommand,
    ChangeCustomerPriceListCommandHandler,
    CreateCustomerCommand,
    CreateCustomerCommandHandler,
    UpdateCustomerCommand,
    UpdateCustomerCommandHandler,
)
from src.customers.domain.entities import Customer
from src.imports.app.columns import Column, boolean, choice, money, text, whole
from src.imports.app.kinds.base import INVALID_VALUE, NOT_FOUND, KindImporter, RowPlan
from src.imports.app.lookups import ImportLookups, key
from src.imports.domain.entities import ImportJob, ImportKind, ImportMode
from src.shared.domain.exceptions import InvalidValueError
from src.shared.domain.tax import TaxType
from src.shared.domain.value_objects import Email, TaxId
from src.suppliers.app.commands.supplier import (
    CreateSupplierCommand,
    CreateSupplierCommandHandler,
    UpdateSupplierCommand,
    UpdateSupplierCommandHandler,
)
from src.suppliers.domain.entities import Supplier

TAX_TYPES: dict[str, TaxType] = {
    "RUC": TaxType.RUC,
    "1": TaxType.RUC,
    "CEDULA": TaxType.NATIONAL_ID,
    "2": TaxType.NATIONAL_ID,
    "PASAPORTE": TaxType.PASSPORT,
    "3": TaxType.PASSPORT,
    "EXTERIOR": TaxType.FOREIGN_ID,
    "IDENTIFICACION_EXTERIOR": TaxType.FOREIGN_ID,
    "4": TaxType.FOREIGN_ID,
}
_VALIDATED_TYPES = (TaxType.RUC, TaxType.NATIONAL_ID)

TAX_TYPE = Column(
    "tipo_identificacion",
    "tax_type",
    "RUC, CEDULA, PASAPORTE o EXTERIOR",
    "CEDULA",
    required=True,
    parse=choice(TAX_TYPES, "Tipo de identificación"),
)
TAX_ID = Column(
    "identificacion",
    "tax_id",
    "Cédula, RUC o pasaporte, único en la empresa. Una cédula o RUC sin el cero "
    "inicial (Excel lo quita en celdas numéricas) se completa",
    "1710034065",
    key=True,
    required=True,
    parse=text(32),
)
NAME = Column(
    "nombre",
    "name",
    "Nombre o razón social",
    "Ferretería El Clavo",
    required=True,
    parse=text(128),
)
EMAIL = Column("email", "email", "Correo electrónico", "", parse=text(128))
PHONE = Column("telefono", "phone", "Teléfono", "", parse=text(32))
ADDRESS = Column("direccion", "address", "Dirección", "", parse=text(255))
CITY = Column("ciudad", "city", "Ciudad", "Quito", parse=text(64))
STATE = Column("provincia", "state", "Provincia", "Pichincha", parse=text(64))
COUNTRY = Column("pais", "country", "País", "Ecuador", parse=text(64))
CREDIT_LIMIT = Column(
    "cupo",
    "credit_limit",
    "Cupo de crédito; vacía al crear: no compra a crédito",
    "500",
    parse=money,
)
PAYMENT_TERMS = Column(
    "plazo_dias", "payment_terms", "Plazo de crédito en días", "30", parse=whole
)
PRICE_LIST = Column(
    "lista_precios",
    "price_list",
    "Nombre de la lista de precios con que compra (debe existir); vacía: la de "
    "su sucursal o la general",
    "",
    parse=text(64),
)
LEAD_TIME = Column(
    "dias_entrega", "lead_time_days", "Días que tarda en entregar", "", parse=whole
)
NOTES = Column("notas", "notes", "Notas", "", parse=text(512))
IS_ACTIVE = Column(
    "activo",
    "is_active",
    "NO para dejarlo inactivo; vacía al crear, SI",
    "SI",
    parse=boolean,
)


def tax_id_candidates(raw: str, tax_type: TaxType | None) -> list[str]:
    """La identificación como está y, si es una cédula o RUC numérico al que le
    falta el cero inicial (Excel lo quita), con él"""
    candidates = [raw]
    if tax_type in (None, *_VALIDATED_TYPES) and raw.isdigit() and len(raw) in (9, 12):
        candidates.append("0" + raw)
    return candidates


class _PartnerImporter(KindImporter):
    """Lo común a clientes y proveedores; cada uno dice sus campos y comandos"""

    fields: tuple[Column, ...]
    defaults: dict[str, Any]

    def __init__(self, lookups: ImportLookups):
        self.lookups = lookups

    def _existing(self, tax_ids: Iterable[str]) -> dict[str, Customer | Supplier]:
        raise NotImplementedError

    def _current(self, record: Any) -> dict[str, Any]:
        return {
            "name": record.name,
            "tax_type": TaxType(record.tax_type),
            **{column.field: getattr(record, column.field) for column in self.fields},
        }

    def _prepare(self, plans: list[RowPlan]) -> None:
        """Lo que hace falta leer antes de planificar, además de los registros"""

    def _extra(self, plan: RowPlan, payload: dict[str, Any]) -> None:
        """Campos que no son del registro (la lista de precios del cliente)"""

    def _plan(self, plans: list[RowPlan], mode: ImportMode) -> None:
        self._prepare(plans)
        candidates = {
            plan.row_number: tax_id_candidates(plan.get(TAX_ID), plan.get(TAX_TYPE))
            for plan in plans
        }
        existing = self._existing(
            tax_id for values in candidates.values() for tax_id in values
        )
        for plan in plans:
            options = candidates[plan.row_number]
            match = next((tax_id for tax_id in options if tax_id in existing), None)
            # A new one keeps the zero only when it is a cédula or RUC
            plan.payload["tax_id"] = match or (
                options[-1] if plan.get(TAX_TYPE) in _VALIDATED_TYPES else options[0]
            )
        self.unique_in_file(
            plans, lambda p: p.payload["tax_id"], TAX_ID, "La identificación"
        )

        for plan in plans:
            if not plan.ok:
                continue
            tax_id = plan.payload["tax_id"]
            record = existing.get(tax_id)
            if record is not None:
                plan.target_id = record.require_id()
                if mode == ImportMode.SKIP:
                    self.settle(plan, mode, changed=False)
                    continue
                current = self._current(record)
            elif not self.require(plan, TAX_TYPE, NAME):
                continue
            else:
                current = {"name": None, "tax_type": None, **self.defaults}

            payload = dict(current)
            for column in (TAX_TYPE, NAME, *self.fields):
                if plan.has(column):
                    payload[column.field] = plan.get(column)
            self._extra(plan, payload)

            if email := payload.get("email"):
                try:
                    Email(email)
                except InvalidValueError:
                    plan.error(EMAIL, INVALID_VALUE, "No es un correo válido")
            if payload["tax_type"] in _VALIDATED_TYPES:
                try:
                    TaxId(tax_id)
                except InvalidValueError:
                    plan.error(
                        TAX_ID,
                        INVALID_VALUE,
                        "No es una cédula o RUC ecuatoriano válido",
                    )

            # What changed, so an update only writes that (a new one: all)
            changes = {
                name for name, value in current.items() if payload[name] != value
            }
            plan.payload = {"tax_id": tax_id, **payload, "changes": changes}
            if plan.ok and record is not None:
                self.settle(plan, mode, changed=bool(changes))

    @staticmethod
    def _data(payload: dict[str, Any], *names: str) -> dict[str, Any]:
        """Los campos del comando: sin los que no son del registro"""
        skip = {"changes", *names}
        data = {name: value for name, value in payload.items() if name not in skip}
        data["tax_type"] = int(data["tax_type"])
        return data


@injectable(lifetime="scoped")
class CustomerImporter(_PartnerImporter):
    kind = ImportKind.CUSTOMERS
    fields = (
        EMAIL,
        PHONE,
        ADDRESS,
        CITY,
        STATE,
        COUNTRY,
        CREDIT_LIMIT,
        PAYMENT_TERMS,
        IS_ACTIVE,
    )
    columns = (TAX_TYPE, TAX_ID, NAME, *fields[:-1], PRICE_LIST, IS_ACTIVE)
    defaults: dict[str, Any] = {
        "email": None,
        "phone": None,
        "address": None,
        "city": None,
        "state": None,
        "country": None,
        "credit_limit": None,
        "payment_terms": None,
        "is_active": True,
        "price_list_id": None,
    }

    def __init__(
        self,
        lookups: ImportLookups,
        create: CreateCustomerCommandHandler,
        update: UpdateCustomerCommandHandler,
        change_price_list: ChangeCustomerPriceListCommandHandler,
    ):
        super().__init__(lookups)
        self.create = create
        self.update = update
        self.change_price_list = change_price_list
        self._lists: dict[str, int] = {}

    def _existing(self, tax_ids: Iterable[str]) -> dict[str, Customer | Supplier]:
        return dict(self.lookups.customers(tax_ids))

    def _current(self, record: Any) -> dict[str, Any]:
        return {**super()._current(record), "price_list_id": record.price_list_id}

    def _prepare(self, plans: list[RowPlan]) -> None:
        self._lists = (
            {name: ref.id for name, ref in self.lookups.price_lists().items()}
            if any(plan.has(PRICE_LIST) for plan in plans)
            else {}
        )

    def _extra(self, plan: RowPlan, payload: dict[str, Any]) -> None:
        if not plan.has(PRICE_LIST):
            return
        price_list_id = self._lists.get(key(plan.get(PRICE_LIST)))
        if price_list_id is None:
            plan.error(
                PRICE_LIST,
                NOT_FOUND,
                f"No existe la lista de precios {plan.get(PRICE_LIST)}",
            )
        payload["price_list_id"] = price_list_id

    def execute(self, job: ImportJob, plans: list[RowPlan]) -> None:
        for plan in self.writes(plans):
            with self.row(plan):
                changes = plan.payload["changes"]
                price_list_id = plan.payload["price_list_id"]
                data = self._data(plan.payload, "price_list_id")
                if plan.target_id is None:
                    customer = self.create.handle(CreateCustomerCommand(**data))
                    plan.record_id = customer["id"]
                else:
                    plan.record_id = plan.target_id
                    if changes - {"price_list_id"}:
                        self.update.handle(
                            UpdateCustomerCommand(id=plan.target_id, **data)
                        )
                # Apart, like the route: it is audited (S5.3)
                if "price_list_id" in changes:
                    self.change_price_list.handle(
                        ChangeCustomerPriceListCommand(
                            customer_id=plan.record_id, price_list_id=price_list_id
                        )
                    )


@injectable(lifetime="scoped")
class SupplierImporter(_PartnerImporter):
    kind = ImportKind.SUPPLIERS
    fields = (
        EMAIL,
        PHONE,
        ADDRESS,
        CITY,
        COUNTRY,
        PAYMENT_TERMS,
        LEAD_TIME,
        NOTES,
        IS_ACTIVE,
    )
    columns = (TAX_TYPE, TAX_ID, NAME, *fields)
    defaults: dict[str, Any] = {
        "email": None,
        "phone": None,
        "address": None,
        "city": None,
        "country": None,
        "payment_terms": None,
        "lead_time_days": None,
        "notes": None,
        "is_active": True,
    }

    def __init__(
        self,
        lookups: ImportLookups,
        create: CreateSupplierCommandHandler,
        update: UpdateSupplierCommandHandler,
    ):
        super().__init__(lookups)
        self.create = create
        self.update = update

    def _existing(self, tax_ids: Iterable[str]) -> dict[str, Customer | Supplier]:
        return dict(self.lookups.suppliers(tax_ids))

    def execute(self, job: ImportJob, plans: list[RowPlan]) -> None:
        for plan in self.writes(plans):
            with self.row(plan):
                data = self._data(plan.payload)
                if plan.target_id is None:
                    supplier = self.create.handle(CreateSupplierCommand(**data))
                    plan.record_id = supplier["id"]
                else:
                    self.update.handle(UpdateSupplierCommand(id=plan.target_id, **data))
                    plan.record_id = plan.target_id
