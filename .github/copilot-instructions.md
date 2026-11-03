# copilot-instructions.md — Submission Builder (Simple Edition)

> Current implementation extensions requested after this original specification:
> submissions/chats/native sessions persist locally and can be reopened through two
> additional GET endpoints. Skills are Markdown-only; the harness generates per-document
> Python through the harness's native LocalShellTool and the project's .venv, not
> fixed scripts, Docker or Azure Code Interpreter. Local execution is not sandboxed.
> A trusted backend publication gate independently recalculates and validates artifacts.
> Saved submissions also support confirmed deletion, fresh-input reruns, and live
> progress watching when reopening a run that is active in another tab.
> These extensions supersede the fixed-script and memory-only examples below.

> Put this file at `.github/copilot-instructions.md`.
> **Guiding principle: keep it simple and explainable.** The intelligence lives in the **agent + skills (markdown)**, not in backend code. The backend only uploads files, runs the agent, runs a few small scripts, and serves the workbook. If a feature needs a lot of backend code, it is out of scope for now.

---

## 1. What the app does (one paragraph)
A broker uploads **last year's Excel submission** (the template) and **this year's raw client data** (policy listings, loss runs, notes). An AI agent reads both, explains in chat what it found and how it plans to update the workbook, **waits for the broker's OK**, then fills a copy of last year's workbook with this year's data. The broker sees the result **in the browser**, asks for fixes in plain English ("column F should be net paid"), and downloads the final `.xlsx`. Every customer's template is different. Nothing about any template is hard-coded.

## 2. The whole architecture
```
Next.js UI  ──►  FastAPI (4 endpoints)  ──►  Agent Framework harness  ──►  gpt-6.1-sol (Foundry)
                      │                          │
                      │                          └─ Skills (SKILL.md + 5 small Python scripts, run locally)
                      └─ ./runs/<run_id>/  (plain folders: prior/ raw/ work/ output/)
```
**That's it.** For the MVP there is no database, no queue, no blob storage, no Azure Functions and no background workers. Run state is just files in a folder, and the chat session is kept in memory.

### How to explain it in 30 seconds
1. You upload files, and they're saved to a folder.
2. You chat with an agent. The agent follows **AGENTS.md** (its job description) and uses **skills** (how-to guides) to read the template, read the raw data and fill the workbook.
3. Skills come with tiny scripts so the agent reads and writes Excel **exactly**, without guessing numbers.
4. The agent always shows its plan and waits for your OK before writing anything.
5. You see the workbook in the browser and download it.

---

## 3. Tech stack
| Part | Choice |
|---|---|
| Frontend | Next.js 15 (App Router, TypeScript), Fluent UI React v9, **Univer** (read-only Excel viewer) |
| Backend | Python 3.11, FastAPI, `sse-starlette` |
| Agent | Microsoft Agent Framework Python: `create_harness_agent`, `FoundryChatClient`, `SkillsProvider` |
| Model | Foundry project deployment `gpt-6.1-sol` |
| Excel | `openpyxl` (read/write with formatting), `pandas` + `duckdb` (raw data), LibreOffice headless (recalculate) |

## 4. Repository layout (small on purpose)
```
/
├─ .github/copilot-instructions.md
├─ api/
│  ├─ main.py            # FastAPI: 4 endpoints (~120 lines)
│  ├─ agent.py           # builds the harness agent (~40 lines)
│  ├─ runner.py          # runs skill scripts as subprocesses (~30 lines)
│  ├─ viewer.py          # xlsx → Univer JSON for the browser (~100 lines)
│  ├─ AGENTS.md          # the agent's job description
│  ├─ skills/            # 3 skills (see §6)
│  ├─ requirements.txt
│  └─ Dockerfile
├─ web/
│  ├─ app/page.tsx       # the single workspace page
│  ├─ components/        # Chat.tsx, PlanCard.tsx, Upload.tsx, WorkbookPane.tsx
│  └─ lib/api.ts
└─ samples/              # test packs (see §9)
```
**Rule for Copilot:** stay at roughly this size. Don't add services, layers, repositories, factories or abstractions that aren't listed here.

---

## 5. Backend

