"""Platform commands for the messages that got stuck: the outbox messages that
are `failed` and the consumer's dead letters. They run as faclab_worker over
every tenant; the HTTP console arrives with the platform role (S8.5).

Every change records who made it (`--by`, required) on the row and in the log.

Usage:
    python -m src.background.cli outbox-failed [--limit N]
    python -m src.background.cli outbox-retry (ID ... | --all) --by NAME
    python -m src.background.cli dead-letters [--limit N]
    python -m src.background.cli dead-letter-reprocess ID --by NAME
"""

import argparse
import sys

from config import config
from src.shared.infra.database import worker_session_maker
from src.shared.infra.kafka import dead_letters
from src.shared.infra.logging import configure_logging
from src.shared.infra.outbox import admin as outbox_admin


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m src.background.cli")
    commands = parser.add_subparsers(dest="command", required=True)

    failed = commands.add_parser("outbox-failed", help="List the failed messages")
    failed.add_argument("--limit", type=int, default=100)

    retry = commands.add_parser(
        "outbox-retry", help="Put failed messages back in the queue"
    )
    retry.add_argument("ids", type=int, nargs="*")
    retry.add_argument("--all", action="store_true", help="Every failed message")
    retry.add_argument("--by", required=True, help="Who retries them (audit)")

    letters = commands.add_parser("dead-letters", help="List the pending dead letters")
    letters.add_argument("--limit", type=int, default=100)

    reprocess = commands.add_parser(
        "dead-letter-reprocess", help="Process a dead letter again"
    )
    reprocess.add_argument("id", type=int)
    reprocess.add_argument("--by", required=True, help="Who reprocesses it (audit)")
    return parser


def _outbox_failed(limit: int) -> int:
    messages = outbox_admin.list_failed(worker_session_maker(), limit)
    for m in messages:
        print(
            f"{m.id}\t{m.tenant_id}\t{m.topic}\t{m.event_type}\t"
            f"attempts={m.attempts}\t{m.created_at:%Y-%m-%d %H:%M:%S}\t{m.last_error}"
        )
    print(f"{len(messages)} failed message(s)")
    return 0


def _outbox_retry(ids: list[int], every: bool, by: str) -> int:
    if every == bool(ids):
        print("Give the ids to retry or --all, not both", file=sys.stderr)
        return 2
    retried = outbox_admin.retry_failed(
        worker_session_maker(), None if every else ids, by
    )
    print(f"{len(retried)} message(s) back in the queue: {retried}")
    skipped = sorted(set(ids) - set(retried))
    if skipped:
        print(f"Not failed, left as they are: {skipped}", file=sys.stderr)
    return 0


def _dead_letters(limit: int) -> int:
    letters = dead_letters.list_pending(worker_session_maker(), limit)
    for d in letters:
        print(
            f"{d.id}\t{d.tenant_id}\t{d.topic}[{d.kafka_partition}]@{d.kafka_offset}\t"
            f"attempts={d.attempts}\t{d.created_at:%Y-%m-%d %H:%M:%S}\t{d.error}"
        )
    print(f"{len(letters)} pending dead letter(s)")
    return 0


def _dead_letter_reprocess(letter_id: int, by: str) -> int:
    import src
    from src.background.messaging import create_consumer
    from src.container import create_wireup_container

    # The topic's handler opens its scope from the container, as in the worker
    src.wireup_container = create_wireup_container()
    letter = dead_letters.reprocess(
        worker_session_maker(), letter_id, by, create_consumer().dispatch
    )
    if letter is None:
        print(f"No pending dead letter {letter_id}", file=sys.stderr)
        return 1
    if letter.status != "reprocessed":
        print(f"Dead letter {letter_id} failed again: {letter.error}", file=sys.stderr)
        return 1
    print(f"Dead letter {letter_id} reprocessed")
    return 0


def main(argv: list[str] | None = None) -> int:
    configure_logging(log_level=config.LOG_LEVEL)
    args = _parser().parse_args(argv)
    if args.command == "outbox-failed":
        return _outbox_failed(args.limit)
    if args.command == "outbox-retry":
        return _outbox_retry(args.ids, args.all, args.by)
    if args.command == "dead-letters":
        return _dead_letters(args.limit)
    return _dead_letter_reprocess(args.id, args.by)


if __name__ == "__main__":
    sys.exit(main())
