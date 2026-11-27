"""Lectura y escritura de las hojas de la importación (S5.8): CSV y XLSX.

Se leen en streaming desde el archivo subido (en disco si es grande): el CSV
con `csv.reader`, el XLSX con openpyxl en modo `read_only`. Cada celda llega
como texto o None, sin espacios en los bordes; un número de Excel entero llega
sin ".0" (un código de barras numérico) y un booleano como SI/NO.

Un archivo pequeño no puede ocupar la CPU ni la memoria del API (S9.3): el XLSX
se descomprime hasta `MAX_UNCOMPRESSED_BYTES` y su hoja se recorre una vez sin
cargarla para cortar filas de más de `MAX_COLUMNS` celdas y números de fila
mayores al tope; openpyxl ignora la dimensión que declara el archivo (con
`A1:XFD1048576` rellenaba cada hueco con 16.384 celdas vacías). Las filas
vacías cuentan para el tope de líneas, en CSV y en XLSX.
"""

import codecs
import csv
import io
import zipfile
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import IO, Any
from xml.etree.ElementTree import ParseError, iterparse

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font
from openpyxl.utils.exceptions import InvalidFileException

from src.imports.domain.exceptions import ImportFileInvalidError

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CSV_MEDIA_TYPE = "text/csv; charset=utf-8"

_ZIP_SIGNATURE = b"PK\x03\x04"
_OLE_SIGNATURE = b"\xd0\xcf\x11\xe0"  # .xls (Excel 97-2003)
_CHUNK = 64 * 1024
_DELIMITERS = (",", ";", "\t")

# Ninguna plantilla pasa de 20 columnas; el resto del ancho es basura
MAX_COLUMNS = 200
# Un XLSX legítimo de 50.000 filas y 15 columnas ocupa unos 36 MiB sin comprimir
MAX_UNCOMPRESSED_BYTES = 64 * 1_048_576
_MAX_SHARED_STRINGS_BYTES = 16 * 1_048_576
_MAX_ARCHIVE_ENTRIES = 1_000
# A cell is <c> with <v>, <f> or <is><t>: a few elements each
_ELEMENTS_PER_CELL = 4
_MAX_ROW_ELEMENTS = MAX_COLUMNS * _ELEMENTS_PER_CELL
# Column widths, merged cells, conditional formats... outside the rows
_MAX_OTHER_ELEMENTS = 100_000

Row = tuple[int, list[str | None]]


@dataclass
class Table:
    header: list[str | None]
    rows: Iterator[Row]


def read_table(file: IO[bytes], file_name: str, max_lines: int) -> Table:
    """La primera hoja del archivo: su encabezado y las filas siguientes, cada
    una con su número de línea (el encabezado es la 1). Una línea después de
    `max_lines`, vacía o no, es `IMPORT_FILE_INVALID`"""
    file.seek(0)
    start = file.read(len(_ZIP_SIGNATURE))
    file.seek(0)
    name = file_name.lower()
    if start == _OLE_SIGNATURE or name.endswith(".xls"):
        raise ImportFileInvalidError(
            "Los archivos .xls no se admiten: guárdelo como .xlsx o .csv"
        )
    if start == _ZIP_SIGNATURE:
        return _read_xlsx(file, max_lines)
    if name.endswith((".xlsx", ".xlsm")):
        raise ImportFileInvalidError("No es un archivo de Excel válido")
    return _read_csv(file, max_lines)


def _too_many_lines(max_lines: int) -> ImportFileInvalidError:
    return ImportFileInvalidError(
        f"El archivo tiene más de {max_lines} líneas, contando las vacías: "
        "borre las filas vacías del final o divídalo",
        detail=f"max_lines={max_lines}",
    )


def _too_wide(columns: int) -> ImportFileInvalidError:
    return ImportFileInvalidError(
        f"El archivo tiene filas de más de {MAX_COLUMNS} columnas: "
        "borre las columnas que sobran",
        detail=f"columns={columns}",
    )


