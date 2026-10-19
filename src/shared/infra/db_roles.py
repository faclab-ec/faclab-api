"""Database roles for row-level security (S2.4). Idempotent.

Usage:
    python -m src.shared.infra.db_roles

Each URL names a role and its password: `DATABASE_URL` → `faclab_app` (the API,
under row-level security), `DATABASE_URL_WORKER` → `faclab_worker` (BYPASSRLS:
the outbox relay and platform lookups) and `DATABASE_URL_MIGRATIONS` →
`faclab_owner` (owns the tables and runs the migrations). With the superuser of
`DATABASE_URL_ADMIN` it creates or updates the three roles, creates the database
owned by `faclab_owner` and hands it any table, sequence or type of `public` that
another role owns (a database migrated before S2.4). Table privileges and the
policies come with the migrations. Passwords go to the server already hashed and
never reach the logs.
"""

import sys
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import structlog
from environs import Env, EnvError
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

logger = structlog.get_logger(__name__)

OWNER = "faclab_owner"
APP = "faclab_app"
WORKER = "faclab_worker"

_COMMON = "LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION"
ATTRIBUTES = {
    OWNER: f"{_COMMON} NOBYPASSRLS",
    APP: f"{_COMMON} NOBYPASSRLS",
    WORKER: f"{_COMMON} BYPASSRLS",
}


class RoleConfigError(ValueError):
    """The role URLs don't describe the three roles of one database"""


@dataclass(frozen=True)
class RoleUrls:
    """The superuser's URL and one URL per role; `URL` masks the passwords in
    its repr, so a traceback never shows them"""

    admin: URL
    owner: URL
    app: URL
    worker: URL

    @classmethod
    def parse(cls, admin: str, owner: str, app: str, worker: str) -> "RoleUrls":
        urls = cls(
            admin=_parse("the admin URL", admin),
            owner=_parse(f"the URL for {OWNER}", owner),
            app=_parse(f"the URL for {APP}", app),
            worker=_parse(f"the URL for {WORKER}", worker),
        )
        urls.validate()
        return urls

    @property
    def database(self) -> str:
        return self.owner.database or ""

    def roles(self) -> dict[str, URL]:
        return {OWNER: self.owner, APP: self.app, WORKER: self.worker}

    def validate(self) -> None:
        for role, url in self.roles().items():
            if url.username != role:
                raise RoleConfigError(f"the URL for {role} connects as another user")
            if not url.password:
                raise RoleConfigError(f"the URL for {role} has no password")
        places = {(url.host, url.port, url.database) for url in self.roles().values()}
        if len(places) != 1:
            raise RoleConfigError("the role URLs point to different databases")
        if not self.database:
            raise RoleConfigError("the role URLs name no database")
        if self.admin.host != self.owner.host or self.admin.port != self.owner.port:
            raise RoleConfigError("the admin URL points to another server")


def _parse(name: str, url: str) -> URL:
    # SQLAlchemy's message repeats the string, password included
    try:
        return make_url(url)
    except ArgumentError:
        raise RoleConfigError(f"{name} is not a database URL") from None


def _dsn(url: URL, database: str) -> str:
    """libpq connection string (psycopg2 doesn't take SQLAlchemy's driver name)"""
    plain = url.set(drivername="postgresql", database=database)
    return plain.render_as_string(hide_password=False)


@contextmanager
def _connect(url: URL, database: str) -> Generator[Any]:
    import psycopg2

    connection = psycopg2.connect(_dsn(url, database))
    connection.autocommit = True
    try:
        yield connection
    finally:
        connection.close()


def _ensure_role(cursor: Any, connection: Any, role: str, password: str) -> bool:
    from psycopg2 import sql
    from psycopg2.extensions import encrypt_password

    cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
    created = cursor.fetchone() is None
    verifier = encrypt_password(password, role, connection, "scram-sha-256")
    statement = (
        "CREATE ROLE {} {} PASSWORD {}" if created else "ALTER ROLE {} {} PASSWORD {}"
    )
    cursor.execute(
        sql.SQL(statement).format(
            sql.Identifier(role), sql.SQL(ATTRIBUTES[role]), sql.Literal(verifier)
        )
    )
    return created


def _ensure_database(cursor: Any, database: str) -> bool:
    from psycopg2 import sql

    cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database,))
    created = cursor.fetchone() is None
    statement = (
        "CREATE DATABASE {} OWNER {}" if created else "ALTER DATABASE {} OWNER TO {}"
    )
    cursor.execute(
        sql.SQL(statement).format(sql.Identifier(database), sql.Identifier(OWNER))
    )
    cursor.execute(
        sql.SQL("GRANT CONNECT ON DATABASE {} TO {}, {}").format(
            sql.Identifier(database), sql.Identifier(APP), sql.Identifier(WORKER)
        )
    )
    return created


# Objects of `public` owned by another role: tables (their serial sequences
# follow them), sequences of no table and types that aren't a table's row type
_FOREIGN_OBJECTS = """
SELECT 'TABLE', c.relname FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
   AND pg_get_userbyid(c.relowner) <> %(owner)s
UNION ALL
SELECT 'SEQUENCE', c.relname FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'public' AND c.relkind = 'S'
   AND pg_get_userbyid(c.relowner) <> %(owner)s
   AND NOT EXISTS (
       SELECT 1 FROM pg_depend d
        WHERE d.objid = c.oid AND d.classid = 'pg_class'::regclass
          AND d.deptype IN ('a', 'i'))
UNION ALL
SELECT 'TYPE', t.typname FROM pg_type t
  JOIN pg_namespace n ON n.oid = t.typnamespace
 WHERE n.nspname = 'public' AND t.typtype IN ('e', 'd', 'c')
   AND (t.typrelid = 0 OR t.typtype <> 'c')
   AND pg_get_userbyid(t.typowner) <> %(owner)s
"""


def _adopt_objects(cursor: Any) -> int:
    from psycopg2 import sql

    cursor.execute(_FOREIGN_OBJECTS, {"owner": OWNER})
    objects = cursor.fetchall()
    for kind, name in objects:
        cursor.execute(
            sql.SQL("ALTER {} {} OWNER TO {}").format(
                sql.SQL(kind), sql.Identifier("public", name), sql.Identifier(OWNER)
            )
        )
    return len(objects)


def bootstrap(urls: RoleUrls) -> None:
    """Creates or updates the roles and the database; safe to repeat"""
    with _connect(urls.admin, "postgres") as connection, connection.cursor() as cursor:
        for role, url in urls.roles().items():
            created = _ensure_role(cursor, connection, role, url.password or "")
            logger.info("db_role_ready", role=role, created=created)
        created = _ensure_database(cursor, urls.database)
        logger.info(
            "db_database_ready", database=urls.database, owner=OWNER, created=created
        )

    with (
        _connect(urls.admin, urls.database) as connection,
        connection.cursor() as cursor,
    ):
        adopted = _adopt_objects(cursor)
        if adopted:
            logger.info(
                "db_objects_adopted", database=urls.database, owner=OWNER, count=adopted
            )


def main() -> int:
    env = Env()
    env.read_env()
    try:
        urls = RoleUrls.parse(
            admin=env.str("DATABASE_URL_ADMIN"),
            owner=env.str("DATABASE_URL_MIGRATIONS"),
            app=env.str("DATABASE_URL"),
            worker=env.str("DATABASE_URL_WORKER"),
        )
    except (EnvError, RoleConfigError) as exc:
        logger.error("db_roles_invalid_config", error=str(exc))
        return 1
    bootstrap(urls)
    return 0


if __name__ == "__main__":
    sys.exit(main())
