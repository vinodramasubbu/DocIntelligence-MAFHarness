import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from openpyxl import load_workbook

def check(path: str, old_year: str | None = None) -> dict:
    source = Path(path).resolve()
    executable = os.getenv("SOFFICE_PATH") or shutil.which("soffice")
    if not executable:
        local = Path(__file__).resolve().parents[1] / ".tools" / "LibreOffice" / "program" / "soffice.exe"
        candidate = Path(r"C:\Program Files\LibreOffice\program\soffice.exe")
        executable = str(local) if local.exists() else str(candidate) if candidate.exists() else None
    recalculated = False
    if executable:
        with tempfile.TemporaryDirectory() as temp:
            profile = (Path(temp) / "profile").as_uri()
            result = subprocess.run(
                [executable, f"-env:UserInstallation={profile}", "--headless", "--convert-to",
                 "xlsx", "--outdir", temp, str(source)],
                capture_output=True, text=True, timeout=120,
            )
            converted = Path(temp) / source.name
            if result.returncode or not converted.exists():
                raise RuntimeError(f"LibreOffice recalculation failed: {result.stderr} {result.stdout}")
            shutil.copyfile(converted, source)
            recalculated = True
    wb = load_workbook(source, data_only=True)
    formulas = load_workbook(source, data_only=False)
    errors, stale, checks, uncached = [], [], [], []
    for ws in wb:
        for row in ws:
            for cell in row:
                label = f"{ws.title}!{cell.coordinate}"
                if cell.data_type == "e":
                    errors.append({"cell": label, "error": cell.value})
                if old_year and isinstance(cell.value, str) and old_year in cell.value:
                    stale.append(label)
                if formulas[ws.title][cell.coordinate].data_type == "f" and cell.value is None:
                    uncached.append(label)
                if isinstance(cell.value, str) and cell.value.strip().lower().startswith(("check", "reconciliation")):
                    value = ws.cell(cell.row, cell.column + 1).value
                    if value not in (0, None):
                        checks.append({"cell": label, "value": value})
    wb.close()
    formulas.close()
    return {
        "recalculated": recalculated, "errors": errors, "stale_year_cells": stale,
        "nonzero_checks": checks, "uncached_formulas": uncached,
        "valid": recalculated and not (errors or stale or checks or uncached),
        "warning": None if recalculated else "LibreOffice is unavailable. Formula results have NOT been validated.",
    }
