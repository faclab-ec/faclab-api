import json
from typing import Any

from opentelemetry.propagate import inject
from sqlalchemy import event
from sqlalchemy.orm import Session
from wireup import injectable

from src.shared.infra.kafka.producer import json_default
from src.shared.infra.outbox import relay
from src.shared.infra.outbox.models import OutboxMessageModel


@injectable(lifetime="scoped")
class OutboxWriter:
    """Guarda mensajes para Kafka dentro de la transacción del request.

    Publicar directo a Kafka antes del commit es una escritura doble: una venta
    revertida podía llegar a facturación. El relay publica estos mensajes solo
    cuando la transacción ya se confirmó.
    """

    def __init__(self, session: Session):
        self.session = session

    def add(
        self, topic: str, payload: dict[str, Any], event_type: str, event_id: str
    ) -> None:
        headers: dict[str, str] = {}
        inject(carrier=headers)
        self.session.add(
            OutboxMessageModel(
                event_id=event_id,
                event_type=event_type,
                topic=topic,
                # Stored as plain JSON: Decimal -> str, datetime -> ISO 8601
                payload=json.loads(json.dumps(payload, default=json_default)),
                headers=headers,
            )
        )
        self.session.flush()
        event.listen(self.session, "after_commit", _wake_relay, once=True)


def _wake_relay(_session: Session) -> None:
    relay.wake()
