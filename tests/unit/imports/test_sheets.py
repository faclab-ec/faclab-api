"""Reading the uploaded sheets and writing templates and error reports (S5.8)"""

import io
import zipfile
from collections.abc import Callable
from decimal import Decimal

import pytest
from openpyxl import Workbook, load_workbook

from src.imports.app.columns import (
    CellError,
    boolean,
    choice,
    header_name,
    money,
    positive_quantity,
    quantity,
    text,
    whole,
)
from src.imports.domain.exceptions import ImportFileInvalidError
from src.imports.infra.sheets import (
    MAX_COLUMNS,
    MAX_UNCOMPRESSED_BYTES,
    read_table,
    write_csv,
    write_xlsx,
)
from src.shared.domain.tax import TaxCode

MAX_LINES = 100


def _rows(table) -> list:
    return list(table.rows)


def _xlsx(*rows: list) -> io.BytesIO:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer


# -- cells -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("Precio venta", "precio_venta"),
        ("  Descripción ", "descripcion"),
        ("CODIGO-BARRAS", "codigo_barras"),
        ("Tipo  Identificación", "tipo_identificacion"),
    ],
)
def test_a_header_is_compared_without_accents_case_or_spaces(written, expected):
    assert header_name(written) == expected


@pytest.mark.parametrize(
    ("written", "expected"),
    [("12.50", "12.50"), ("12,50", "12.50"), ("0", "0"), ("1 200", "1200")],
)
def test_money_takes_a_point_or_a_comma_as_the_decimal_separator(written, expected):
    assert money(written) == Decimal(expected)


@pytest.mark.parametrize(
    "written", ["1.234,50", "1,234.50", "doce", "-1", "0.1234567", "NaN", "1e20"]
)
def test_money_rejects_what_is_not_an_amount(written):
    with pytest.raises(CellError):
        money(written)


def test_quantities_whole_numbers_and_booleans():
    assert quantity("2,5") == Decimal("2.5")
    with pytest.raises(CellError, match="mayor que cero"):
        positive_quantity("0")
    assert whole("30") == 30
    with pytest.raises(CellError):
        whole("1.5")
    assert boolean("Sí") is True
    assert boolean("no") is False
    with pytest.raises(CellError, match="SI o NO"):
        boolean("tal vez")


def test_text_and_choice_check_length_and_options():
    with pytest.raises(CellError, match="más de 3"):
        text(3)("abcd")
    parse = choice({"15": TaxCode.VAT_15, "VAT_15": TaxCode.VAT_15}, "IVA")
    assert parse("vat_15") == TaxCode.VAT_15
    with pytest.raises(CellError, match="IVA no válido"):
        parse("21")


# -- reading -----------------------------------------------------------------


def test_a_csv_with_commas_is_read_with_its_line_numbers():
    file = io.BytesIO(b"sku,nombre\nA-1, Martillo \n\nB-2,\n")

    table = read_table(file, "productos.csv", MAX_LINES)

    assert table.header == ["sku", "nombre"]
    assert _rows(table) == [(2, ["A-1", "Martillo"]), (3, []), (4, ["B-2", None])]


def test_a_csv_from_spanish_excel_uses_semicolons_and_windows_1252():
    content = "sku;nombre;precio_venta\nA-1;Pañuelo;1,50\n".encode("cp1252")

    table = read_table(io.BytesIO(content), "productos.csv", MAX_LINES)

    assert table.header == ["sku", "nombre", "precio_venta"]
    assert _rows(table) == [(2, ["A-1", "Pañuelo", "1,50"])]


def test_a_csv_utf8_with_bom_keeps_its_accents():
    content = "﻿sku,descripción\nA-1,Ñandú\n".encode()

    table = read_table(io.BytesIO(content), "productos.csv", MAX_LINES)

    assert table.header == ["sku", "descripción"]
    assert _rows(table) == [(2, ["A-1", "Ñandú"])]


def test_an_xlsx_reads_the_first_sheet_with_numbers_as_text():
    file = _xlsx(
        ["sku", "codigo_barras", "precio_venta", "activo"],
        ["A-1", 7861234500011, 1.5, True],
        [None, None, None, None],
        ["B-2", "0012", 3, False],
    )

    table = read_table(file, "productos.xlsx", MAX_LINES)

    assert table.header == ["sku", "codigo_barras", "precio_venta", "activo"]
    assert _rows(table) == [
        (2, ["A-1", "7861234500011", "1.5", "SI"]),
        (3, [None, None, None, None]),
        (4, ["B-2", "0012", "3", "NO"]),
    ]


@pytest.mark.parametrize(
    ("content", "name", "message"),
    [
        (b"", "productos.csv", "vacío"),
        (b"\xd0\xcf\x11\xe0rest", "productos.xls", ".xls no se admiten"),
        (b"PK\x03\x04not a workbook", "productos.xlsx", "Excel válido"),
        (b"not a zip", "productos.xlsx", "Excel válido"),
    ],
)
def test_a_file_that_cant_be_read_is_rejected(content, name, message):
    with pytest.raises(ImportFileInvalidError, match=message):
        read_table(io.BytesIO(content), name, MAX_LINES)


