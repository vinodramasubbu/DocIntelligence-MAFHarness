---
name: understand-template
description: Inspect an Excel submission template to identify regions, years, formulas, labels and formatting. Use before proposing any update.
---
# Understand the template
This skill contains instructions only. Generate inspection Python for the uploaded
workbook at runtime and execute it with the harness's native LocalShellTool (`run_shell`)
and the supplied project Python. There is no bundled inspection script.

1. Read the current turn's LOCAL input manifest and locate the `prior` workbook.
   Use the supplied Windows paths, not cloud file IDs or `/mnt/data`. Commands start
   in this submission's run folder. Save generated Python under `work\generated`.
2. Generate Python using openpyxl to inspect the actual workbook. Load formulas
   with `data_only=False`; use a second data-only load only for existing cached values.
   Report all sheet names, used ranges, populated cells, formulas, merged ranges,
   styles, number formats, widths, hidden rows/columns and relevant notes.
3. Use focused reads to avoid flooding the chat, but continue until ALL populated
   regions have been inspected. Never assume a preview covers the whole workbook.
4. Identify each table's sheet/range, row/column meanings, units, currency, year
   window, totals and check cells. Distinguish calendar, policy, accident and
   underwriting years. A sheet can contain several unrelated tables and its first
   row is not necessarily a header.
5. Inventory cover dates, titles, footnotes, valuation dates and dependent formulas.
   For an existing `output` workbook, inspect that local copy too so corrections
   preserve earlier approved changes.
6. Preserve historic values unless the raw data explicitly restates them.
   Report uncertainties to the broker; do not infer missing numeric values.

Print a compact, structured inventory as evidence for the plan. Do not edit any
workbook, generate a deliverable or call publish_workbook during inspection.
The application audits executed shell commands; retain generated Python in the run folder.
LocalShellTool is not a sandbox: access only this submission's files and never modify inputs.
