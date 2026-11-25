from src.shared.app.plans import PlanLimitReachedError, PlanLimits, PlanResource


class FakePlanLimits(PlanLimits):
    """A plan for unit tests: `full` resources have no room left (limit given
    in `limits`, 1 by default); every check is kept in `checked`"""

    def __init__(
        self,
        full: set[PlanResource] | None = None,
        limits: dict[PlanResource, int] | None = None,
    ):
        self.full = full or set()
        self.limits = limits or {}
        self.checked: list[PlanResource] = []

    def ensure_room(self, resource: PlanResource) -> None:
        self.checked.append(resource)
        if resource in self.full:
            raise PlanLimitReachedError(resource, self.limits.get(resource, 1))
