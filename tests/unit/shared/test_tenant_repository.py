"""The base repository with a tenant-scoped model: it assigns the context's
tenant on create and never reads, updates or deletes another tenant's rows."""

from collections.abc import Iterator
from uuid import UUID

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.shared.domain.exceptions import NotFoundError
from src.shared.domain.tenant import (
    TenantContext,
    TenantContextRequiredError,
    TenantMismatchError,
    TenantSource,
    use_tenant,
)
from tests.tenant_notes import (
    GlobalNoteModel,
    GlobalNoteRepository,
    Note,
    NoteMapper,
    NoteModel,
    NoteRepository,
    ScratchBase,
    TaggedNote,
    TaggedNoteMapper,
    TaggedNoteRepository,
    TitleIs,
)

TENANT_A = UUID("00000000-0000-4000-8000-0000000000a1")
TENANT_B = UUID("00000000-0000-4000-8000-0000000000b2")


def _in(tenant_id: UUID):
    return use_tenant(TenantContext(tenant_id, TenantSource.TASK))


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite://")
    ScratchBase.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    # Ids 1-2 belong to A, 3-4 to B
    db.add_all(
        [
            NoteModel(id=1, tenant_id=TENANT_A, title="shared"),
            NoteModel(id=2, tenant_id=TENANT_A, title="only A"),
            NoteModel(id=3, tenant_id=TENANT_B, title="shared"),
            NoteModel(id=4, tenant_id=TENANT_B, title="only B"),
        ]
    )
    db.commit()
    yield db
    db.close()


@pytest.fixture
def repo(session) -> NoteRepository:
    return NoteRepository(session, NoteMapper())


def test_create_assigns_the_context_tenant(repo, session):
    with _in(TENANT_A):
        note = repo.create(Note(title="new"))

    assert session.get(NoteModel, note.id).tenant_id == TENANT_A


def test_create_without_a_context_fails(repo):
    with pytest.raises(TenantContextRequiredError):
        repo.create(Note(title="new"))


def test_an_entity_never_brings_another_tenant(session):
    repo = TaggedNoteRepository(session, TaggedNoteMapper())

    with _in(TENANT_A):
        with pytest.raises(TenantMismatchError):
            repo.create(TaggedNote(title="new", tenant_id=TENANT_B))
        with pytest.raises(TenantMismatchError):
            repo.update(TaggedNote(id=2, title="moved", tenant_id=TENANT_B))
        own = repo.create(TaggedNote(title="mine", tenant_id=TENANT_A))

    assert own.tenant_id == TENANT_A
    assert session.get(NoteModel, 2).tenant_id == TENANT_A


def test_reads_without_a_context_fail(repo):
    with pytest.raises(TenantContextRequiredError):
        repo.get_by_id(1)
    with pytest.raises(TenantContextRequiredError):
        repo.filter_by(title="shared")


def test_another_tenants_id_is_not_found(repo, session):
    with _in(TENANT_A):
        assert repo.get_by_id(3) is None
        assert repo.get_by_ids([1, 3]) == [Note(id=1, title="shared")]
        assert repo.first(id=3) is None
        assert repo.first_for_update(id=3) is None
        with pytest.raises(NotFoundError):
            repo.update(Note(id=3, title="taken"))
        with pytest.raises(NotFoundError):
            repo.delete(3)

    assert session.get(NoteModel, 3).title == "shared"


def test_lists_and_counts_only_see_the_context_tenant(repo):
    with _in(TENANT_B):
        assert {n.id for n in repo.get_all()} == {3, 4}
        assert [n.id for n in repo.filter_by(title="shared")] == [3]
        assert [n.id for n in repo.filter_by_spec(TitleIs("shared"))] == [3]
        assert repo.count_by(title="shared") == 1
        assert repo.count_by_spec(TitleIs("shared")) == 1
        page = repo.paginate(limit=10, offset=0)

    assert page["total"] == 2
    assert {item["id"] for item in page["items"]} == {3, 4}


def test_update_and_delete_work_inside_the_tenant(repo, session):
    with _in(TENANT_A):
        repo.update(Note(id=2, title="edited"))
        repo.delete(1)
        session.flush()

    assert session.get(NoteModel, 2).title == "edited"
    assert session.get(NoteModel, 2).tenant_id == TENANT_A
    assert session.get(NoteModel, 1) is None


def test_a_model_without_the_mark_ignores_tenants(session):
    session.add_all(
        [
            GlobalNoteModel(id=1, tenant_id=TENANT_A, title="a"),
            GlobalNoteModel(id=2, tenant_id=None, title="b"),
        ]
    )
    session.commit()
    repo = GlobalNoteRepository(session, TaggedNoteMapper())

    with _in(TENANT_B):
        assert repo.get_by_id(1) is not None
        assert repo.count_by() == 2
    created = repo.create(TaggedNote(title="no context"))

    assert created.tenant_id is None
