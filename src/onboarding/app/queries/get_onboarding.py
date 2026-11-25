"""The company's onboarding checklist (S8.5), derived from what exists: nothing
is stored, so the wizard can be left and resumed at any time and a step done
outside it counts. It covers what core owns; the fiscal profile, the
certificate, the sequences and the readiness are faclab-invoicing's and the
wizard reads them there."""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from wireup import injectable

from src.imports.infra.models import ImportJobModel
from src.organization.infra.models import (
    BranchModel,
    EmissionPointModel,
    PosTerminalModel,
)
from src.shared.app.queries import Query, QueryHandler
from src.shared.domain.tenant import require_tenant
from src.shared.infra.tenant import tenant_criteria
from src.tenancy.infra.models import MembershipModel


@dataclass
class GetOnboardingQuery(Query):
    pass


def _count(session: Session, model, *criteria) -> int:
    return (
        session.scalar(
            select(func.count(model.id)).where(*tenant_criteria(model), *criteria)
        )
        or 0
    )


@injectable(lifetime="scoped")
class GetOnboardingQueryHandler(QueryHandler[GetOnboardingQuery, dict]):
    def __init__(self, session: Session):
        self.session = session

    def _handle(self, query: GetOnboardingQuery) -> dict:
        tenant_id = require_tenant("the onboarding").tenant_id
        branches = _count(self.session, BranchModel, BranchModel.is_active.is_(True))
        points = _count(
            self.session, EmissionPointModel, EmissionPointModel.is_active.is_(True)
        )
        terminals = _count(
            self.session, PosTerminalModel, PosTerminalModel.is_active.is_(True)
        )
        # Memberships have no row-level security: filter by the tenant
        users = (
            self.session.scalar(
                select(func.count(MembershipModel.id))
                .where(MembershipModel.tenant_id == tenant_id)
                .where(MembershipModel.active.is_(True))
            )
            or 0
        )
        imported = _count(
            self.session, ImportJobModel, ImportJobModel.status == "COMPLETED"
        )
        steps: list[dict[str, Any]] = [
            _step("branches", branches >= 1, branches),
            _step("emission_points", points >= 1, points),
            _step("terminals", terminals >= 1, terminals),
            # More than the administrator who was created with the company
            _step("users", users > 1, users, required=False),
            _step("import", imported >= 1, imported, required=False),
        ]
        required = [step for step in steps if step["required"]]
        return {
            "steps": steps,
            "ready": all(step["done"] for step in required),
        }


def _step(key: str, done: bool, count: int, required: bool = True) -> dict[str, Any]:
    return {"key": key, "done": done, "count": count, "required": required}
