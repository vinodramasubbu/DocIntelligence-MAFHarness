"""Generate synthetic broker test packs with independently checkable answer keys."""
import csv
import json
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

ROOT = Path(__file__).resolve().parents[1]
PACK_NAMES = ("harborview", "northwind", "workers_comp", "property", "fleet", "cyber", "excess_liability")


def styled_sheet(wb, title, rows):
    ws = wb.create_sheet(title)
    for row in rows:
        ws.append(row)
    for cell in ws[1]:
        cell.font = Font(name="Calibri", bold=True, color="FFFFFF", size=14)
        cell.fill = PatternFill("solid", fgColor="315C50")
        cell.alignment = Alignment(vertical="center")
    ws.row_dimensions[1].height = 30
    for key in ("A", "B", "C", "D", "E"):
        ws.column_dimensions[key].width = 23 if key != "A" else 32
    ws.freeze_panes = "B3"
    return ws


def generate():
    for name in PACK_NAMES:
        base = ROOT / "samples" / name
        (base / "prior").mkdir(parents=True, exist_ok=True)
        (base / "raw").mkdir(exist_ok=True)
    base = ROOT / "samples" / "harborview"
    wb = Workbook()
    wb.remove(wb.active)
    styled_sheet(wb, "Cover", [
        ["Harborview P&C submission 2025"], ["Valuation date", "2025-12-31"],
        ["All figures USD. Net paid excludes ALAE."],
    ]).merge_cells("A1:D1")
    premium = styled_sheet(wb, "Premium", [
        ["Written premium 2025"], ["Policy year", "Net premium"],
        [2023, 900000], [2024, 1000000], [2025, 1100000], ["Total", "=SUM(B3:B5)"],
    ])
    losses = styled_sheet(wb, "Loss History", [
        ["Loss history at 2025-12-31"], ["Accident year", "Net paid", "ALAE"],
        [2023, 100000, 10000], [2024, 120000, 12000], [2025, 150000, 15000],
        ["Total", "=SUM(B3:B5)", "=SUM(C3:C5)"], ["Reconciliation", "=B6-SUM(B3:B5)"],
    ])
    for ws in (premium, losses):
        for row in ws.iter_rows(min_row=3, min_col=2):
            for cell in row:
                cell.number_format = '#,##0.00;[Red](#,##0.00)'
    wb.save(base / "prior" / "submission_2025.xlsx")
    policies = Workbook()
    ws = policies.active
    ws.title = "Policies"
    ws.append(["Policy ID", "Policy Year", "Net Premium", "Status"])
    for row in [
        ["P1", 2026, 600000, "Active"], ["P2", 2026, 650000, "Active"],
        ["P3", 2026, 99999, "Cancelled"],
    ]:
        ws.append(row)
    policies.save(base / "raw" / "policies.xlsx")
    with (base / "raw" / "losses.csv").open("w", newline="") as file:
        writer = csv.writer(file)
        writer.writerows([
            ["Claim ID", "Accident Year", "Net Paid", "ALAE"],
            ["L1", 2024, 130000, 13000], ["L2", 2025, 160000, 16000],
            ["L3", 2026, 100000, 11000], ["L4", 2026, 80000, 9000],
        ])
    (base / "raw" / "notes.md").write_text(
        "Prepare the 2026 submission valued 2026-12-31. USD throughout. "
        "Roll both three-year windows to 2024-2026. Preserve prior premium for "
        "2024 and 2025; exclude Cancelled policies. Restate loss history from the "
        "full loss run. Net paid excludes ALAE; show ALAE separately. "
        "Update cover and all valuation/year labels.\n", encoding="utf-8"
    )
    expected = {"Cover!A1": "Harborview P&C submission 2026", "Cover!B2": "2026-12-31",
                "Premium!A3": 2024, "Premium!A5": 2026, "Premium!B3": 1000000,
                "Premium!B4": 1100000, "Premium!B5": 1250000,
                "Loss History!B3": 130000, "Loss History!B4": 160000,
                "Loss History!B5": 180000, "Loss History!C5": 20000}
    save_answers(base, expected, {"Premium!B6": 3350000, "Loss History!B6": 470000, "Loss History!C6": 49000, "Loss History!B7": 0})

    base = ROOT / "samples" / "northwind"
    wb = Workbook()
    wb.remove(wb.active)
    ws = styled_sheet(wb, "Marine Dashboard", [
        ["Northwind Marine 2025"], ["Valued 2025-12-31"],
        ["Metric (USD)", 2023, 2024, 2025],
        ["Net premium", 400000, 450000, 500000],
        ["Net paid", 40000, 45000, 50000],
        ["Loss ratio", "=B5/B4", "=C5/C4", "=D5/D4"],
        [], ["Largest losses 2025"], ["Claim ID", "Net paid"],
        ["M-old", 50000], ["", 0], ["Total", "=SUM(B10:B11)"],
    ])
    ws.merge_cells("A1:D1")
    for cell in ws[6][1:4]:
        cell.number_format = "0.0%"
    wb.save(base / "prior" / "marine_2025.xlsx")
    for filename, rows in {
        "premium.csv": [["Policy ID", "Year", "Net Premium"], ["N1", 2026, 300000], ["N2", 2026, 250000]],
        "claims.csv": [["Claim ID", "Year", "Net Paid", "ALAE"], ["M1", 2026, 40000, 4000], ["M2", 2026, 20000, 2000]],
    }.items():
        with (base / "raw" / filename).open("w", newline="") as file:
            csv.writer(file).writerows(rows)
    (base / "raw" / "email.txt").write_text(
        "Roll the marine dashboard to 2024-2026; retain 2024 and 2025 history. "
        "Use net paid EXCLUDING ALAE. No duplicates or cancellations. USD. "
        "Valuation is 2026-12-31. Show the largest two 2026 losses descending "
        "by Net Paid and preserve the ratio and total formulas. Update every "
        "2025 title that refers to the current submission to 2026.\n", encoding="utf-8"
    )
    save_answers(base, {
        "Marine Dashboard!A1": "Northwind Marine 2026",
        "Marine Dashboard!B3": 2024, "Marine Dashboard!D3": 2026,
        "Marine Dashboard!B4": 450000, "Marine Dashboard!C4": 500000,
        "Marine Dashboard!D4": 550000, "Marine Dashboard!D5": 60000,
        "Marine Dashboard!A10": "M1", "Marine Dashboard!B10": 40000,
        "Marine Dashboard!A11": "M2", "Marine Dashboard!B11": 20000,
    }, {"Marine Dashboard!B12": 60000, "Marine Dashboard!D6": 60000 / 550000})
    workers_comp()
    property_pack()
    fleet()
    cyber()
    excess_liability()


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as file:
        csv.writer(file).writerows(rows)


