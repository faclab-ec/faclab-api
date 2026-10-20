from dataclasses import dataclass

from wireup import injectable

from src.pos.terminal.app.resolver import TerminalRequest, TerminalResolver
from src.sales.app.repositories import SaleRepository
from src.sales.domain.specifications import ParkedSalesSpecification, SalesByTerminal
from src.shared.app.queries import Query, QueryHandler


@dataclass
class GetParkedSalesQuery(Query):
    """Query para obtener las ventas aparcadas de la terminal"""

    terminal: TerminalRequest


@injectable(lifetime="scoped")
class GetParkedSalesQueryHandler(QueryHandler[GetParkedSalesQuery, list[dict]]):
    def __init__(self, repo: SaleRepository, terminals: TerminalResolver):
        self.repo = repo
        self.terminals = terminals

    def _handle(self, query: GetParkedSalesQuery) -> list[dict]:
        terminal = self.terminals.terminal(query.terminal)
        spec = ParkedSalesSpecification() & SalesByTerminal(terminal.require_id())
        sales = self.repo.filter_by_spec(spec)
        return [sale.dict() for sale in sales]
