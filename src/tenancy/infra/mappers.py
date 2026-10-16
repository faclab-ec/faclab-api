from wireup import injectable

from src.shared.infra.mappers import Mapper
from src.tenancy.domain.entities import Membership, Tenant
from src.tenancy.infra.models import MembershipModel, TenantModel


@injectable(lifetime="singleton")
class TenantMapper(Mapper[Tenant, TenantModel]):
    __entity__ = Tenant
    __exclude_fields__ = frozenset({"created_at"})


@injectable(lifetime="singleton")
class MembershipMapper(Mapper[Membership, MembershipModel]):
    __entity__ = Membership
    __exclude_fields__ = frozenset({"created_at"})
