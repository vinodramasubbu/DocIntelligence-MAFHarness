import csv
import json
import math
from decimal import Decimal

import pytest
from openpyxl import load_workbook

from api.validation import check
from api.viewer import workbook_json
from scripts import create_samples

NEW_PACKS = ("workers_comp", "property", "fleet", "cyber", "excess_liability")


@pytest.fixture(scope="module")
def packs(tmp_path_factory):
    root = tmp_path_factory.mktemp("synthetic-packs")
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(create_samples, "ROOT", root)
        create_samples.generate()
    return root / "samples"


def answer_key(base):
    return json.loads((base / "answer_key.md").read_text(encoding="utf-8").split("```json\n")[1].split("```")[0])


def csv_rows(base, name):
    with (base / "raw" / name).open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def latest(rows, identifier):
    chosen = {}
    for row in rows:
        if row["Snapshot date"] > "2026-12-31":
            continue
        previous = chosen.get(row[identifier])
        if previous is None or row["Snapshot date"] > previous["Snapshot date"]:
            chosen[row[identifier]] = row
    return list(chosen.values())


def assert_number(actual, expected):
    assert math.isclose(float(actual), float(expected), rel_tol=1e-10, abs_tol=1e-8)


@pytest.mark.parametrize("name", create_samples.PACK_NAMES)
def test_pack_inputs_and_answer_key_are_usable(packs, name):
    base = packs / name
    priors = list((base / "prior").glob("*.xlsx"))
    assert len(priors) == 1
    raw = list((base / "raw").iterdir())
    assert any(path.suffix in (".md", ".txt") for path in raw)
    assert any(path.suffix in (".xlsx", ".csv") for path in raw)
    assert all(path.suffix in (".xlsx", ".csv", ".md", ".txt") for path in raw)
    assert not any(path.name == "answer_key.md" for path in raw)
    key = answer_key(base)
    wb = load_workbook(priors[0])
    try:
        for address in key["cells"]:
            sheet, cell = address.rsplit("!", 1)
            assert wb[sheet][cell].data_type != "f", address
        for address in key["calculated"]:
            sheet, cell = address.rsplit("!", 1)
            assert wb[sheet][cell].data_type == "f", address
    finally:
        wb.close()
    preview = workbook_json(priors[0])
    assert preview["workbook"]["sheetOrder"]
    assert not preview["truncated_sheets"]
    json.dumps(preview)


@pytest.mark.parametrize("name", NEW_PACKS)
def test_reference_copy_preserves_formulas_and_recalculates(packs, name, tmp_path):
    base = packs / name
    prior = next((base / "prior").glob("*.xlsx"))
    original = prior.read_bytes()
    key = answer_key(base)
    wb = load_workbook(prior)
    formulas = {
        (ws.title, cell.coordinate): cell.value
        for ws in wb for row in ws for cell in row if cell.data_type == "f"
    }
    assert len(formulas) >= 5
    for address, value in key["cells"].items():
        sheet, cell = address.rsplit("!", 1)
        wb[sheet][cell] = value
    candidate = tmp_path / f"{name}.xlsx"
    wb.save(candidate)
    wb.close()
    report = check(str(candidate))
    assert report["valid"], report
    values = load_workbook(candidate, data_only=True)
    computed = load_workbook(candidate, data_only=False)
    try:
        for category in ("cells", "calculated"):
            for address, expected in key[category].items():
                sheet, cell = address.rsplit("!", 1)
                actual = values[sheet][cell].value
                if isinstance(expected, (int, float)):
                    assert isinstance(actual, (int, float)), address
                    assert_number(actual, expected)
                else:
                    assert actual == expected, address
        for (sheet, cell), formula in formulas.items():
            assert computed[sheet][cell].value == formula, f"{sheet}!{cell}"
    finally:
        values.close()
        computed.close()
    assert prior.read_bytes() == original


