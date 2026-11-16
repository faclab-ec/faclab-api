"""Reading the uploaded sheets and writing templates and error reports (S5.8)"""

import io
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
from src.imports.infra.sheets import read_table, write_csv, write_xlsx
from src.shared.domain.tax import TaxCode


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

    table = read_table(file, "productos.csv")

    assert table.header == ["sku", "nombre"]
    assert _rows(table) == [(2, ["A-1", "Martillo"]), (3, []), (4, ["B-2", None])]


def test_a_csv_from_spanish_excel_uses_semicolons_and_windows_1252():
    content = "sku;nombre;precio_venta\nA-1;Pañuelo;1,50\n".encode("cp1252")

    table = read_table(io.BytesIO(content), "productos.csv")

    assert table.header == ["sku", "nombre", "precio_venta"]
    assert _rows(table) == [(2, ["A-1", "Pañuelo", "1,50"])]


def test_a_csv_utf8_with_bom_keeps_its_accents():
    content = "﻿sku,descripción\nA-1,Ñandú\n".encode()

    table = read_table(io.BytesIO(content), "productos.csv")

    assert table.header == ["sku", "descripción"]
    assert _rows(table) == [(2, ["A-1", "Ñandú"])]


def test_an_xlsx_reads_the_first_sheet_with_numbers_as_text():
    file = _xlsx(
        ["sku", "codigo_barras", "precio_venta", "activo"],
        ["A-1", 7861234500011, 1.5, True],
        [None, None, None, None],
        ["B-2", "0012", 3, False],
    )

    table = read_table(file, "productos.xlsx")

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
        read_table(io.BytesIO(content), name)


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
    table = read_table(io.BytesIO(content), "plantilla.xlsx")
    assert table.header == ["sku", "nombre"]
