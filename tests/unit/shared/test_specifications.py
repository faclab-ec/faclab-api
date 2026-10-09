from typing import Any

from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import DeclarativeBase

from src.shared.domain.specifications import Specification, all_of, contains_pattern


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
