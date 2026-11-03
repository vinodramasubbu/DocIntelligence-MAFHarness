# Submission Builder

A local broker workspace: upload last year's Excel template and this year's data,
review the agent's plan, approve it in chat, inspect the updated workbook and download.
No database, queue or hosted application infrastructure is provisioned.
Generated document-specific Python runs locally through the harness's native
`LocalShellTool`, using this project's `.venv`. **No Docker or Azure Code Interpreter is used.**
The existing Foundry deployment still provides the model.

## Architecture

- [Editable Excalidraw diagram](docs/solution-architecture.excalidraw)
- [SVG architecture preview](docs/solution-architecture.svg)
- [Architecture and system walkthrough](.github/modernize/assessment/engines/facts/architecture-diagram.md)

The diagram distinguishes the local application and code execution from Azure model
inference. It also labels the optional company-knowledge roadmap as not implemented.

## Run on Windows

Requires Python 3.11, Node.js 22+ and Azure CLI signed in to the supplied tenant.
The project uses its own `.venv`; it does not depend on global Python packages.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r api\requirements.txt
Copy-Item .env.example .env
# Edit .env and replace the Azure and Foundry placeholders before using the agent.
.\.venv\Scripts\python.exe scripts\create_samples.py
Push-Location web
npm ci
Pop-Location
.\start-all.ps1
```

The [start-all launcher](start-all.ps1) starts the backend using this project's `.venv`
and the Next.js frontend together, verifies both HTTP endpoints and the API proxy, and
stays in the terminal. **Ctrl+C stops both process trees started by the launcher.**
It refuses to take over occupied ports and never stops unrelated existing servers.
Logs are written to `.logs\backend.*.log` and `.logs\frontend.*.log`.
Run it from any working directory; paths are resolved relative to the script.

For production mode, build first and then launch:

```powershell
Push-Location web
npm run build
Pop-Location
.\start-all.ps1 -Production
```

For restricted PowerShell execution policies, use a process-only override:
`powershell -NoProfile -ExecutionPolicy Bypass -File .\start-all.ps1`.
No machine-wide policy changes or dependency installations are performed by the launcher.

Open http://127.0.0.1:3000. Use the `prior` workbook and all `raw` files from any
of the [sample packs below](#sample-submission-packs). After the plan,
reply **go ahead**. Request corrections in chat; select cells to attach their range.

### Sample submission packs

All seven packs use fictional customers and synthetic data. Each folder contains one
`prior` workbook, a `raw` folder with data and broker instructions, and an
`answer_key.md` for checking results. **Upload only the prior workbook and all raw
files; never upload the answer key.** The new templates deliberately contain live
Excel formulas, not just precomputed values. Preserve those formulas when updating inputs.

| Pack | Submission type | Formula / calculated fields | Data interpretation exercised |
|---|---|---|---|
| [Harborview](samples/harborview) | P&C premium and loss renewal | Rolling-window totals and reconciliation | Cancelled policies; paid vs ALAE |
| [Northwind](samples/northwind) | Marine dashboard | Loss ratios and largest-loss total | Horizontal year layout; top-two ranking |
| [Workers compensation](samples/workers_comp) | Payroll-rated renewal | Payroll / 100 × class rate; incurred losses; totals | Mixed-type footer; class codes; latest claim snapshots |
| [Property](samples/property) | Multi-currency location schedule | TIV sums; cross-sheet totals; `MAX` above limit; limit/TIV ratio | USD/EUR/GBP conversion; closed locations |
| [Fleet](samples/fleet) | Commercial auto | Net paid after recovery; loss ratio; top-two totals | Latest vehicle snapshots; sold/cancelled exclusions; net vs gross ranking |
| [Cyber](samples/cyber) | Revenue and security questionnaire | Regional revenue; MFA coverage percentage; cross-sheet answers | Numeric zero vs missing; partial controls; prior-year/footer exclusions |
| [Excess liability](samples/excess_liability) | Per-claim excess layer | Net incurred; `MIN`/`MAX` attachment and cap; absolute cross-sheet references | Full snapshots; future valuations; per-claim vs aggregate treatment |

For example, the workers compensation answer key expects USD 59,600 in calculated
premium; property TIV is USD 33,450,000; fleet paid loss ratio is 40%; cyber MFA
coverage is 98%; and excess-layer incurred is USD 3,200,000. These are sample
arithmetic controls, not coverage determinations.

Regenerate all packs with `.\.venv\Scripts\python.exe scripts\create_samples.py`.
This overwrites the generated sample files, not saved submissions under `runs`.
The original templates hold prior-year inputs; their formula caches may be empty
until recalculated. Answer keys describe the **updated 2026 workbook**, not the prior.
Offline tests populate reference copies, preserve every formula, independently
reconcile raw data, and verify recalculated values with LibreOffice. This does not
replace a live agent acceptance test.

### Save and resume submissions

Give a new upload an optional submission name. Use **Saved submission** above the
workspace to reopen earlier work, or **New submission** to start another without
deleting anything. The picker shows names, last-update times, and a short unique ID.
The selected submission is also included in the page URL, so refreshing that URL
reopens its chat and workbook. Do not share these local capability URLs publicly.

Uploads, workbooks, chat, activity, errors and native harness session checkpoints are
saved locally under `runs\<uuid>`. Each run's `submission.json` is written atomically.
Completed turns preserve the actual Agent Framework session and approval-turn count,
not just a display transcript. Closing and reopening the app does not require re-uploading.
On Windows, checkpoint replacement retries transient access/sharing/lock errors for
up to 3.15 seconds, retaining the complete temporary snapshot and previous checkpoint
until replacement succeeds. Persistent permission errors still fail explicitly;
the app does not change permissions or overwrite checkpoints in place.
Persistence uses no database or cloud storage service; back up the entire `runs`
folder to preserve work. Local files and generated scripts remain available when a
submission is reopened; every turn receives an updated file manifest and a fresh candidate path.

Closing the browser during an active turn can interrupt that turn. Partial chat and
activity are retained; the next message resumes from the last completed agent checkpoint.
An interruption notice/error asks you to review any partial workbook changes before
proceeding. Another tab cannot start a second turn on an already-busy submission.
Corrupt saved state is reported explicitly and is never silently replaced.

Older run folders also appear in the picker. Their existing files can be reopened,
but chats from before this feature cannot be recovered. The UI explains this and a
fresh inspection/plan is required before approving updates to an older run.

Use **Re-run submission** to create a fresh submission from the selected run's original
template and raw uploads. Its chat, approval state, generated work and output start
empty; the previous submission is not changed. Inspection starts automatically and
streams live activity, then stops for approval before workbook edits.
Use **Delete submission**, then **Delete permanently**, to remove only that submission's
uploads, chat, generated work and output. Deletion cannot be undone. Busy submissions
cannot be rerun or deleted. Failed operations are reported explicitly.

While a submission runs, Activity shows actual tool calls, elapsed viewing time,
expandable errors and an option to show the full activity list. Reopening an active
submission watches its saved chat/progress every 1.5 seconds, including work started
in another tab; no duplicate agent turn is started. Progress is not a fabricated percentage.

### Azure configuration

Resource identifiers are anonymized below. Use your own existing Azure resources
and configure the project endpoint and model deployment in your local `.env`:

- Subscription: `<AZURE_SUBSCRIPTION_ID>`
- Tenant: `<AZURE_TENANT_ID>`
- Project: `https://<FOUNDRY_RESOURCE_NAME>.services.ai.azure.com/api/projects/<FOUNDRY_PROJECT_NAME>`
- Deployment: `<MODEL_DEPLOYMENT_NAME>`

