"""The plans, written by the platform (its CLI, S8.4; a console in S8.5)."""

from dataclasses import dataclass, field
from typing import Any

from wireup import injectable

from src.shared.app.commands import Command, CommandHandler
from src.shared.domain.exceptions import InvalidValueError, NotFoundError
from src.subscriptions.app.repositories import PlanRepository
from src.subscriptions.domain.entities import PLAN_FIELDS, Plan
from src.subscriptions.domain.exceptions import (
    DefaultPlanRequiredError,
    PlanCodeAlreadyExistsError,
)


def describe_plan(plan: Plan) -> dict[str, Any]:
    return {"id": plan.id, **{name: getattr(plan, name) for name in PLAN_FIELDS}}


def _make_default(plans: PlanRepository, plan: Plan) -> Plan:
    """At most one default: the previous one stops being it first"""
    plan.ensure_assignable()
    previous = plans.default()
    if previous is not None and previous.id != plan.id:
        previous.is_default = False
        plans.update(previous)
    plan.is_default = True
    return plans.update(plan)


@dataclass
class CreatePlanCommand(Command):
    code: str
    name: str
    # max_<resource> and max_monthly_documents; missing or None: no limit
    limits: dict[str, int | None] = field(default_factory=dict)
    public_api: bool = True
    is_default: bool = False


@injectable(lifetime="scoped")
class CreatePlanCommandHandler(CommandHandler[CreatePlanCommand, dict]):
    def __init__(self, plans: PlanRepository):
        self.plans = plans

    def _handle(self, command: CreatePlanCommand) -> dict:
        unknown = set(command.limits) - {n for n in PLAN_FIELDS if n.startswith("max_")}
        if unknown:
            raise InvalidValueError(f"unknown limits: {sorted(unknown)}")
        values: dict[str, Any] = {
            "code": command.code,
            "name": command.name,
            "public_api": command.public_api,
            **command.limits,
        }
        plan = Plan(**values)
        if self.plans.first(code=plan.code) is not None:
            raise PlanCodeAlreadyExistsError(f"Plan '{plan.code}' already exists")
        plan = self.plans.create(plan)
        if command.is_default:
            plan = _make_default(self.plans, plan)
        return describe_plan(plan)


@dataclass
class UpdatePlanCommand(Command):
    code: str
    # Any field but the code: name, max_*, public_api, is_active, is_default
    changes: dict[str, Any] = field(default_factory=dict)


@injectable(lifetime="scoped")
class UpdatePlanCommandHandler(CommandHandler[UpdatePlanCommand, dict]):
    """The subscriptions on a plan see its new limits at once; what a tenant
    already has stays even when a limit goes below it"""

    def __init__(self, plans: PlanRepository):
        self.plans = plans

    def _handle(self, command: UpdatePlanCommand) -> dict:
        plan = self.plans.first(code=command.code.strip().lower())
        if plan is None:
            raise NotFoundError(f"Plan '{command.code}' not found")
        changes = dict(command.changes)
        unknown = (set(changes) - set(PLAN_FIELDS)) | ({"code"} & set(changes))
        if unknown:
            raise InvalidValueError(f"fields that can't change: {sorted(unknown)}")
        becomes_default = changes.pop("is_default", None)
        if plan.is_default and (
            becomes_default is False or changes.get("is_active") is False
        ):
            raise DefaultPlanRequiredError(
                "The default plan stays active and default: make another plan "
                "the default first"
            )
        values = {name: getattr(plan, name) for name in PLAN_FIELDS}
        updated = Plan(id=plan.id, **{**values, **changes})
        updated = self.plans.update(updated)
        if becomes_default and not updated.is_default:
            updated = _make_default(self.plans, updated)
        return describe_plan(updated)
