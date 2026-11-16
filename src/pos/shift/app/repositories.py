from abc import ABC, abstractmethod
from collections.abc import Iterable

from src.pos.shift.domain.closing import ShiftClosing
from src.pos.shift.domain.entities import Shift
from src.shared.app.repositories import Repository


class ShiftRepository(Repository[Shift]):
    @abstractmethod
    def first_for_update(self, **kwargs) -> Shift | None:
        """The shift, locked FOR UPDATE: closing it waits for every document
        that is writing into it, and they wait for the closing (S5.9)"""
        raise NotImplementedError

    @abstractmethod
    def first_for_share(self, **kwargs) -> Shift | None:
        """The shift, locked FOR SHARE: documents that write into a shift (sales,
        refunds, payments on account, cash movements) don't wait for each other,
        only for its closing. After waiting for a closing, the row is read again:
        a filter by `status="OPEN"` no longer finds it"""
        raise NotImplementedError


class ShiftClosingRepository(ABC):
    """The Z closings (S5.9). They are written once, with the shift's closing, and
    never changed nor deleted: no update or delete here, and the database
    revokes them from the application's roles."""

    @abstractmethod
    def add(self, closing: ShiftClosing) -> ShiftClosing:
        raise NotImplementedError

    @abstractmethod
    def of_shift(self, shift_id: int) -> ShiftClosing | None:
        raise NotImplementedError

    @abstractmethod
    def numbers_of(self, shift_ids: Iterable[int]) -> dict[int, str]:
        """The Z number of each of these shifts that has a closing"""
        raise NotImplementedError

    @abstractmethod
    def next_sequence(self, terminal_id: int | None) -> int:
        """The terminal's next Z correlative. The closings of a terminal never
        run at once (one open shift per terminal, locked while it closes); the
        unique constraint is the last barrier"""
        raise NotImplementedError
