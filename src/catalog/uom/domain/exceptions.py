from src.shared.domain.exceptions import AlreadyExistsError


class UnitOfMeasureSymbolAlreadyExistsError(AlreadyExistsError):
    error_code = "UNIT_OF_MEASURE_SYMBOL_ALREADY_EXISTS"

    def __init__(self):
        super().__init__("A unit of measure with this symbol already exists")
