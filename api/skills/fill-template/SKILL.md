---
name: fill-template
description: Fill a copy of a submission workbook only after broker approval, preserve formatting and formulas, roll year windows and validate the output.
---
# Fill the approved template
This skill is instructions only. Generate the required editing and verification
Python from the inspected documents; there are no bundled editing scripts.

1. Only proceed after the broker approves the proposed plan in a separate chat turn.
   Inspection, explanations and proposed corrections are not blanket approval.
2. Resolve the source from the current LOCAL Windows-path manifest. For the initial
   update use the `prior` workbook; for corrections use the current `output` workbook
   so earlier approved changes are retained. Reload calculations from local inputs;
   each shell command starts a new process and does not retain Python variables.
3. Generate openpyxl code and run it with LocalShellTool (`run_shell`) and the project
   .venv interpreter. Edit a COPY and save to this turn's supplied candidate path.
   Load the source workbook afresh rather than deep-copying a Workbook object, which
   can produce invalid style references. Save generated Python in `work\generated`.
   Apply only the approved cells, labels and dependent formulas. Preserve styles,
   number formats, merges, widths, sheet order and formulas. Write literal text as
   text, not executable Excel formulas. Never modify prior/raw or write output directly.
4. Compute every replacement number from the source data with explicit, auditable
   calculations. Print a change log containing sheet/cell, old/new values and source
   calculation, plus reconciliation totals and exclusions. Never embed guessed numbers.
5. Rolling windows: drop only the oldest period, keep retained years and add the
   newest. Update all affected labels. Historical years retained by the approved
   window are not stale. Inspect changes outside the approved region as defects.
6. openpyxl row insertion/deletion does NOT update dependent formulas, merged ranges
   or external references automatically. Prefer explicit cell updates. If structural
   edits are necessary, repair and verify every affected formula and merge.
7. Generate checks comparing the candidate with its source and expected totals.
   Reopen the saved candidate, inspect error cells, preserved formulas and formatting,
   changed regions and reconciliation checks. Python/openpyxl does not recalculate
   Excel formulas; never present missing cached results as verified totals.
   Compare formatting semantically (font/fill/border/alignment/number formats and
   explicit dimension attributes), not internal style IDs or object identity. Avoid
   creating new default column-dimension entries while merely inspecting dimensions.
8. Call publish_workbook with no arguments. The application reads only this turn's
   supplied local candidate, independently recalculates a staging copy with LibreOffice,
   checks it, and atomically publishes output/submission.xlsx only on success.
   A file created in a previous turn or a sandbox link is not a current deliverable.
9. If publication returns an error, inspect and correct the candidate in the
   local run folder and retry, at most three times. If recalculation is unavailable,
   validation fails or reconciliation is unresolved, stop and disclose the issue.
   Never claim a deliverable exists unless publish_workbook returned published=true.
10. Summarize exact totals, changed regions and limitations. Invite the broker to
    inspect "This year" and download through the app. Generated Python and executed
    shell commands are retained locally for audit. No cloud execution workspace is used.
