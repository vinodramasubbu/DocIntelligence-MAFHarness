from datetime import date, datetime
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.styles.colors import COLOR_INDEX
from openpyxl.utils import get_column_letter


def color(value) -> dict | None:
    if value is None:
        return None
    rgb = value.rgb if value.type == "rgb" else (
        COLOR_INDEX[value.indexed] if value.type == "indexed" and value.indexed < len(COLOR_INDEX) else None
    )
    return {"rgb": f"#{rgb[-6:]}"} if rgb else None


def workbook_json(path: Path, prior: Path | None = None) -> dict:
    wb = load_workbook(path)
    cached = load_workbook(path, data_only=True)
    original = load_workbook(prior) if prior else None
    sheets, changes, truncated = {}, [], []
    for index, ws in enumerate(wb):
        sheet_id = f"sheet-{index}"
        if ws.max_row > 2000 or ws.max_column > 60:
            truncated.append(ws.title)
        cells = {}
        previous = original[ws.title] if original and ws.title in original.sheetnames else None
        max_row = min(max(ws.max_row, previous.max_row if previous else 0), 2000)
        max_col = min(max(ws.max_column, previous.max_column if previous else 0), 60)
        for row in ws.iter_rows(max_row=max_row, max_col=max_col):
            for cell in row:
                before = previous.cell(cell.row, cell.column).value if previous else None
                changed = original is not None and before != cell.value
                if cell.value is None and not cell.has_style and not changed:
                    continue
                style = {
                    "bl": int(bool(cell.font.bold)), "it": int(bool(cell.font.italic)),
                    "fs": cell.font.sz or 11, "ff": cell.font.name or "Calibri",
                    "cl": color(cell.font.color) or {"rgb": "#243a31"},
                    "ht": {"left": 1, "center": 2, "right": 3}.get(cell.alignment.horizontal, 0),
                    "vt": {"top": 1, "middle": 2, "center": 2, "bottom": 3}.get(cell.alignment.vertical, 3),
                    "tb": 3 if cell.alignment.wrap_text else 1,
                    "n": {"pattern": cell.number_format},
                }
                if cell.fill.patternType == "solid" and color(cell.fill.fgColor):
                    style["bg"] = color(cell.fill.fgColor)
                borders = {}
                for side, key in (("top", "t"), ("bottom", "b"), ("left", "l"), ("right", "r")):
                    border = getattr(cell.border, side)
                    if border and border.style:
                        borders[key] = {"s": {"thin": 1, "medium": 2, "thick": 3, "dashed": 4, "dotted": 5, "double": 6}.get(border.style, 1),
                                        "cl": color(border.color) or {"rgb": "#c7ceca"}}
                if borders:
                    style["bd"] = borders
                value = cached[ws.title][cell.coordinate].value if cell.data_type == "f" else cell.value
                if isinstance(value, (date, datetime)):
                    value = value.isoformat()
                data = {"v": value, "s": style}
                if cell.data_type == "f":
                    data["f"] = cell.value
                cells.setdefault(cell.row - 1, {})[cell.column - 1] = data
                if changed:
                    changes.append({"sheet": ws.title, "cell": cell.coordinate, "row": cell.row - 1, "column": cell.column - 1})
        sheets[sheet_id] = {
            "id": sheet_id, "name": ws.title,
            "rowCount": max(100, max_row + 20), "columnCount": max(26, max_col + 2),
            "cellData": cells, "defaultColumnWidth": 100, "defaultRowHeight": 23,
            "columnData": {i - 1: {"w": (ws.column_dimensions[get_column_letter(i)].width or 13) * 7,
                                   "hd": int(bool(ws.column_dimensions[get_column_letter(i)].hidden))}
                           for i in range(1, max_col + 1)},
            "rowData": {i - 1: {"h": (dim.height or 17) * 1.333, "hd": int(bool(dim.hidden))}
                        for i, dim in ws.row_dimensions.items() if i <= 2000},
            "mergeData": [{"startRow": r.min_row - 1, "endRow": min(r.max_row, 2000) - 1,
                           "startColumn": r.min_col - 1, "endColumn": min(r.max_col, 60) - 1}
                          for r in ws.merged_cells.ranges if r.min_row <= 2000 and r.min_col <= 60],
        }
    wb.close()
    cached.close()
    if original:
        original.close()
    return {
        "workbook": {"id": path.parent.parent.name + "-" + path.parent.name,
                     "name": path.name, "appVersion": "1.1.0", "locale": "enUS",
                     "sheetOrder": list(sheets), "sheets": sheets, "styles": {}},
        "changed_cells": changes, "truncated_sheets": truncated,
    }
