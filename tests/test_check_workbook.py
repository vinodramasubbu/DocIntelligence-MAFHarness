from openpyxl import Workbook
from pathlib import Path
from api.validation import check


def test_validation_never_hides_errors(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws["A1"] = "Submission 2025"
    ws["A2"] = "#REF!"
    ws["A3"] = "Check"
    ws["B3"] = 20
    path = tmp_path / "bad.xlsx"
    wb.save(path)
    result = check(str(path), "2025")
    assert not result["valid"]
    assert result["errors"]
    assert result["stale_year_cells"]
    assert result["nonzero_checks"]


def test_missing_recalculator_blocks_publication_even_without_formulas(tmp_path, monkeypatch):
    workbook = Workbook()
    workbook.active["A1"] = 100
    path = tmp_path / "candidate.xlsx"
    workbook.save(path)
    workbook.close()
    exists = Path.exists
    monkeypatch.delenv("SOFFICE_PATH", raising=False)
    monkeypatch.setattr("api.validation.shutil.which", lambda name: None)
    monkeypatch.setattr(Path, "exists", lambda value: False if value.name == "soffice.exe" else exists(value))
    result = check(str(path))
    assert result["recalculated"] is False
    assert result["valid"] is False
    assert "NOT been validated" in result["warning"]
