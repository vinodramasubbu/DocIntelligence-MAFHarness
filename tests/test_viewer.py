import json
from openpyxl import load_workbook
from conftest import ROOT
from api.viewer import workbook_json


def test_univer_shape_changed_and_deleted_cells(tmp_path):
    prior = ROOT / "samples/harborview/prior/submission_2025.xlsx"
    output = tmp_path / "output.xlsx"
    wb = load_workbook(prior)
    wb["Premium"]["B5"] = 1250000
    wb["Cover"]["B2"] = None
    wb.save(output)
    result = workbook_json(output, prior)
    json.dumps(result)
    assert result["workbook"]["sheetOrder"] == ["sheet-0", "sheet-1", "sheet-2"]
    assert {(c["sheet"], c["cell"]) for c in result["changed_cells"]} == {("Premium", "B5"), ("Cover", "B2")}
    assert result["workbook"]["sheets"]["sheet-2"]["cellData"][5][1]["f"] == "=SUM(B3:B5)"