def test_workers_comp_raw_reconciliation(packs):
    base = packs / "workers_comp"
    key = answer_key(base)
    rows = csv_rows(base, "payroll.csv")
    included = [row for row in rows if row["Policy year"] == "2026" and row["Status"] == "Active"]
    assert len(included) == 5
    assert len(rows) - len(included) == 3
    rates_book = load_workbook(base / "raw" / "rates.xlsx", data_only=True)
    try:
        rates = {code: Decimal(str(rate)) for code, rate in rates_book.active.iter_rows(min_row=2, values_only=True)}
    finally:
        rates_book.close()
    total_premium = Decimal(0)
    total_payroll = Decimal(0)
    for index, code in enumerate(("8810", "8018", "7380"), start=4):
        payroll = sum(Decimal(row["Payroll USD"]) for row in included if row["Class code"] == code)
        premium = payroll / 100 * rates[code]
        assert_number(payroll, key["cells"][f"Payroll Rating!B{index}"])
        assert_number(rates[code], key["cells"][f"Payroll Rating!C{index}"])
        assert_number(premium, key["calculated"][f"Payroll Rating!D{index}"])
        total_payroll += payroll
        total_premium += premium
    assert_number(total_payroll, key["calculated"]["Payroll Rating!B7"])
    assert_number(total_premium, key["calculated"]["Payroll Rating!D7"])
    claims = latest(csv_rows(base, "claim_snapshots.csv"), "Claim ID")
    assert len(claims) == 2
    for index, year in enumerate(("2025", "2026"), start=4):
        incurred = Decimal(0)
        for column, field in (("B", "Net paid"), ("C", "Case outstanding"), ("D", "ALAE")):
            amount = sum(Decimal(row[field]) for row in claims if row["Accident year"] == year)
            assert_number(amount, key["cells"][f"Loss Experience!{column}{index}"])
            incurred += amount
        assert_number(incurred, key["calculated"][f"Loss Experience!E{index}"])


def test_property_raw_reconciliation(packs):
    base = packs / "property"
    key = answer_key(base)
    fx = {row["Currency"]: Decimal(row["USD per currency unit"]) for row in csv_rows(base, "fx.csv")}
    rows = csv_rows(base, "locations.csv")
    included = [row for row in rows if row["Status"] == "Open"]
    assert len(included) == 3
    assert len(rows) - len(included) == 2
    tiv = Decimal(0)
    for index, row in enumerate(included, start=4):
        location_tiv = Decimal(0)
        for column, field in (("B", "Building"), ("C", "Contents"), ("D", "Business interruption")):
            amount = (Decimal(row[field]) * fx[row["Currency"]]).quantize(Decimal("0.01"))
            assert_number(amount, key["cells"][f"Locations!{column}{index}"])
            location_tiv += amount
        assert_number(location_tiv, key["calculated"][f"Locations!E{index}"])
        tiv += location_tiv
    assert_number(tiv, key["calculated"]["Coverage!B6"])
    limit = Decimal(key["cells"]["Coverage!B4"])
    assert_number(max(tiv - limit, 0), key["calculated"]["Coverage!B7"])
    assert_number(limit / tiv, key["calculated"]["Coverage!B8"])


def test_fleet_raw_reconciliation(packs):
    base = packs / "fleet"
    key = answer_key(base)
    book = load_workbook(base / "raw" / "vehicle_snapshots.xlsx", data_only=True)
    try:
        rows = list(book.active.values)
        vehicles = [dict(zip(rows[0], row)) for row in rows[1:]]
    finally:
        book.close()
    chosen = latest(vehicles, "Vehicle ID")
    active = [row for row in chosen if row["Status"] == "Active"]
    assert len(vehicles) == 8
    assert len(chosen) == 6
    assert len(active) == 4
    for index, category in enumerate(("Car", "Van", "Truck"), start=4):
        group = [row for row in active if row["Vehicle type"] == category]
        assert len(group) == key["cells"][f"Fleet Summary!B{index}"]
        assert sum(row["Insured value USD"] for row in group) == key["cells"][f"Fleet Summary!C{index}"]
    claims = csv_rows(base, "claims.csv")
    net = {row["Claim ID"]: Decimal(row["Paid before recovery"]) - Decimal(row["Recovery"]) for row in claims}
    largest = sorted(net, key=lambda identifier: (-net[identifier], identifier))[:2]
    assert largest == [key["cells"]["Large Losses!A4"], key["cells"]["Large Losses!A5"]]
    for index, identifier in enumerate(largest, start=4):
        row = next(row for row in claims if row["Claim ID"] == identifier)
        assert_number(row["Paid before recovery"], key["cells"][f"Large Losses!B{index}"])
        assert_number(row["Recovery"], key["cells"][f"Large Losses!C{index}"])
        assert_number(net[identifier], key["calculated"][f"Large Losses!D{index}"])
    total = sum(net.values())
    assert_number(total, key["cells"]["Fleet Summary!B9"])
    assert_number(total / Decimal(key["cells"]["Fleet Summary!B10"]), key["calculated"]["Fleet Summary!B11"])
    assert sum(net[identifier] for identifier in largest) < total


