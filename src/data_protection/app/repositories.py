from abc import abstractmethod

from src.data_protection.domain.entities import ExportJob
from src.shared.app.repositories import Repository


class ExportJobRepository(Repository[ExportJob]):
    @abstractmethod
    def in_progress(self) -> ExportJob | None:
        """La exportación en cola o en curso de la empresa, si hay"""

    @abstractmethod
    def page(self, limit: int, offset: int) -> dict:
        """Las exportaciones, la última primero, con su total"""
