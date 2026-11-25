from wireup import injectable

from src.shared.infra.mappers import Mapper
from src.subscriptions.domain.entities import Plan, Subscription
from src.subscriptions.infra.models import PlanModel, SubscriptionModel


@injectable(lifetime="singleton")
class PlanMapper(Mapper[Plan, PlanModel]):
    __entity__ = Plan


@injectable(lifetime="singleton")
class SubscriptionMapper(Mapper[Subscription, SubscriptionModel]):
    __entity__ = Subscription