def workers_comp():
    base = ROOT / "samples" / "workers_comp"
    wb = Workbook()
    wb.remove(wb.active)
    ws = styled_sheet(wb, "Payroll Rating", [
        ["Cedar Works Workers Compensation 2025"], ["Valuation date", "2025-12-31"],
        ["Class code", "Payroll USD", "Rate per USD 100", "Estimated premium"],
        ["8810", 1500000, 0.18, "=B4/100*C4"],
        ["8018", 2200000, 1.35, "=B5/100*C5"],
        ["7380", 800000, 2.2, "=B6/100*C6"],
        ["Total", "=SUM(B4:B6)", None, "=SUM(D4:D6)"],
        ["Reconciliation", "=D7-SUM(D4:D6)"],
    ])
    ws.merge_cells("A1:D1")
    styled_sheet(wb, "Loss Experience", [
        ["Workers compensation losses 2025"], ["Valuation date", "2025-12-31"],
        ["Accident year", "Net paid", "Case outstanding", "ALAE", "Incurred incl ALAE"],
        [2024, 8000, 20000, 1000, "=SUM(B4:D4)"],
        [2025, 0, 0, 0, "=SUM(B5:D5)"],
        ["Total", "=SUM(B4:B5)", "=SUM(C4:C5)", "=SUM(D4:D5)", "=SUM(E4:E5)"],
        ["Reconciliation", "=E6-SUM(B6:D6)"],
    ])
    wb.save(base / "prior" / "workers_comp_2025.xlsx")
    write_csv(base / "raw" / "payroll.csv", [
        ["Employee group", "Policy year", "Class code", "Payroll USD", "Status"],
        ["Office East", 2026, "8810", 520000, "Active"],
        ["Office West", 2026, "8810", 480000, "Active"],
        ["Warehouse East", 2026, "8018", 1000000, "Active"],
        ["Warehouse West", 2026, "8018", 1400000, "Active"],
        ["Drivers", 2026, "7380", 900000, "Active"],
        ["Cancelled division", 2026, "8018", 500000, "Cancelled"],
        ["Prior year", 2025, "8810", 2000000, "Active"],
        ["Total", "Total", "", 6800000, ""],
    ])
    rates = Workbook()
    rates.active.title = "Rates"
    for row in [
        ["Class code", "2026 rate per USD 100"],
        ["8810", 0.2], ["8018", 1.5], ["7380", 2.4],
    ]:
        rates.active.append(row)
    rates.save(base / "raw" / "rates.xlsx")
    write_csv(base / "raw" / "claim_snapshots.csv", [
        ["Claim ID", "Snapshot date", "Accident year", "Net paid", "Case outstanding", "ALAE"],
        ["WC1", "2026-09-30", 2025, 10000, 20000, 1200],
        ["WC1", "2026-12-31", 2025, 12000, 18000, 1500],
        ["WC2", "2026-12-31", 2026, 5000, 8000, 500],
    ])
    (base / "raw" / "instructions.md").write_text(
        "Synthetic Cedar Works renewal for 2026, valued 2026-12-31; USD only. "
        "Update both worksheet titles and valuation dates to 2026. Roll the two "
        "loss rows from accident years 2024-2025 to 2025-2026. Include only Active 2026 payroll "
        "detail; exclude the Total footer, prior-year and Cancelled records. Keep "
        "class codes as identifiers and apply the 2026 rates from rates.xlsx. "
        "Estimated premium = payroll / 100 * rate; keep this as an Excel formula, "
        "not a pasted result. Claim rows are full snapshots, not transactions: use "
        "only the latest snapshot per claim on or before valuation. Net paid and "
        "case outstanding exclude ALAE; incurred includes all three. Keep incurred, "
        "sum and reconciliation formulas, formatting, and the original workbook.\n",
        encoding="utf-8",
    )
    save_answers(base, {
        "Payroll Rating!A1": "Cedar Works Workers Compensation 2026", "Payroll Rating!B2": "2026-12-31",
        "Payroll Rating!B4": 1000000, "Payroll Rating!C4": 0.2,
        "Payroll Rating!B5": 2400000, "Payroll Rating!C5": 1.5,
        "Payroll Rating!B6": 900000, "Payroll Rating!C6": 2.4,
        "Loss Experience!A1": "Workers compensation losses 2026", "Loss Experience!B2": "2026-12-31",
        "Loss Experience!A4": 2025, "Loss Experience!A5": 2026,
        "Loss Experience!B4": 12000, "Loss Experience!C4": 18000, "Loss Experience!D4": 1500,
        "Loss Experience!B5": 5000, "Loss Experience!C5": 8000, "Loss Experience!D5": 500,
    }, {
        "Payroll Rating!D4": 2000, "Payroll Rating!D5": 36000, "Payroll Rating!D6": 21600,
        "Payroll Rating!B7": 4300000, "Payroll Rating!D7": 59600, "Payroll Rating!B8": 0,
        "Loss Experience!E4": 31500, "Loss Experience!E5": 13500,
        "Loss Experience!B6": 17000, "Loss Experience!C6": 26000,
        "Loss Experience!D6": 2000, "Loss Experience!E6": 45000, "Loss Experience!B7": 0,
    })