### 5.1 `agent.py`
```python
from pathlib import Path
from azure.identity.aio import DefaultAzureCredential
from agent_framework import create_harness_agent, SkillsProvider
from agent_framework.foundry import FoundryChatClient
from runner import run_script
import os

HERE = Path(__file__).parent

agent = create_harness_agent(
    client=FoundryChatClient(
        project_endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
        model=os.environ.get("FOUNDRY_MODEL", "gpt-6.1-sol"),
        credential=DefaultAzureCredential(),
    ),
    name="submission-builder",
    agent_instructions=(HERE / "AGENTS.md").read_text(),
    skills_provider=SkillsProvider.from_paths(skill_paths=HERE / "skills", script_runner=run_script),
    auto_approval_rules=[SkillsProvider.all_tools_auto_approval_rule],  # our own trusted skills
    disable_web_search=True,
)
```
- **Human review happens in the chat, not in approval pop-ups.** AGENTS.md tells the agent to present its plan and stop. The broker replies "go ahead" or gives corrections. That's simpler to build and easier to explain.
- One session per run: `sessions[run_id] = agent.create_session()`. Pass `session=` on every call.
- If an Agent Framework API name is uncertain, check the official harness and skills samples, and mark it `# TODO(verify-api)`. Don't invent APIs.