def _header(cells: Sequence[str | None]) -> list[str | None]:
    """El encabezado sin las celdas vacías del final"""
    header = list(cells)
    while header and header[-1] is None:
        header.pop()
    if len(header) > MAX_COLUMNS:
        raise _too_wide(len(header))
    return header


def _read_csv(file: IO[bytes], max_lines: int) -> Table:
    encoding = _encoding(file)
    text = io.TextIOWrapper(file, encoding=encoding, newline="")
    first = text.readline()
    if not first.strip():
        raise ImportFileInvalidError("El archivo está vacío")
    delimiter = max(_DELIMITERS, key=first.count)
    header = _header(
        [_text(cell) for cell in next(csv.reader([first], delimiter=delimiter))]
    )
    reader = csv.reader(text, delimiter=delimiter)

    def rows() -> Iterator[Row]:
        try:
            for line, cells in enumerate(reader, start=2):
                if line > max_lines:
                    raise _too_many_lines(max_lines)
                yield line, [_text(cell) for cell in cells[: len(header)]]
        except csv.Error as exc:
            raise ImportFileInvalidError(
                f"El CSV está mal formado cerca de la línea {reader.line_num}: {exc}"
            ) from exc

    return Table(header, rows())


def _encoding(file: IO[bytes]) -> str:
    """UTF-8 (con o sin BOM, como lo guarda Excel en "CSV UTF-8") o, si no lo
    es, Windows-1252 (el "CSV" de Excel en español)"""
    decoder = codecs.getincrementaldecoder("utf-8")()
    file.seek(0)
    try:
        while chunk := file.read(_CHUNK):
            decoder.decode(chunk)
        decoder.decode(b"", final=True)
        encoding = "utf-8-sig"
    except UnicodeDecodeError:
        encoding = "cp1252"
    file.seek(0)
    return encoding


_NOT_EXCEL = (
    InvalidFileException,
    zipfile.BadZipFile,
    KeyError,
    ValueError,
    OSError,
    ParseError,
)


def _read_xlsx(file: IO[bytes], max_lines: int) -> Table:
    try:
        _check_archive(file)
        workbook = load_workbook(file, read_only=True, data_only=True)
    except _NOT_EXCEL as exc:
        raise ImportFileInvalidError("No es un archivo de Excel válido") from exc
    if not workbook.worksheets:
        workbook.close()
        raise ImportFileInvalidError("El archivo está vacío")
    sheet = workbook.worksheets[0]
    try:
        _check_sheet(sheet, max_lines)
        # The dimension the file declares is not trusted
        sheet.reset_dimensions()  # type: ignore[union-attr]
        first = next(sheet.iter_rows(max_row=1, values_only=True), None)
        header = _header([_cell(cell) for cell in first or ()])
    except _NOT_EXCEL as exc:
        workbook.close()
        raise ImportFileInvalidError("No es un archivo de Excel válido") from exc
    except ImportFileInvalidError:
        workbook.close()
        raise
    if not header:
        workbook.close()
        raise ImportFileInvalidError("El archivo está vacío")
    values = sheet.iter_rows(min_row=2, max_col=len(header), values_only=True)

    def rows() -> Iterator[Row]:
        try:
            for line, cells in enumerate(values, start=2):
                if line > max_lines:
                    raise _too_many_lines(max_lines)
                yield line, [_cell(cell) for cell in cells]
        finally:
            workbook.close()

    return Table(header, rows())