def property_pack():
    base = ROOT / "samples" / "property"
    wb = Workbook()
    wb.remove(wb.active)
    ws = styled_sheet(wb, "Locations", [
        ["Summit Property Schedule 2025"], ["Valuation date", "2025-12-31"],
        ["Location ID", "Building USD", "Contents USD", "BI USD", "Total insured value"],
        ["P1", 10000000, 2500000, 1500000, "=SUM(B4:D4)"],
        ["P2", 7000000, 900000, 400000, "=SUM(B5:D5)"],
        ["P3", 4000000, 500000, 300000, "=SUM(B6:D6)"],
        ["Total", "=SUM(B4:B6)", "=SUM(C4:C6)", "=SUM(D4:D6)", "=SUM(E4:E6)"],
        ["Reconciliation", "=E7-SUM(B7:D7)"],
    ])
    ws.merge_cells("A1:E1")
    styled_sheet(wb, "Coverage", [
        ["Summit Property Coverage 2025"], ["Valuation date", "2025-12-31"],
        ["Metric", "USD"],
        ["Policy limit", 25000000], ["Deductible", 100000],
        ["Total insured value", "=Locations!E7"],
        ["TIV above policy limit", "=MAX(B6-B4,0)"],
        ["Limit to TIV ratio", "=B4/B6"],
    ])["B8"].number_format = "0.00%"
    wb.save(base / "prior" / "property_2025.xlsx")
    write_csv(base / "raw" / "locations.csv", [
        ["Location ID", "Currency", "Building", "Contents", "Business interruption", "Status"],
        ["P1", "USD", 12000000, 3000000, 2000000, "Open"],
        ["P2", "EUR", 8000000, 1000000, 500000, "Open"],
        ["P3", "GBP", 4000000, 500000, 300000, "Open"],
        ["P4", "USD", 9900000, 0, 0, "Closed"],
        ["Total", "", "", "", "", "Summary only"],
    ])
    write_csv(base / "raw" / "fx.csv", [
        ["Currency", "USD per currency unit"], ["USD", 1], ["EUR", 1.1], ["GBP", 1.25],
    ])
    (base / "raw" / "broker_email.txt").write_text(
        "Synthetic Summit property renewal 2026, valued 2026-12-31. Include only Open "
        "locations; exclude Closed locations and the summary footer. Match P1/P2/P3 "
        "to the existing rows. Convert each source amount to USD using fx.csv "
        "(multiply by USD per currency unit); retain full precision and round final "
        "USD amounts to cents. BI means business interruption. Set the policy limit "
        "to USD 30,000,000 and deductible to USD 250,000. Update both 2025 titles and "
        "valuation dates. Preserve row totals, column totals, cross-sheet TIV, "
        "MAX-based TIV above the policy limit, limit/TIV ratio and reconciliation "
        "as formulas. TIV above the limit is a reporting metric, not a coverage "
        "determination. Preserve the percentage format and original workbook.\n",
        encoding="utf-8",
    )
    save_answers(base, {
        "Locations!A1": "Summit Property Schedule 2026", "Locations!B2": "2026-12-31",
        "Locations!B4": 12000000, "Locations!C4": 3000000, "Locations!D4": 2000000,
        "Locations!B5": 8800000, "Locations!C5": 1100000, "Locations!D5": 550000,
        "Locations!B6": 5000000, "Locations!C6": 625000, "Locations!D6": 375000,
        "Coverage!A1": "Summit Property Coverage 2026", "Coverage!B2": "2026-12-31",
        "Coverage!B4": 30000000, "Coverage!B5": 250000,
    }, {
        "Locations!E4": 17000000, "Locations!E5": 10450000, "Locations!E6": 6000000,
        "Locations!B7": 25800000, "Locations!C7": 4725000, "Locations!D7": 2925000,
        "Locations!E7": 33450000, "Locations!B8": 0,
        "Coverage!B6": 33450000, "Coverage!B7": 3450000, "Coverage!B8": 30000000 / 33450000,
    })


