"""La mensajería de un proceso: productor, relay del outbox y consumidor.

La arma el worker (`worker.py`) y, con RUN_BACKGROUND, también el API. Aquí se
juntan los handlers de cada topic que consume el core, por eso vive fuera de
`shared`: importa los módulos.
"""

from collections.abc import Callable

from config import config
from src.invoicing.infra.invoice_messages import INVOICES_TOPIC, handle_invoice_message
from src.shared.infra.database import worker_session_maker
from src.shared.infra.kafka.consumer import KafkaMessageConsumer, MessageHandler
from src.shared.infra.kafka.dead_letters import DeadLetterStore
from src.shared.infra.kafka.producer import KafkaEventProducer
from src.shared.infra.outbox import relay as outbox_relay
from src.shared.infra.outbox.relay import OutboxRelay

# Topics core consumes. Marks sales as invoiced (or their invoice as rejected)
# when faclab-invoicing reports the SRI result
CONSUMER_HANDLERS: dict[str, MessageHandler] = {INVOICES_TOPIC: handle_invoice_message}


def create_consumer(on_cycle: Callable[[], None] | None = None) -> KafkaMessageConsumer:
    """The consumer of CONSUMER_HANDLERS. Its dead letters, like the relay,
    are written as faclab_worker: they belong to every tenant"""
    return KafkaMessageConsumer(
        config.KAFKA_BOOTSTRAP_SERVERS,
        config.KAFKA_CONSUMER_GROUP_ID,
        CONSUMER_HANDLERS,
        dead_letters=DeadLetterStore(worker_session_maker()),
        max_attempts=config.KAFKA_CONSUMER_MAX_ATTEMPTS,
        retry_base_delay=config.KAFKA_CONSUMER_RETRY_BASE_SECONDS,
        on_cycle=on_cycle,
    )


class Messaging:
    """Started in order and stopped in reverse: the consumer first, so it
    doesn't take messages while the rest stops; the producer last, after the
    relay's last batch."""

    def __init__(
        self,
        producer: KafkaEventProducer,
        relay: OutboxRelay,
        consumer: KafkaMessageConsumer,
    ):
        self.producer = producer
        self.relay = relay
        self.consumer = consumer

    def start(self) -> None:
        self.producer.start()
        outbox_relay.start(self.relay)
        self.consumer.start()

    def stop(self) -> None:
        self.consumer.stop()
        outbox_relay.stop()
        self.producer.close()


def create_messaging(
    on_relay_cycle: Callable[[], None] | None = None,
    on_consumer_cycle: Callable[[], None] | None = None,
) -> Messaging:
    producer = KafkaEventProducer(config.KAFKA_BOOTSTRAP_SERVERS)
    # Reads every tenant's messages: faclab_worker, not the API's role
    relay = OutboxRelay(
        worker_session_maker(),
        producer,
        poll_interval=config.OUTBOX_POLL_INTERVAL_SECONDS,
        max_attempts=config.OUTBOX_MAX_ATTEMPTS,
        retry_base_seconds=config.OUTBOX_RETRY_BASE_SECONDS,
        retry_max_seconds=config.OUTBOX_RETRY_MAX_SECONDS,
        on_cycle=on_relay_cycle,
    )
    return Messaging(producer, relay, create_consumer(on_cycle=on_consumer_cycle))
