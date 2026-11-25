"""The platform's read side of the tenants (S8.5): cross-tenant, so it runs with
faclab_worker's session (the console opens it), never with a request's."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from wireup import injectable

from src.invoicing.infra.models import InvoiceDiscrepancyModel
from src.organization.infra.models import BranchModel
from src.sales.infra.models import SaleModel
from src.shared.app.queries import Query, QueryHandler
from src.subscriptions.domain.entities import period_of
from src.subscriptions.infra.models import (
    DocumentUsageModel,
    PlanModel,
    SubscriptionModel,
)
from src.tenancy.domain.exceptions import TenantNotFoundError
from src.tenancy.infra.models import MembershipModel, TenantModel


def _plan(plan: PlanModel | None) -> dict[str, Any] | None:
    if plan is None:
        return None
    return {"code": plan.code, "name": plan.name}


def _row(tenant: TenantModel, subscription, plan, users: int, branches: int) -> dict:
    return {
        "id": tenant.id,
        "ruc": tenant.ruc,
        "legal_name": tenant.legal_name,
        "trade_name": tenant.trade_name,
        "status": tenant.status,
        "created_at": tenant.created_at,
        "subscription_status": subscription.status if subscription else None,
        "trial_ends_at": subscription.trial_ends_at if subscription else None,
        "plan": _plan(plan),
        "active_users": users,
        "active_branches": branches,
    }


def _counts(session: Session, tenant_ids: list[UUID]) -> tuple[dict, dict]:
    users = dict(
        session.execute(
            select(MembershipModel.tenant_id, func.count(MembershipModel.id))
            .where(MembershipModel.tenant_id.in_(tenant_ids))
            .where(MembershipModel.active.is_(True))
            .group_by(MembershipModel.tenant_id)
        ).all()
    )
    branches = dict(
        session.execute(
            select(BranchModel.tenant_id, func.count(BranchModel.id))
            .where(BranchModel.tenant_id.in_(tenant_ids))
            .where(BranchModel.is_active.is_(True))
            .group_by(BranchModel.tenant_id)
        ).all()
    )
    return users, branches


@dataclass
class ListTenantsQuery(Query):
    # RUC or name contains it
    q: str | None = None
    status: str | None = None
    limit: int = 50
    offset: int = 0


@injectable(lifetime="scoped")
class ListTenantsQueryHandler(QueryHandler[ListTenantsQuery, dict]):
    def __init__(self, session: Session):
        self.session = session

    def _handle(self, query: ListTenantsQuery) -> dict:
        criteria = []
        if query.q:
            pattern = f"%{query.q.strip()}%"
            criteria.append(
                or_(
                    TenantModel.ruc.like(pattern),
                    TenantModel.legal_name.ilike(pattern),
                    TenantModel.trade_name.ilike(pattern),
                )
            )
        if query.status:
            criteria.append(TenantModel.status == query.status)
        total = self.session.scalar(select(func.count(TenantModel.id)).where(*criteria))
        rows = self.session.execute(
            select(TenantModel, SubscriptionModel, PlanModel)
            .outerjoin(SubscriptionModel, SubscriptionModel.tenant_id == TenantModel.id)
            .outerjoin(PlanModel, PlanModel.id == SubscriptionModel.plan_id)
            .where(*criteria)
            .order_by(TenantModel.legal_name, TenantModel.id)
            .limit(query.limit)
            .offset(query.offset)
        ).all()
        users, branches = _counts(self.session, [row[0].id for row in rows])
        return {
            "items": [
                _row(t, s, p, users.get(t.id, 0), branches.get(t.id, 0))
                for t, s, p in rows
            ],
            "total": total or 0,
            "limit": query.limit,
            "offset": query.offset,
        }


@dataclass
class GetTenantQuery(Query):
    tenant_id: UUID


@injectable(lifetime="scoped")
class GetTenantQueryHandler(QueryHandler[GetTenantQuery, dict]):
    """A tenant with its billing state, from what core already knows: sales by
    invoice status, discrepancies and the month's electronic documents. The
    issuer's readiness (certificate, fiscal profile) is faclab-invoicing's and
    belongs to the company's administrator"""

    def __init__(self, session: Session):
        self.session = session

    def _handle(self, query: GetTenantQuery) -> dict:
        row = self.session.execute(
            select(TenantModel, SubscriptionModel, PlanModel)
            .outerjoin(SubscriptionModel, SubscriptionModel.tenant_id == TenantModel.id)
            .outerjoin(PlanModel, PlanModel.id == SubscriptionModel.plan_id)
            .where(TenantModel.id == query.tenant_id)
        ).first()
        if row is None:
            raise TenantNotFoundError()
        tenant, subscription, plan = row
        users, branches = _counts(self.session, [tenant.id])
        detail = _row(
            tenant,
            subscription,
            plan,
            users.get(tenant.id, 0),
            branches.get(tenant.id, 0),
        )
        detail["invoicing"] = self._invoicing(tenant.id)
        return detail

    def _invoicing(self, tenant_id: UUID) -> dict[str, Any]:
        by_status = dict(
            self.session.execute(
                select(SaleModel.invoice_status, func.count(SaleModel.id))
                .where(SaleModel.tenant_id == tenant_id)
                .where(SaleModel.invoice_status.is_not(None))
                .group_by(SaleModel.invoice_status)
            ).all()
        )
        unresolved = self.session.scalar(
            select(func.count(InvoiceDiscrepancyModel.id))
            .where(InvoiceDiscrepancyModel.tenant_id == tenant_id)
            .where(InvoiceDiscrepancyModel.status == "open")
        )
        uninvoiced = self.session.scalar(
            select(func.count(SaleModel.id))
            .where(SaleModel.tenant_id == tenant_id)
            .where(SaleModel.status == "CONFIRMED")
        )
        month = period_of(datetime.now(UTC))
        usage = self.session.execute(
            select(DocumentUsageModel.invoices, DocumentUsageModel.credit_notes)
            .where(DocumentUsageModel.tenant_id == tenant_id)
            .where(DocumentUsageModel.period == month)
        ).first()
        return {
            "pending_invoices": by_status.get("PENDING", 0),
            "rejected_invoices": by_status.get("REJECTED", 0),
            "authorized_invoices": by_status.get("AUTHORIZED", 0),
            "uninvoiced_sales": uninvoiced or 0,
            "open_discrepancies": unresolved or 0,
            "documents_this_month": (usage[0] + usage[1]) if usage else 0,
        }