def fleet():
    base = ROOT / "samples" / "fleet"
    wb = Workbook()
    wb.remove(wb.active)
    styled_sheet(wb, "Fleet Summary", [
        ["Roadrunner Commercial Auto 2025"], ["Valuation date", "2025-12-31"],
        ["Vehicle type", "Vehicle count", "Insured value USD"],
        ["Car", 2, 70000], ["Van", 1, 55000], ["Truck", 1, 100000],
        ["Total", "=SUM(B4:B6)", "=SUM(C4:C6)"],
        ["Reconciliation", "=B7-SUM(B4:B6)"],
        ["All-claim net paid", 80000], ["Written premium", 200000],
        ["Paid loss ratio", "=B9/B10"],
    ])["B11"].number_format = "0.0%"
    styled_sheet(wb, "Large Losses", [
        ["Largest auto losses 2025"], ["Valuation date", "2025-12-31"],
        ["Claim ID", "Paid before recovery", "Recovery", "Net paid"],
        ["Old1", 50000, 10000, "=B4-C4"],
        ["Old2", 40000, 0, "=B5-C5"],
        ["Total top two", "=SUM(B4:B5)", "=SUM(C4:C5)", "=SUM(D4:D5)"],
        ["Reconciliation", "=D6-(B6-C6)"],
    ])
    wb.save(base / "prior" / "fleet_2025.xlsx")
    vehicles = Workbook()
    vehicles.active.title = "Vehicle Snapshots"
    for row in [
        ["Vehicle ID", "Snapshot date", "Vehicle type", "Insured value USD", "Status"],
        ["V1", "2026-12-31", "Car", 45000, "Active"],
        ["V1", "2026-03-31", "Car", 40000, "Active"],
        ["V2", "2026-12-31", "Van", 60000, "Active"],
        ["V2", "2026-06-30", "Van", 55000, "Active"],
        ["V3", "2026-12-31", "Truck", 120000, "Active"],
        ["V4", "2026-12-31", "Car", 30000, "Sold"],
        ["V5", "2026-12-31", "Van", 50000, "Cancelled"],
        ["V6", "2026-12-31", "Truck", 100000, "Active"],
    ]:
        vehicles.active.append(row)
    vehicles.save(base / "raw" / "vehicle_snapshots.xlsx")
    write_csv(base / "raw" / "claims.csv", [
        ["Claim ID", "Accident year", "Paid before recovery", "Recovery"],
        ["A1", 2026, 65000, 15000], ["A2", 2026, 30000, 0], ["A3", 2026, 55000, 35000],
    ])
    (base / "raw" / "instructions.md").write_text(
        "Synthetic Roadrunner renewal for 2026 at 2026-12-31, all USD. Vehicle rows "
        "are full snapshots: select the latest per Vehicle ID on or before valuation, "
        "then retain only Active vehicles. Do not select by file order. Exclude Sold "
        "and Cancelled vehicles. Summarize count and insured value by Car, Van, Truck. "
        "Written premium is USD 250,000. Claims are unique current-year transactions. "
        "Net paid = paid before recovery minus recovery. Put ALL claims' net paid "
        "in Fleet Summary B9; preserve the B9/B10 loss-ratio formula. Show only the "
        "two largest net-paid claims in Large Losses, descending net paid (not gross "
        "paid), with Claim ID as ascending tie-breaker. Keep net-paid, sum and "
        "reconciliation formulas. The top-two total is not the all-claim total. "
        "Update both titles and valuation dates; preserve the original workbook.\n",
        encoding="utf-8",
    )
    save_answers(base, {
        "Fleet Summary!A1": "Roadrunner Commercial Auto 2026", "Fleet Summary!B2": "2026-12-31",
        "Fleet Summary!B4": 1, "Fleet Summary!C4": 45000,
        "Fleet Summary!B5": 1, "Fleet Summary!C5": 60000,
        "Fleet Summary!B6": 2, "Fleet Summary!C6": 220000,
        "Fleet Summary!B9": 100000, "Fleet Summary!B10": 250000,
        "Large Losses!A1": "Largest auto losses 2026", "Large Losses!B2": "2026-12-31",
        "Large Losses!A4": "A1", "Large Losses!B4": 65000, "Large Losses!C4": 15000,
        "Large Losses!A5": "A2", "Large Losses!B5": 30000, "Large Losses!C5": 0,
    }, {
        "Fleet Summary!B7": 4, "Fleet Summary!C7": 325000, "Fleet Summary!B8": 0,
        "Fleet Summary!B11": 0.4,
        "Large Losses!D4": 50000, "Large Losses!D5": 30000,
        "Large Losses!B6": 95000, "Large Losses!C6": 15000, "Large Losses!D6": 80000,
        "Large Losses!B7": 0,
    })