These are documentation placeholders, not runnable values. Local runtime configuration
has not been changed. Keep real identifiers and credentials out of shared documentation.

Authentication uses `DefaultAzureCredential` (local Azure CLI or managed identity).
No API keys are stored. The signed-in identity needs permission to invoke the model.
The subscription setting documents the target; it does not silently change your global CLI account.
Model prompts, tool output and conversation are sent to **your configured Foundry project**.
There are no Code Interpreter file uploads, managed execution containers or interpreter
session charges; normal model usage still applies.

### Local execution (trusted development only)

The harness factory wires `LocalShellTool` and its environment-awareness provider.
Commands run as stateless PowerShell processes, rooted in the selected submission's
folder, with `.venv\Scripts` first on PATH. Generated scripts and intermediate files
persist across calls; Python variables and shell environment changes do not.
Python safe-path mode prevents generated filenames from shadowing standard libraries.
Execution has a 120-second command timeout and 64 KiB output limit. The native tool's
exit-code/timeout metadata drives failed activity reporting. Executed shell commands
are audited under `work\generated`; document-specific Python is saved there too.

**LocalShellTool is not a sandbox.** It runs with the app's OS permissions and inherits
its environment. A working directory, instructions and `.venv` do not prevent access to
other files, credentials or the network. Use only trusted documents in this local
development configuration. Per-command tool approval is explicitly disabled
(`acknowledge_unsafe=True`) so the existing chat workflow can run automatically.
Broker approval before editing is still a conversational workflow rule, not OS isolation.
The publication tool additionally blocks the first turn and independently validates
the current candidate; generated local code is not technically prevented from bypassing it.
Do not expose this configuration as a multi-user or public service.
The shell tools package is prerelease and pinned for reproducible behavior.

