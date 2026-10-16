"""A tenant-scoped table that only exists in tests, to prove the base repository
before S2.3 marks the real modules. It has its own metadata: it never reaches
`Base.metadata`, the migrations or the Postgres tests' TRUNCATE."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import String, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from src.shared.domain.entities import Entity
from src.shared.domain.specifications import Specification
from src.shared.infra.mappers import Mapper
from src.shared.infra.repositories import SqlAlchemyRepository


class ScratchBase(DeclarativeBase):
    pass


class NoteModel(ScratchBase):
    __tablename__ = "tenant_scoped_notes"
    __tenant_scoped__ = True

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    title: Mapped[str] = mapped_column(String(64), nullable=False)


class GlobalNoteModel(ScratchBase):
    """The same table without the mark: the base repository ignores tenants"""

    __tablename__ = "global_notes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[UUID | None] = mapped_column(Uuid)
    title: Mapped[str] = mapped_column(String(64), nullable=False)


@dataclass
class Note(Entity):
    """An entity that knows nothing about tenants, like most will"""

    title: str = ""
    id: int | None = None


@dataclass
class TaggedNote(Entity):
    """An entity that carries its tenant"""

    title: str = ""
    tenant_id: UUID | None = None
    id: int | None = None


class NoteMapper(Mapper[Note, NoteModel]):
    __entity__ = Note


class TaggedNoteMapper(Mapper[TaggedNote, NoteModel]):
    __entity__ = TaggedNote


class NoteRepository(SqlAlchemyRepository[Note]):
    __model__ = NoteModel


class TaggedNoteRepository(SqlAlchemyRepository[TaggedNote]):
    __model__ = NoteModel


class GlobalNoteRepository(SqlAlchemyRepository[TaggedNote]):
    __model__ = GlobalNoteModel


class TitleIs(Specification):
    def __init__(self, title: str):
        self.title = title

    def is_satisfied_by(self, candidate: Any) -> bool:
        return candidate.title == self.title

    def to_query_criteria(self) -> list[Any]:
        return [NoteModel.title == self.title]
