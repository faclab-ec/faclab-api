from src.audit.app.queries.audit_log import ListAuditLogQueryHandler
from src.audit.infra.trail import SqlAlchemyAuditTrail

INJECTABLES = [
    SqlAlchemyAuditTrail,
    ListAuditLogQueryHandler,
]