def cyber():
    base = ROOT / "samples" / "cyber"
    wb = Workbook()
    wb.remove(wb.active)
    ws = styled_sheet(wb, "Cyber Questionnaire", [
        ["Bluebird Technology Cyber 2025"], ["Valuation date", "2025-12-31"],
        ["Field", "Response"],
        ["Annual revenue USD", "=Revenue!B7"], ["Employee count", 350],
        ["Privileged MFA status", "Partial"], ["Endpoint detection and response", "Yes"],
        ["Offline backups tested", "No"], ["Incidents in last 24 months", 2],
        ["Recovery time objective hours", 24], ["Policy limit USD", 5000000],
        ["Retention USD", 100000], ["Privileged MFA coverage", "='Security Metrics'!B6"],
    ])
    ws["B13"].number_format = "0.0%"
    styled_sheet(wb, "Revenue", [
        ["Regional revenue 2025"], ["Reporting year", 2025],
        ["Region", "Revenue USD"],
        ["North America", 60000000], ["Europe", 30000000], ["APAC", 10000000],
        ["Total", "=SUM(B4:B6)"], ["Reconciliation", "=B7-SUM(B4:B6)"],
    ])
    styled_sheet(wb, "Security Metrics", [
        ["Cyber controls 2025"], ["Valuation date", "2025-12-31"],
        ["Metric", "Count or ratio"], ["Privileged accounts", 100],
        ["MFA-covered privileged accounts", 95], ["Coverage", "=B5/B4"],
    ])["B6"].number_format = "0.0%"
    wb.save(base / "prior" / "cyber_2025.xlsx")
    write_csv(base / "raw" / "revenue.csv", [
        ["Reporting year", "Region", "Revenue USD"],
        [2026, "North America", 70000000], [2026, "Europe", 35000000], [2026, "APAC", 15000000],
        [2025, "North America", 60000000], ["Total", "2026 summary only", 120000000],
    ])
    controls = Workbook()
    controls.active.title = "Controls"
    for row in [
        ["Control", "Value"],
        ["Employee count", 420], ["Privileged accounts", 200],
        ["MFA-covered privileged accounts", 196],
        ["Endpoint detection and response", "Yes"], ["Offline backups tested", "Yes"],
        ["Incidents in last 24 months", 0], ["Recovery time objective hours", 8],
    ]:
        controls.active.append(row)
    controls.save(base / "raw" / "controls.xlsx")
    (base / "raw" / "broker_email.txt").write_text(
        "Synthetic Bluebird cyber renewal for reporting year 2026 and valuation "
        "2026-12-31. All revenue and policy amounts are USD. Include only 2026 detail "
        "revenue, not the Total footer or 2025 history. Restate all questionnaire and "
        "security-control responses from controls.xlsx, including the numeric zero "
        "incident count (zero is not blank or unknown). Privileged MFA status is "
        "Yes only if every privileged account is covered, Partial for some but not "
        "all, and No for zero covered. Coverage is covered accounts / total accounts. "
        "Policy limit is USD 10,000,000; retention is USD 250,000. Update all current "
        "submission titles, valuation dates and Revenue reporting year. Keep regional "
        "sum, reconciliation, coverage percentage and cross-sheet questionnaire "
        "formulas rather than hardcoding their answers. Preserve percentage formats "
        "and the original workbook. No external cyber assessment is required.\n",
        encoding="utf-8",
    )
    save_answers(base, {
        "Cyber Questionnaire!A1": "Bluebird Technology Cyber 2026",
        "Cyber Questionnaire!B2": "2026-12-31", "Cyber Questionnaire!B5": 420,
        "Cyber Questionnaire!B6": "Partial", "Cyber Questionnaire!B7": "Yes",
        "Cyber Questionnaire!B8": "Yes", "Cyber Questionnaire!B9": 0,
        "Cyber Questionnaire!B10": 8, "Cyber Questionnaire!B11": 10000000,
        "Cyber Questionnaire!B12": 250000,
        "Revenue!A1": "Regional revenue 2026", "Revenue!B2": 2026,
        "Revenue!B4": 70000000, "Revenue!B5": 35000000, "Revenue!B6": 15000000,
        "Security Metrics!A1": "Cyber controls 2026", "Security Metrics!B2": "2026-12-31",
        "Security Metrics!B4": 200, "Security Metrics!B5": 196,
    }, {
        "Revenue!B7": 120000000, "Revenue!B8": 0, "Security Metrics!B6": 0.98,
        "Cyber Questionnaire!B4": 120000000, "Cyber Questionnaire!B13": 0.98,
    })


