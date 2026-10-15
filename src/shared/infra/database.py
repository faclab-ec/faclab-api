from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from wireup import injectable

from src.shared.domain.exceptions import BaseError


class Base(DeclarativeBase):
    pass


def create_session_maker(connection_string: str) -> sessionmaker[Session]:
    if not connection_string:
        raise ValueError("Database connection string cannot be empty")

    engine = create_engine(connection_string)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def create_session_factory(connection_string: str):
    _factory = create_session_maker(connection_string)

    @injectable(lifetime="scoped")
    def get_db_session() -> Iterator[Session]:
        session = _factory()
        try:
            yield session
            session.commit()
        except Exception as exc:
            if isinstance(exc, BaseError) and exc.commit_transaction:
                session.commit()
            else:
                session.rollback()
            raise
        finally:
            session.close()

    return get_db_session
