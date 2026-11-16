"""Lectura y escritura de las hojas de la importación (S5.8): CSV y XLSX.

Se leen en streaming desde el archivo subido (en disco si es grande): el CSV
con `csv.reader`, el XLSX con openpyxl en modo `read_only`. Cada celda llega
como texto o None, sin espacios en los bordes; un número de Excel entero llega
sin ".0" (un código de barras numérico) y un booleano como SI/NO.
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

Row = tuple[int, list[str | None]]


@dataclass
class Table:
    header: list[str | None]
    rows: Iterator[Row]


def read_table(file: IO[bytes], file_name: str) -> Table:
    """La primera hoja del archivo: su encabezado y las filas siguientes, cada
    una con su número de línea (el encabezado es la 1)"""
    file.seek(0)
    start = file.read(len(_ZIP_SIGNATURE))
    file.seek(0)
    name = file_name.lower()
    if start == _OLE_SIGNATURE or name.endswith(".xls"):
        raise ImportFileInvalidError(
            "Los archivos .xls no se admiten: guárdelo como .xlsx o .csv"
        )
    if start == _ZIP_SIGNATURE:
        return _read_xlsx(file)
    if name.endswith((".xlsx", ".xlsm")):
        raise ImportFileInvalidError("No es un archivo de Excel válido")
    return _read_csv(file)


def _read_csv(file: IO[bytes]) -> Table:
    encoding = _encoding(file)
    text = io.TextIOWrapper(file, encoding=encoding, newline="")
    first = text.readline()
    if not first.strip():
        raise ImportFileInvalidError("El archivo está vacío")
    delimiter = max(_DELIMITERS, key=first.count)
    header = next(csv.reader([first], delimiter=delimiter))
    reader = csv.reader(text, delimiter=delimiter)

    def rows() -> Iterator[Row]:
        try:
            for line, cells in enumerate(reader, start=2):
                yield line, [_text(cell) for cell in cells]
        except csv.Error as exc:
            raise ImportFileInvalidError(
                f"El CSV está mal formado cerca de la línea {reader.line_num}: {exc}"
            ) from exc

    return Table([_text(cell) for cell in header], rows())


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


def _read_xlsx(file: IO[bytes]) -> Table:
    try:
        workbook = load_workbook(file, read_only=True, data_only=True)
    except (
        InvalidFileException,
        zipfile.BadZipFile,
        KeyError,
        ValueError,
        OSError,
    ) as exc:
        raise ImportFileInvalidError("No es un archivo de Excel válido") from exc
    if not workbook.worksheets:
        raise ImportFileInvalidError("El archivo está vacío")
    sheet = workbook.worksheets[0]
    values = sheet.iter_rows(values_only=True)
    header = next(values, None)
    if header is None or all(cell is None for cell in header):
        workbook.close()
        raise ImportFileInvalidError("El archivo está vacío")

    def rows() -> Iterator[Row]:
        try:
            for line, cells in enumerate(values, start=2):
                yield line, [_cell(cell) for cell in cells]
        finally:
            workbook.close()

    return Table([_cell(cell) for cell in header], rows())


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