def excess_liability():
    base = ROOT / "samples" / "excess_liability"
    wb = Workbook()
    wb.remove(wb.active)
    styled_sheet(wb, "Excess Liability", [
        ["Atlas Excess Liability 2025"], ["Valuation date", "2025-12-31"],
        ["Layer metric", "USD"], ["Attachment per claim", 1000000],
        ["Limit per claim", 5000000], ["Ground-up net incurred", "='Claim Layers'!E7"],
        ["Incurred within layer", "='Claim Layers'!F7"],
        ["Reconciliation", "=B6-SUM('Claim Layers'!E4:E6)"],
    ])
    ws = styled_sheet(wb, "Claim Layers", [
        ["Excess claim analysis 2025"], ["Valuation date", "2025-12-31"],
        ["Claim ID", "Paid", "Outstanding", "Recovery", "Net incurred", "Within layer"],
        ["CL1", 600000, 500000, 100000, "=MAX(B4+C4-D4,0)",
         "=MIN(MAX(E4-'Excess Liability'!$B$4,0),'Excess Liability'!$B$5)"],
        ["CL2", 200000, 100000, 0, "=MAX(B5+C5-D5,0)",
         "=MIN(MAX(E5-'Excess Liability'!$B$4,0),'Excess Liability'!$B$5)"],
        ["CL3", 2000000, 1500000, 200000, "=MAX(B6+C6-D6,0)",
         "=MIN(MAX(E6-'Excess Liability'!$B$4,0),'Excess Liability'!$B$5)"],
        ["Total", "=SUM(B4:B6)", "=SUM(C4:C6)", "=SUM(D4:D6)", "=SUM(E4:E6)", "=SUM(F4:F6)"],
        ["Reconciliation", "=E7-(B7+C7-D7)"],
    ])
    ws.column_dimensions["F"].width = 28
    wb.save(base / "prior" / "excess_liability_2025.xlsx")
    write_csv(base / "raw" / "claim_snapshots.csv", [
        ["Claim ID", "Snapshot date", "Accident year", "Paid", "Outstanding", "Recovery"],
        ["CL1", "2026-09-30", 2024, 700000, 650000, 100000],
        ["CL1", "2026-12-31", 2024, 800000, 600000, 200000],
        ["CL2", "2026-12-31", 2025, 300000, 200000, 100000],
        ["CL3", "2026-12-31", 2026, 3000000, 2000000, 500000],
        ["CL3", "2027-01-31", 2026, 9000000, 2000000, 500000],
    ])
    (base / "raw" / "layer_terms.md").write_text(
        "Synthetic Atlas 2026 renewal valued 2026-12-31; USD throughout. "
        "The renewed layer is USD 3,000,000 excess of USD 1,000,000 PER CLAIM, "
        "without an aggregate limit in this exercise. Claim rows are full valuation "
        "snapshots, not transactions. Select the latest snapshot per claim on or "
        "before 2026-12-31; exclude the future 2027 valuation and do not add snapshots. "
        "All accident years remain in scope. Net incurred = MAX(paid + outstanding "
        "- recovery, 0); there is no separate ALAE amount to add. Incurred within "
        "layer = MIN(MAX(net incurred - attachment, 0), limit), applied separately "
        "to each claim before summing. The exercise models arithmetic only, not "
        "a legal coverage determination. Update both titles and valuation dates. "
        "Preserve MAX/MIN, absolute cross-sheet references, sum and reconciliation "
        "formulas, including the distinction between ground-up and within-layer "
        "amounts. Preserve the original workbook.\n", encoding="utf-8",
    )
    save_answers(base, {
        "Excess Liability!A1": "Atlas Excess Liability 2026",
        "Excess Liability!B2": "2026-12-31", "Excess Liability!B4": 1000000,
        "Excess Liability!B5": 3000000,
        "Claim Layers!A1": "Excess claim analysis 2026", "Claim Layers!B2": "2026-12-31",
        "Claim Layers!B4": 800000, "Claim Layers!C4": 600000, "Claim Layers!D4": 200000,
        "Claim Layers!B5": 300000, "Claim Layers!C5": 200000, "Claim Layers!D5": 100000,
        "Claim Layers!B6": 3000000, "Claim Layers!C6": 2000000, "Claim Layers!D6": 500000,
    }, {
        "Claim Layers!E4": 1200000, "Claim Layers!E5": 400000, "Claim Layers!E6": 4500000,
        "Claim Layers!F4": 200000, "Claim Layers!F5": 0, "Claim Layers!F6": 3000000,
        "Claim Layers!B7": 4100000, "Claim Layers!C7": 2800000,
        "Claim Layers!D7": 800000, "Claim Layers!E7": 6100000,
        "Claim Layers!F7": 3200000, "Claim Layers!B8": 0,
        "Excess Liability!B6": 6100000, "Excess Liability!B7": 3200000,
        "Excess Liability!B8": 0,
    })


def save_answers(base, cells, calculated):
    content = "# Synthetic sample answer key\n\nExpected cell values and recalculated totals:\n\n```json\n"
    content += json.dumps({"cells": cells, "calculated": calculated}, indent=2) + "\n```\n"
    (base / "answer_key.md").write_text(content, encoding="utf-8")


if __name__ == "__main__":
    generate()