# -- what a small file must not make the API do (S9.3) -----------------------


def _crafted(sheet_xml: Callable[[bytes], bytes]) -> io.BytesIO:
    """A two-column workbook whose sheet XML is rewritten by `sheet_xml`"""
    source = zipfile.ZipFile(_xlsx(["sku", "nombre"], ["A-1", "Martillo"]))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as target:
        for entry in source.infolist():
            data = source.read(entry.filename)
            if entry.filename == "xl/worksheets/sheet1.xml":
                data = sheet_xml(data)
            target.writestr(entry.filename, data)
    buffer.seek(0)
    return buffer


def _dimension(ref: str) -> Callable[[bytes], bytes]:
    return lambda xml: xml.replace(
        b'<dimension ref="A1:B2" />', f'<dimension ref="{ref}" />'.encode()
    )


def _before_sheet_end(extra: bytes) -> Callable[[bytes], bytes]:
    return lambda xml: xml.replace(b"</sheetData>", extra + b"</sheetData>")


def test_the_dimension_an_xlsx_declares_is_not_trusted():
    """openpyxl padded every row to it: 16.384 empty cells each"""
    table = read_table(_crafted(_dimension("A1:XFD1048576")), "p.xlsx", MAX_LINES)

    assert table.header == ["sku", "nombre"]
    assert _rows(table) == [(2, ["A-1", "Martillo"])]


def test_a_row_number_past_the_limit_is_refused_before_reading():
    """The rows in between were filled with empty ones, one by one"""
    far = b'<row r="1048576"><c r="A1048576" t="inlineStr"><is><t>x</t></is></c></row>'
    file = _crafted(
        lambda xml: _before_sheet_end(far)(_dimension("A1:XFD1048576")(xml))
    )

    with pytest.raises(ImportFileInvalidError, match="más de 100 líneas"):
        read_table(file, "p.xlsx", MAX_LINES)


def test_a_row_of_too_many_cells_is_refused_without_loading_it():
    cells = b'<c t="inlineStr"><is><t>x</t></is></c>' * (MAX_COLUMNS + 1)
    file = _crafted(_before_sheet_end(b'<row r="3">' + cells + b"</row>"))

    with pytest.raises(ImportFileInvalidError, match=f"más de {MAX_COLUMNS} columnas"):
        read_table(file, "p.xlsx", MAX_LINES)


def test_elements_piled_outside_the_rows_are_refused():
    merged = b'<mergeCell ref="A1:A2"/>' * 100_001
    file = _crafted(
        lambda xml: xml.replace(
            b"</sheetData>", b"</sheetData><mergeCells>" + merged + b"</mergeCells>"
        )
    )

    with pytest.raises(ImportFileInvalidError, match="Excel válido"):
        read_table(file, "p.xlsx", MAX_LINES)


def test_an_xlsx_too_big_once_uncompressed_is_refused_before_reading():
    filler = b"<!-- " + b"x" * MAX_UNCOMPRESSED_BYTES + b" -->"
    file = _crafted(lambda xml: xml + filler)

    with pytest.raises(ImportFileInvalidError, match="demasiado sin comprimir"):
        read_table(file, "p.xlsx", MAX_LINES)


def test_empty_lines_count_toward_the_limit_of_a_csv():
    file = io.BytesIO(b"sku,nombre\n" + b"\n" * MAX_LINES)

    with pytest.raises(ImportFileInvalidError, match="contando las vacías"):
        _rows(read_table(file, "p.csv", MAX_LINES))


def test_a_header_too_wide_is_refused():
    file = io.BytesIO(b",".join([b"x"] * (MAX_COLUMNS + 1)) + b"\nA\n")

    with pytest.raises(ImportFileInvalidError, match=f"más de {MAX_COLUMNS} columnas"):
        read_table(file, "p.csv", MAX_LINES)


def test_cells_past_the_header_are_dropped():
    table = read_table(io.BytesIO(b"sku\nA-1,sobra,sobra\n"), "p.csv", MAX_LINES)

    assert _rows(table) == [(2, ["A-1"])]


# -- writing -----------------------------------------------------------------


def test_a_csv_is_written_with_a_bom_for_excel():
    content = write_csv(["fila", "mensaje"], [[2, "Sin unidad"], [3, None]])

    assert content.startswith(b"\xef\xbb\xbf")
    assert content.decode("utf-8-sig").splitlines() == [
        "fila,mensaje",
        "2,Sin unidad",
        "3,",
    ]


def test_an_xlsx_template_has_its_header_and_an_instructions_sheet():
    content = write_xlsx(
        ["sku", "nombre"],
        [],
        "productos",
        [["Columna", "Descripción"], ["sku", "Código interno"]],
    )

    workbook = load_workbook(io.BytesIO(content))
    assert workbook.sheetnames == ["productos", "Instrucciones"]
    assert [cell.value for cell in workbook["productos"][1]] == ["sku", "nombre"]
    assert workbook["Instrucciones"]["B2"].value == "Código interno"
    # What is written into the template is read back as the import reads it
    table = read_table(io.BytesIO(content), "plantilla.xlsx", MAX_LINES)
    assert table.header == ["sku", "nombre"]
