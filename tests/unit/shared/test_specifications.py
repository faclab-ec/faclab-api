from typing import Any

from sqlalchemy import Column, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Session

from src.shared.domain.specifications import (
    MatchAll,
    Specification,
    all_of,
    contains_pattern,
)


class SpecBase(DeclarativeBase):
    pass


class UserModel(SpecBase):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    age = Column(Integer)
    name = Column(String)
    active = Column(Integer)


class IsAdult(Specification):
    def is_satisfied_by(self, candidate: Any) -> bool:
        return candidate.get("age", 0) >= 18

    def to_query_criteria(self) -> list[Any]:
        return [UserModel.age >= 18]


class IsActive(Specification):
    def is_satisfied_by(self, candidate: Any) -> bool:
        return candidate.get("active", False)

    def to_query_criteria(self) -> list[Any]:
        return [UserModel.active == 1]


class IsYoung(Specification):
    def is_satisfied_by(self, candidate: Any) -> bool:
        return candidate.get("age", 0) < 30

    def to_query_criteria(self) -> list[Any]:
        return [UserModel.age < 30]


class IsNamed(Specification):
    def __init__(self, name: str):
        self.name = name

    def is_satisfied_by(self, candidate: Any) -> bool:
        return candidate.get("name") == self.name

    def to_query_criteria(self) -> list[Any]:
        return [UserModel.name == self.name]


def test_specification_is_satisfied():
    spec = IsAdult()
    assert spec.is_satisfied_by({"age": 20}) is True
    assert spec.is_satisfied_by({"age": 15}) is False


def test_and_composition():
    spec = IsAdult() & IsActive()
    assert spec.is_satisfied_by({"age": 20, "active": True}) is True
    assert spec.is_satisfied_by({"age": 20, "active": False}) is False
    assert spec.is_satisfied_by({"age": 15, "active": True}) is False


def test_or_composition():
    spec = IsAdult() | IsActive()
    assert spec.is_satisfied_by({"age": 20, "active": False}) is True
    assert spec.is_satisfied_by({"age": 15, "active": True}) is True
    assert spec.is_satisfied_by({"age": 15, "active": False}) is False


def test_not_invert():
    spec = ~IsAdult()
    assert spec.is_satisfied_by({"age": 20}) is False
    assert spec.is_satisfied_by({"age": 15}) is True


def test_to_query_criteria_and():
    spec = IsAdult() & IsActive()
    criteria = spec.to_query_criteria()
    assert len(criteria) == 2


def test_to_query_criteria_or():
    spec = IsAdult() | IsActive()
    criteria = spec.to_query_criteria()
    assert len(criteria) == 1


def test_or_keeps_the_criteria_of_each_side_together():
    spec = (IsAdult() & IsActive()) | (IsYoung() & IsNamed("Ana"))

    [criterion] = spec.to_query_criteria()

    sql = str(criterion.compile(compile_kwargs={"literal_binds": True}))
    assert sql == (
        "users.age >= 18 AND users.active = 1 OR users.age < 30 AND users.name = 'Ana'"
    )


def test_or_query_matches_what_is_satisfied_by_accepts():
    rows = [
        {"id": 1, "age": 20, "active": 1, "name": "Bob"},  # left side
        {"id": 2, "age": 15, "active": 0, "name": "Ana"},  # right side
        {"id": 3, "age": 40, "active": 0, "name": "Bob"},  # adult only
        {"id": 4, "age": 15, "active": 1, "name": "Bob"},  # young and active only
    ]
    spec = (IsAdult() & IsActive()) | (IsYoung() & IsNamed("Ana"))
    engine = create_engine("sqlite://")
    SpecBase.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(UserModel(**row) for row in rows)
        session.flush()

        found = session.query(UserModel.id).filter(*spec.to_query_criteria()).all()

    assert sorted(id for (id,) in found) == [1, 2]
    assert [row["id"] for row in rows if spec.is_satisfied_by(row)] == [1, 2]


def test_or_with_a_side_that_matches_everything_matches_everything():
    assert (MatchAll() | IsAdult()).to_query_criteria() == []
    assert (IsAdult() | all_of([])).to_query_criteria() == []


def test_to_query_criteria_not():
    spec = ~IsAdult()
    criteria = spec.to_query_criteria()
    assert len(criteria) == 1


def test_all_of_without_specs_matches_everything():
    spec = all_of([])
    assert spec.is_satisfied_by({"age": 1}) is True
    assert spec.to_query_criteria() == []


def test_all_of_combines_with_and():
    spec = all_of([IsAdult(), IsActive()])
    assert spec.is_satisfied_by({"age": 20, "active": True}) is True
    assert spec.is_satisfied_by({"age": 20, "active": False}) is False
    assert len(spec.to_query_criteria()) == 2


def test_contains_pattern_escapes_wildcards():
    assert contains_pattern("50%_off\\") == "%50\\%\\_off\\\\%"
