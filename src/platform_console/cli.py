"""Platform operators (S8.5): who may log into the console. The platform's
team is managed here, as faclab_worker, never over HTTP. An operator is an
existing user (a global identity) with a row in `platform_operators`; the user
logs into the console with its own password.

Usage:
    python -m src.platform_console.cli operators
    python -m src.platform_console.cli operator-add --username ana --by NAME
    python -m src.platform_console.cli operator-remove --username ana --by NAME
"""

import argparse
import sys

import structlog
from sqlalchemy import select

from config import config
from src.auth.infra.models import UserModel
from src.platform_console.infra.models import PlatformOperatorModel
from src.shared.infra.database import worker_session_maker
from src.shared.infra.logging import configure_logging

logger = structlog.get_logger(__name__)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.platform_console.cli",
        description="Manage the platform console's operators",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("operators", help="List the operators")
    for name, text in (
        (
            "operator-add",
            "Let an existing user log into the console (or reactivate it)",
        ),
        ("operator-remove", "Take a user's console access away"),
    ):
        command = commands.add_parser(name, help=text)
        command.add_argument("--username", required=True)
        command.add_argument("--by", required=True, help="Who does it (log)")
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_logging(log_level=config.LOG_LEVEL)
    args = _parser().parse_args(argv)
    with worker_session_maker()() as session:
        if args.command == "operators":
            rows = session.execute(
                select(UserModel.username, PlatformOperatorModel.is_active)
                .join(
                    PlatformOperatorModel, PlatformOperatorModel.user_id == UserModel.id
                )
                .order_by(UserModel.username)
            )
            for username, active in rows:
                print(f"{username}\t{'active' if active else 'inactive'}")
            return 0

        user_id = session.scalar(
            select(UserModel.id).where(UserModel.username == args.username)
        )
        if user_id is None:
            print(f"No user '{args.username}'", file=sys.stderr)
            return 1
        operator = session.scalar(
            select(PlatformOperatorModel).where(
                PlatformOperatorModel.user_id == user_id
            )
        )
        if args.command == "operator-add":
            if operator is None:
                session.add(PlatformOperatorModel(user_id=user_id, is_active=True))
            else:
                operator.is_active = True
        elif operator is not None:
            operator.is_active = False
        session.commit()
    logger.info(
        "platform_operator_changed",
        action=args.command,
        username=args.username,
        by=args.by,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