### 5.2 `runner.py`
```python
import subprocess, sys
from pathlib import Path

def run_script(skill, script, args=None) -> str:
    """Run a skill's script as a subprocess and return its JSON output."""
    cmd = [sys.executable, str(Path(script.full_path)), *(args if isinstance(args, list) else [])]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    return r.stdout if r.returncode == 0 else f'{{"error": {r.stderr[-2000:]!r}}}'
```
(Add a timeout and an allow-list. That's enough hardening for the MVP.)

### 5.3 `main.py`: four endpoints only
| Endpoint | What it does |
|---|---|
| `POST /runs` | Multipart upload (`prior` file + `raw` files). Creates `runs/<id>/{prior,raw,work,output}`, saves the files, creates the agent session, returns `{run_id}`. |
| `POST /runs/{id}/chat` | Body `{message, selection?}`. Prepends the run folder path to the first message. Streams the agent reply over **SSE** with only 3 event types: `text` (reply text), `progress` (todos and skill/script steps, as one short line each), `done` (with `has_output: bool`). |
| `GET /runs/{id}/workbook?which=prior\|output` | Returns Univer JSON from `viewer.py`, plus a list of changed cells when `which=output` (simple cell-by-cell compare with the prior workbook). |
| `GET /runs/{id}/download` | Returns `output/submission.xlsx`. |

Keep all four in one file. No routers, no dependency-injection layers.

### 5.4 `viewer.py`
Load the xlsx with openpyxl. For each sheet, emit cell values, formulas, basic styles (bold, italic, font colour, fill, number format, alignment, borders), merged ranges and column widths in Univer's `IWorkbookData` shape. Cap each sheet at 2,000 rows × 60 columns.

---

## 6. Skills: 3 skills, 5 scripts
Each skill is a folder with `SKILL.md`. The frontmatter has `name` (equal to the folder name) and `description` (what it does and when to use it). The body is plain-English, step-by-step guidance. **The skills hold the domain knowledge. Keep the scripts dumb.**

```
skills/
├─ understand-template/
│  ├─ SKILL.md                 # how to find regions, meanings, year windows, formulas
│  └─ scripts/inspect_workbook.py
├─ read-raw-data/
│  ├─ SKILL.md                 # how to read policy listings, loss runs, notes; traps to check
│  └─ scripts/profile_data.py, query_data.py
└─ fill-template/
   ├─ SKILL.md                 # how to roll years forward, update values/labels, keep formulas, validate
   └─ scripts/write_cells.py, check_workbook.py
```

| Script | Input → Output (JSON to stdout) |
|---|---|
| `inspect_workbook.py <xlsx> [--sheet S] [--range A1:Z50]` | Cells with value, formula, bold, fill colour and merged flag, plus each sheet's used range. The agent uses this to *see* the layout. |
| `profile_data.py <file>` | For csv/xlsx: likely header row, columns, types, sample rows, row count. For txt/md: the text. |
| `query_data.py <file> "<SQL>"` | Runs DuckDB SQL over the file (table name `data`) and returns the rows. **This is how every number is computed.** |
| `write_cells.py <xlsx_in> <xlsx_out> <changes.json>` | Applies `[{sheet, cell, value \| formula}]` and `[{op:"insert_rows"\|"delete_rows", sheet, row, count}]`, copying the style of the neighbouring row. Never touches `prior/`. |
| `check_workbook.py <xlsx>` | Recalculates with LibreOffice, then reports error cells (`#REF!` etc.), text cells still containing old years, and check cells that aren't 0. |

**Example SKILL.md (`fill-template`)**
```markdown
---
name: fill-template
description: Update a copy of last year's submission with this year's data. Use after the broker approves the plan: rolling year windows, replacing values, updating titles/dates, keeping formulas, and validating.
---
# Fill the template
1. Copy prior/<file>.xlsx to work/submission.xlsx. Never edit prior/.
2. For each region in the approved plan:
   - Rolling window: drop the oldest year, add the newest. Shift the values; keep formulas pointing at the right cells.
   - Values: write ONLY numbers you got from query_data.py. Record the query next to each change.
   - Lists (e.g. top 10 large losses): rebuild the rows, keep the total row formula.
   - Labels: update every title, header, footnote and cover date that mentions the old year or valuation date.
3. Run write_cells.py with all changes in one changes.json.
4. Run check_workbook.py. Fix any errors or stale years and check again (max 3 times).
5. Copy to output/submission.xlsx and summarise: what changed per region, totals vs raw data, open questions.
```

---

## 7. `AGENTS.md`: the agent's job description (keep it short)
```markdown
# You are the Submission Builder
You update a customer's reinsurance submission for the new year.
- prior/ = last year's workbook. It is the template. Every customer's template is different.
- raw/   = this year's raw data and notes.
- Output = output/submission.xlsx, same look and structure as last year, with this year's data.

## Rules
1. Never make up numbers. Every number comes from query_data.py on raw data.
2. Never change prior/. Keep the broker's formatting and formulas.
3. Think in regions (tables), not sheets. A sheet can hold several tables.
4. Read every note or email in raw/. They often explain or override the data.
5. If something is unclear or would change a total (units, currency, duplicates, ALAE, cancelled policies), ask.

## Steps
1. Use understand-template: list each region (sheet, range, what it shows, years covered).
2. Use read-raw-data: describe each raw file and any data issues.
3. Present a short PLAN: for each region, where the new numbers come from and what changes. List your questions.
   STOP and wait for the broker's OK.
4. Use fill-template to build output/submission.xlsx and validate it.
5. Summarise the changes and the reconciliation. Ask the broker to review it in the viewer.
6. For feedback, change only what was asked, re-validate, and say what changed.
```

---

## 8. Frontend: one page, Microsoft Cowork-style
**Layout:** a two-pane workspace with a slim header.
- **Left: chat (40%)**
  - Empty state: an upload card with two drop zones, "Last year's submission" and "This year's raw data", plus a **Start** button.
  - Messages rendered as markdown (tables supported).
  - A **PlanCard** at the top of the agent's turn: a live checklist from `progress` events (✓ done, spinner for running).
  - Progress lines as small grey text ("Reading Loss History…").
  - Composer at the bottom. If cells are selected in the viewer, show a chip ("Loss History!K5:N8") that is sent as `selection`.
- **Right: workbook (60%)**
  - Tabs: **Last year · This year**. Univer viewer, read-only, with real formatting and sheet tabs.
  - On "This year", changed cells get a soft amber highlight.
  - A **Download** button.
- **Look and feel:** Fluent v9, neutral background, white rounded cards, soft shadow, plenty of white space, Segoe UI. Calm and minimal.

State: React `useState` plus one `useChatStream(runId)` hook. No global state library.

---

## 9. Sample test packs
```
samples/harborview/   prior/ (multi-sheet P&C template) · raw/ (policy listing xlsx, loss run csv, notes) · answer_key.md
samples/northwind/    prior/ (single-sheet marine dashboard, years as columns) · raw/ (claims csv, premium csv, email) · answer_key.md
```
Both must work **with no code changes**. That's the proof the logic lives in the agent and skills.

## 10. Testing (light)
- A pytest file per script, run against `samples/`.
- One end-to-end script, `scripts/run_sample.py harborview`, that runs the agent headless with the reply "go ahead" at the review step, then compares key totals against `answer_key.md`.

## 11. Build order
1. `runner.py` + the 5 scripts + tests on samples.
2. `AGENTS.md` + 3 `SKILL.md` files + `agent.py`; try it from a small CLI loop.
3. `main.py` (4 endpoints) + `viewer.py`.
4. Next.js page: upload → chat stream → viewer → download.
5. Changed-cell highlight and selection chip.

## 12. Later (not now)
Entra sign-in, Blob/Cosmos storage, customer memory across years, tool-approval cards, Container Apps deployment. Add them only once the simple version works end to end.