def test_cyber_raw_reconciliation(packs):
    base = packs / "cyber"
    key = answer_key(base)
    rows = csv_rows(base, "revenue.csv")
    current = [row for row in rows if row["Reporting year"] == "2026"]
    assert len(current) == 3
    assert len(rows) - len(current) == 2
    for index, row in enumerate(current, start=4):
        assert_number(row["Revenue USD"], key["cells"][f"Revenue!B{index}"])
    total = sum(Decimal(row["Revenue USD"]) for row in current)
    assert_number(total, key["calculated"]["Cyber Questionnaire!B4"])
    wb = load_workbook(base / "raw" / "controls.xlsx", data_only=True)
    try:
        controls = dict(wb.active.iter_rows(min_row=2, values_only=True))
    finally:
        wb.close()
    for row, field in (
        (5, "Employee count"), (7, "Endpoint detection and response"),
        (8, "Offline backups tested"), (9, "Incidents in last 24 months"),
        (10, "Recovery time objective hours"),
    ):
        assert controls[field] == key["cells"][f"Cyber Questionnaire!B{row}"]
    accounts = controls["Privileged accounts"]
    covered = controls["MFA-covered privileged accounts"]
    assert accounts == key["cells"]["Security Metrics!B4"]
    assert covered == key["cells"]["Security Metrics!B5"]
    status = "Yes" if covered == accounts else "No" if covered == 0 else "Partial"
    assert status == key["cells"]["Cyber Questionnaire!B6"]
    assert_number(Decimal(covered) / accounts, key["calculated"]["Cyber Questionnaire!B13"])
    assert key["cells"]["Cyber Questionnaire!B9"] == 0


def test_excess_layer_raw_reconciliation(packs):
    base = packs / "excess_liability"
    key = answer_key(base)
    rows = csv_rows(base, "claim_snapshots.csv")
    chosen = sorted(latest(rows, "Claim ID"), key=lambda row: row["Claim ID"])
    assert len(rows) == 5
    assert len(chosen) == 3
    attachment = Decimal(key["cells"]["Excess Liability!B4"])
    limit = Decimal(key["cells"]["Excess Liability!B5"])
    total_incurred = Decimal(0)
    total_layer = Decimal(0)
    for index, row in enumerate(chosen, start=4):
        for column, field in (("B", "Paid"), ("C", "Outstanding"), ("D", "Recovery")):
            assert_number(row[field], key["cells"][f"Claim Layers!{column}{index}"])
        incurred = max(Decimal(row["Paid"]) + Decimal(row["Outstanding"]) - Decimal(row["Recovery"]), 0)
        layer = min(max(incurred - attachment, 0), limit)
        assert_number(incurred, key["calculated"][f"Claim Layers!E{index}"])
        assert_number(layer, key["calculated"][f"Claim Layers!F{index}"])
        total_incurred += incurred
        total_layer += layer
    assert_number(total_incurred, key["calculated"]["Excess Liability!B6"])
    assert_number(total_layer, key["calculated"]["Excess Liability!B7"])
    assert total_layer > limit