### Formula recalculation

Install LibreOffice Calc, set `SOFFICE_PATH`, or place a local extraction at
`.tools\LibreOffice\program\soffice.exe`. This workspace includes that local
extraction when prepared by the build assistant. No system-wide installation is needed.
Without LibreOffice, publication is blocked with an explicit validation error rather
than pretending cached totals are correct. Generated local Python creates and checks a
candidate; the trusted local publication gate independently recalculates its formulas.
An invalid candidate never replaces a previously published workbook.

## Validation

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe scripts\run_sample.py harborview
.\.venv\Scripts\python.exe scripts\run_sample.py northwind
.\.venv\Scripts\python.exe scripts\run_sample.py workers_comp
Set-Location web
npm run typecheck
npm run build
```

Live tests incur model usage on the configured project. They send synthetic sample
files, never answer keys. All seven packs use the same skills and code without template-specific logic.
Pass any pack folder name above to `scripts\run_sample.py`.
Tests check the approval boundary, unchanged original hash, expected cells and recalculated totals.

Generated raw-data calculations preserve mixed-type source columns, including footer
labels such as `Total`. The read-raw-data skill requires explicit conversions and
inspection/reconciliation of excluded rows, rather than silently deleting labels or
counting summary rows twice. SQL `TRY_CAST` is an option if DuckDB is available;
document-specific pandas/Decimal calculations are also supported.
Activity entries are tool attempts, not evidence that a workbook has been validated.
Failed shell attempts retain their full native error output (within the shell's output
limit) under **Show error details**, including after reopening a submission. A recovered
attempt stays in the audit history; it does not mean the entire turn failed.
Generated DuckDB queries use quoted source columns and explicit non-keyword aliases;
parser failures must be corrected and dependent reconciliation calculations rerun.

## Small by design

- [API](api/main.py): eight application endpoints, including `GET /runs` and
  `GET /runs/{id}` for listing/resuming, `DELETE /runs/{id}` and
  `POST /runs/{id}/rerun`; SSE remains `text`, `progress`, `done`.
- [Persistence](api/persistence.py): atomic local JSON snapshots; no database.
- [Harness](api/agent.py): one Agent Framework harness/session per run, three markdown skills.
- [Skills](api/skills): three Markdown-only workflows; no bundled executable scripts.
- [Publication](api/publication.py): fresh local candidates, bounded workbook validation
  and atomic publication, without cloud file transfers.
- [Validation](api/validation.py): trusted, independent local recalculation/publication checks.
- [Viewer](api/viewer.py): Univer JSON, formatting, formulas, merges and changed-cell metadata.
- [UI](web/app/page.tsx): Next.js 15, Fluent UI v9, read-only Univer, local React state.

### Natural-language skills, discovered by the harness

The implementation follows Microsoft's Python [harness quickstart](https://learn.microsoft.com/en-us/agent-framework/get-started/harness?pivots=programming-language-python),
[harness concepts](https://learn.microsoft.com/en-us/agent-framework/concepts/harness?pivots=programming-language-python)
and [Agent Skills](https://learn.microsoft.com/en-us/agent-framework/agents/skills?pivots=programming-language-python) documentation.

The workflow is written in plain-English Markdown, not in a hard-coded Python pipeline:

- [AGENTS.md](api/AGENTS.md): the agent's role, approval rules and overall workflow.
- [Understand template](api/skills/understand-template/SKILL.md): how to interpret layouts and regions.
- [Read raw data](api/skills/read-raw-data/SKILL.md): how to interpret source data and reconcile totals.
- [Fill template](api/skills/fill-template/SKILL.md): how to update and validate the approved copy.

`create_harness_agent` receives `SkillsProvider.from_paths(api/skills, ...)`.
At the start of each turn the provider discovers skill folders and advertises only
their YAML `name` and `description`. The model decides which skill applies and calls
the native **`load_skill`** tool to read its Markdown body. Script discovery is disabled
and no script runner is configured. The SDK still exposes its generic `run_skill_script`
tool, but there are no executable skill scripts; the instructions direct the agent to
native **LocalShellTool** instead. The harness wires its **run_shell** tool and shell
environment provider, letting the model generate and execute project-local Python.
There is no fixed inspection/query/editing pipeline hidden behind the skills.

Executed PowerShell commands are recorded under `work\generated`; the model saves its
generated Python there and executes it through the project interpreter. After broker
approval it creates the candidate at a fresh per-turn path under `work`, then calls
**publish_workbook**. The app independently recalculates and checks a staging copy,
and atomically publishes `output\submission.xlsx` only if validation succeeds.
Instructions require preserving originals, but local execution does not enforce file
isolation. Use the app's Download link after publication, not obsolete sandbox links.

Discovery caching is disabled: add or edit `api\skills\<skill-name>\SKILL.md` and the
next turn rediscovers it without changing Python or rebuilding the frontend. A skill
contains only Markdown. `name` must match the folder name.
Each turn loads the current files, but prior chat history remains; start a new run for
an entirely clean test after changing instructions. Changes to `AGENTS.md` apply to new runs.
Do not add fixed executable helpers to skills. Update the Markdown instructions when
document interpretation or generated-code requirements change.

The app retains native harness todo tracking and reuses a session per run. It disables
web search, file memory and the separate mode tool deliberately: approval happens in chat,
and shell execution is explicitly enabled using the native LocalShellTool. Generated
code, durable work and native conversation checkpoints stay local; prompts and tool
output still go to the model.
Shell provider transcript items are preserved alongside the native session so a cold
restart can replay prior shell history without depending on service-side continuation.

Runs and chats persist under `runs\<uuid>` and can be reopened after API restart.
Use **Delete submission** in the workspace when a run is no longer needed; all saved
source data and conversation history remain on this computer until removed.
Preview is capped at 2,000 rows × 60 columns
per sheet; downloaded workbooks are not truncated.

### MVP boundaries

Local-only, single-trusted-user use: run IDs are capabilities, not authentication.
Do not expose either server publicly. No sign-in, customer isolation service or retention automation.
Supported inputs: `.xlsx`, `.csv`, UTF-8 `.txt` and `.md`; export emails to text first.
No PDF/OCR, macros, password-protected workbooks or guaranteed Excel feature fidelity.
openpyxl preserves common formatting/formulas but some Excel-only features may not survive.
Row insertion/deletion does not automatically repair dependent formulas or merged ranges:
skills prefer explicit cell updates and require validation for structural changes.
First-turn publication is blocked in code; subsequent approval interpretation follows the agent's
instructions, as specified for this conversational MVP, not a production authorization boundary.

### Debugging

Use the **Submission Builder API** and **Live sample** VS Code launches with `.venv`.
Foundry Toolkit's current `agent-dev-cli` pins an older framework core that conflicts
with this harness, so Agent Inspector is not enabled. Use the working direct VS Code
debugger configurations rather than downgrading the harness or mixing incompatible packages.