def _check_archive(file: IO[bytes]) -> None:
    """Lo que el ZIP dice que ocupa sin comprimir; `zipfile` no descomprime una
    entrada más allá de lo que declara (falla con BadZipFile)"""
    file.seek(0)
    with zipfile.ZipFile(file) as archive:
        entries = archive.infolist()
    file.seek(0)
    size = sum(entry.file_size for entry in entries)
    strings = sum(
        entry.file_size
        for entry in entries
        if entry.filename.lower().endswith("sharedstrings.xml")
    )
    if (
        len(entries) > _MAX_ARCHIVE_ENTRIES
        or size > MAX_UNCOMPRESSED_BYTES
        or strings > _MAX_SHARED_STRINGS_BYTES
    ):
        raise ImportFileInvalidError(
            "El archivo de Excel ocupa demasiado sin comprimir: "
            "guárdelo de nuevo solo con la hoja de la plantilla o divídalo",
            detail=f"entries={len(entries)},uncompressed={size},strings={strings}",
        )


def _check_sheet(sheet: Any, max_lines: int) -> None:
    """Recorre la hoja sin cargarla y corta lo que openpyxl no acota: arma
    cada fila completa en memoria (una fila de millones de celdas), rellena con
    filas vacías hasta el número de fila que diga el archivo y guarda hasta el
    final los elementos fuera de las filas que no conoce"""
    stack: list[Any] = []
    rows = outside = in_row = cells = 0
    row_depth: int | None = None
    with sheet._get_source() as source:
        for event, element in iterparse(source, events=("start", "end")):
            if event == "start":
                tag = element.tag.rsplit("}", 1)[-1]
                if tag == "row" and row_depth is None:
                    rows += 1
                    number = element.get("r") or "0"
                    if rows > max_lines or (
                        number.isdigit() and int(number) > max_lines
                    ):
                        raise _too_many_lines(max_lines)
                    row_depth, in_row, cells = len(stack), 0, 0
                elif row_depth is not None:
                    in_row += 1
                    cells += tag == "c"
                    if cells > MAX_COLUMNS or in_row > _MAX_ROW_ELEMENTS:
                        raise _too_wide(max(cells, in_row // _ELEMENTS_PER_CELL))
                else:
                    outside += 1
                    if outside > _MAX_OTHER_ELEMENTS:
                        raise ImportFileInvalidError(
                            "No es un archivo de Excel válido",
                            detail=f"elements>{_MAX_OTHER_ELEMENTS}",
                        )
                stack.append(element)
                continue
            stack.pop()
            if stack:
                # Nothing read is kept: the parser's tree stays one path deep
                stack[-1].remove(element)
            if row_depth == len(stack):
                row_depth = None


def _text(value: str) -> str | None:
    value = value.strip()
    return value or None


def _cell(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "SI" if value else "NO"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return str(value)
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime | date):
        return value.isoformat()
    return _text(str(value))


# -- writing ----------------------------------------------------------------


def write_csv(header: Sequence[str], rows: Sequence[Sequence[Any]]) -> bytes:
    """UTF-8 con BOM, para que Excel lo abra con tildes"""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows([_out(value) for value in row] for row in rows)
    return buffer.getvalue().encode("utf-8-sig")


def write_xlsx(
    header: Sequence[str],
    rows: Sequence[Sequence[Any]],
    title: str,
    notes: Sequence[Sequence[Any]] | None = None,
) -> bytes:
    """Una hoja con el encabezado en negrita y, en `notes`, una segunda hoja
    "Instrucciones". Las columnas van como texto, para que Excel no quite los
    ceros iniciales de una cédula o un código de barras"""
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = title[:31]
    sheet.append(list(header))
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for index, name in enumerate(header, start=1):
        letter = sheet.cell(row=1, column=index).column_letter
        sheet.column_dimensions[letter].width = max(12, len(str(name)) + 4)
        sheet.column_dimensions[letter].number_format = "@"
    for row in rows:
        sheet.append([_out(value) for value in row])
    if notes:
        instructions = workbook.create_sheet("Instrucciones")
        for line in notes:
            instructions.append(list(line))
        for cell in instructions[1]:
            cell.font = Font(bold=True)
        instructions.column_dimensions["A"].width = 24
        instructions.column_dimensions["C"].width = 90
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _out(value: Any) -> Any:
    return "" if value is None else value
