"""Strict Excel adapter. It reads cell values but never executes operations."""
from openpyxl import load_workbook

from .model import SpecError


def _read_sheet(workbook, path, sheet, columns, allow_empty=False):
    if sheet not in workbook.sheetnames:
        raise SpecError(f'{path.name}: missing sheet {sheet!r}')
    rows = workbook[sheet].iter_rows()
    header = tuple(cell.value for cell in next(rows, ()))
    if len(header) != len(set(header)):
        raise SpecError(f'{path.name}/{sheet}: duplicate column header')
    if header != tuple(columns):
        missing = [column for column in columns if column not in header]
        extra = [column for column in header if column not in columns]
        raise SpecError(f'{path.name}/{sheet}: headers must be {columns}; missing={missing}, extra={extra}')
    result = []
    for row_number, cells in enumerate(rows, 2):
        values = [cell.value for cell in cells]
        if all(value is None for value in values):
            continue
        if any(cell.data_type in {'f', 'e'} for cell in cells):
            raise SpecError(f'{sheet}!{row_number}: formulas and Excel errors are forbidden')
        if len(values) != len(columns) or any(value is None or value == '' for value in values):
            raise SpecError(f'{sheet}!{row_number}: missing or unexpected cells')
        result.append((row_number, dict(zip(columns, values))))
    if not result and not allow_empty:
        raise SpecError(f'{sheet}: no data rows')
    return result


def read_rows(path, sheet, columns, allow_empty=False):
    workbook = load_workbook(path, read_only=True, data_only=False)
    try:
        return _read_sheet(workbook, path, sheet, columns, allow_empty)
    finally:
        workbook.close()


def read_tables(path, schema, optional_empty=()):
    """Read a multi-sheet specification using one workbook snapshot."""
    workbook = load_workbook(path, read_only=True, data_only=False)
    try:
        return {sheet: _read_sheet(workbook, path, sheet, columns, sheet in optional_empty)
                for sheet, columns in schema.items()}
    finally:
        workbook.close()
