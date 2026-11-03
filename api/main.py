import asyncio
import json
import logging
import shutil
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4
from zipfile import BadZipFile

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from openpyxl import load_workbook
from pydantic import BaseModel, Field, ValidationError
from sse_starlette.sse import EventSourceResponse

from api.agent import RunAgent
from api.persistence import SavedMessage, SavedProgress, Submission, load_submission, save_submission
from api.viewer import workbook_json

ROOT = Path(__file__).resolve().parents[1] / "runs"
sessions: dict[str, RunAgent] = {}
logger = logging.getLogger(__name__)
MAX_BYTES = 30 * 1024 * 1024


@asynccontextmanager
async def lifespan(app):
    ROOT.mkdir(exist_ok=True)
    yield
    for session in sessions.values():
        await session.close()
    sessions.clear()


app = FastAPI(title="Submission Builder", lifespan=lifespan)


def run_folder(run_id: str) -> Path:
    try:
        if str(UUID(run_id)) != run_id:
            raise ValueError()
    except ValueError:
        raise HTTPException(404, "Run not found.") from None
    folder = ROOT / run_id
    if not folder.is_dir() or folder.resolve() != ROOT.resolve() / run_id:
        raise HTTPException(404, "Run not found.")
    return folder


def read_submission(folder: Path) -> Submission:
    try:
        return load_submission(folder)
    except (OSError, ValueError, ValidationError) as error:
        logger.exception("Could not read saved submission %s", folder.name)
        raise HTTPException(500, "Saved submission state could not be read. Its files have not been changed.") from error


def submission_summary(folder: Path, submission: Submission) -> dict:
    return {
        "run_id": folder.name, "name": submission.name,
        "created_at": submission.created_at.isoformat(), "updated_at": submission.updated_at.isoformat(),
        "has_output": (folder / "output" / "submission.xlsx").is_file(),
        "busy": folder.name in sessions and sessions[folder.name].lock.locked(),
        "unavailable": None,
    }


@app.get("/runs")
async def list_runs():
    result = []
    for folder in ROOT.iterdir():
        if not folder.is_dir():
            continue
        try:
            if str(UUID(folder.name)) != folder.name:
                continue
        except ValueError:
            continue
        try:
            result.append(submission_summary(folder, read_submission(folder)))
        except HTTPException as error:
            timestamp = datetime.fromtimestamp(folder.stat().st_mtime, timezone.utc).isoformat()
            result.append({
                "run_id": folder.name, "name": folder.name, "created_at": timestamp,
                "updated_at": timestamp, "has_output": False, "busy": False,
                "unavailable": error.detail,
            })
    return sorted(result, key=lambda item: item["updated_at"], reverse=True)


@app.get("/runs/{run_id}")
async def get_run(run_id: str):
    folder = run_folder(run_id)
    submission = read_submission(folder)
    summary = submission_summary(folder, submission)
    notice = None
    if submission.in_progress and not summary["busy"]:
        notice = "The previous turn was interrupted. Partial chat was saved; continue from the last completed agent checkpoint and review any workbook changes."
    elif not (folder / "submission.json").exists():
        notice = "This older submission has saved files but no saved chat. Ask the assistant to inspect the existing files and propose a new plan before approving changes."
    return {
        **summary,
        "messages": [message.model_dump() for message in submission.messages],
        "progress": [step.model_dump(exclude_none=True) for step in submission.progress],
        "error": submission.error, "notice": notice,
    }


@app.delete("/runs/{run_id}")
async def delete_run(run_id: str):
    folder = run_folder(run_id)
    session = sessions.get(run_id)
    if session is not None and session.lock.locked():
        raise HTTPException(409, "Wait for this submission to finish before deleting it.")
    if session is not None:
        await session.lock.acquire()
    try:
        if session is not None:
            await session.close()
        shutil.rmtree(folder)
        sessions.pop(run_id, None)
    except (OSError, RuntimeError) as error:
        sessions.pop(run_id, None)
        logger.exception("Could not delete submission %s", run_id)
        raise HTTPException(500, "The submission could not be fully deleted. Review its files and retry.") from error
    finally:
        if session is not None:
            session.lock.release()
    return {"deleted": True, "run_id": run_id}


@app.post("/runs/{run_id}/rerun")
async def rerun(run_id: str):
    source = run_folder(run_id)
    if run_id in sessions and sessions[run_id].lock.locked():
        raise HTTPException(409, "Wait for this submission to finish before rerunning it.")
    original = read_submission(source)
    inputs = []
    for subfolder in ("prior", "raw"):
        directory = source / subfolder
        if not directory.is_dir() or directory.resolve() != directory:
            raise HTTPException(400, "The submission's original inputs are missing or linked elsewhere.")
        for path in directory.iterdir():
            if not path.is_file() or path.is_symlink():
                raise HTTPException(400, "Rerun requires regular original input files.")
            inputs.append((subfolder, path))
    if not any(folder == "prior" for folder, _ in inputs) or not any(folder == "raw" for folder, _ in inputs):
        raise HTTPException(400, "The submission needs both its original template and raw inputs to rerun.")
    identifier = str(uuid4())
    target = ROOT / identifier
    try:
        for subfolder in ("prior", "raw", "work", "output"):
            (target / subfolder).mkdir(parents=True)
        for subfolder, path in inputs:
            shutil.copyfile(path, target / subfolder / path.name)
        now = datetime.now(timezone.utc)
        save_submission(target, Submission(
            name=f"{original.name[:112]} (rerun)", created_at=now, updated_at=now,
        ))
    except OSError as error:
        shutil.rmtree(target)
        logger.exception("Could not rerun submission %s", run_id)
        raise HTTPException(500, "The rerun could not be created. The original submission was not changed.") from error
    return {"run_id": identifier}


async def save(file: UploadFile, folder: Path, extensions: set[str]):
    name = file.filename or ""
    if not name or Path(name).name != name or "\\" in name or "/" in name or Path(name).suffix.lower() not in extensions:
        raise HTTPException(400, "Invalid filename or unsupported file type.")
    path = folder / name
    if path.exists():
        raise HTTPException(400, f"Duplicate filename: {name}")
    size = 0
    try:
        with path.open("wb") as target:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise HTTPException(413, "Each file must be at most 30 MB.")
                target.write(chunk)
        if not size:
            raise HTTPException(400, "Empty uploads are not supported.")
        if path.suffix.lower() == ".xlsx":
            # Bound inflated XML before openpyxl opens the workbook.
            from zipfile import ZipFile
            with ZipFile(path) as archive:
                if sum(item.file_size for item in archive.infolist()) > 150 * 1024 * 1024:
                    raise HTTPException(413, "Workbook expands beyond the 150 MB limit.")
            wb = await asyncio.to_thread(load_workbook, path, read_only=True)
            wb.close()
    except (BadZipFile, KeyError, ValueError) as error:
        raise HTTPException(400, f"Invalid workbook: {name}") from error
    finally:
        await file.close()


@app.post("/runs")
async def create_run(
    prior: UploadFile = File(...), raw: list[UploadFile] = File(...),
    name: str = Form(default="", max_length=120),
):
    if not 1 <= len(raw) <= 20:
        raise HTTPException(400, "Upload between 1 and 20 raw files.")
    run_id = str(uuid4())
    folder = ROOT / run_id
    for subfolder in ("prior", "raw", "work", "output"):
        (folder / subfolder).mkdir(parents=True, exist_ok=True)
    try:
        await save(prior, folder / "prior", {".xlsx"})
        for file in raw:
            await save(file, folder / "raw", {".xlsx", ".csv", ".txt", ".md"})
        now = datetime.now(timezone.utc)
        save_submission(folder, Submission(
            name=name.strip() or Path(prior.filename).stem, created_at=now, updated_at=now,
        ))
    except Exception:
        shutil.rmtree(folder)
        raise
    return {"run_id": run_id}


class ChatInput(BaseModel):
    message: str = Field(min_length=1, max_length=20000)
    selection: str | None = Field(default=None, max_length=250)


@app.post("/runs/{run_id}/chat")
async def chat(run_id: str, body: ChatInput):
    folder = run_folder(run_id)
    submission = read_submission(folder)
    session = sessions.get(run_id)
    if session is None:
        session = RunAgent(folder)
        sessions[run_id] = session
    if session.lock.locked():
        raise HTTPException(409, "The agent is already working on this run.")
    await session.lock.acquire()
    try:
        session.restore(submission.session, submission.turn)
    except (KeyError, TypeError, ValueError) as error:
        session.lock.release()
        logger.exception("Could not restore native agent state for %s", run_id)
        raise HTTPException(500, "The saved agent checkpoint could not be restored. Its files have not been changed.") from error
    interrupted = submission.in_progress or submission.error is not None
    submission.messages.extend([
        SavedMessage(role="user", text=body.message, selection=body.selection),
        SavedMessage(role="assistant", text=""),
    ])
    submission.progress = []
    submission.error = None
    submission.in_progress = True
    try:
        save_submission(folder, submission)
    except OSError:
        session.lock.release()
        logger.exception("Could not save submission %s before starting a turn", run_id)
        raise HTTPException(500, "The submission could not be saved; the agent has not been started.") from None

    async def events():
        error = None
        completed = False
        try:
            message = body.message
            if interrupted:
                message = (
                    "The previous turn failed or was interrupted. You are resuming the last completed "
                    "agent checkpoint. Inspect current work/output files before further writes; do not "
                    "assume partial changes were validated.\nBroker message:\n" + message
                )
            async for event, data in session.stream(message, body.selection):
                if event == "text":
                    submission.messages[-1].text += data["text"]
                elif event == "progress":
                    submission.progress.append(SavedProgress.model_validate(data))
                save_submission(folder, submission)
                yield {"event": event, "data": json.dumps(data)}
            submission.session = session.session.to_dict()
            submission.turn = session.turn
            completed = True
        except Exception as exc:
            logger.exception("Agent failed for run %s", run_id)
            error = f"The agent could not complete this turn: {type(exc).__name__}: {exc}"
            submission.error = error
            submission.progress.append(SavedProgress(text=error, status="failed"))
            yield {"event": "progress", "data": json.dumps({"text": error, "status": "failed"})}
        finally:
            try:
                if not completed:
                    session.restore(submission.session, submission.turn)
                    if submission.error is None:
                        submission.error = "The turn was interrupted. Partial chat was saved; review the files and retry from the last completed agent checkpoint."
                submission.in_progress = False
                save_submission(folder, submission)
            finally:
                session.lock.release()
        yield {"event": "done", "data": json.dumps({"has_output": (folder / "output" / "submission.xlsx").is_file(), "error": error})}

    return EventSourceResponse(events())


@app.get("/runs/{run_id}/workbook")
async def get_workbook(run_id: str, which: Literal["prior", "output"] = "prior"):
    folder = run_folder(run_id)
    prior = next((folder / "prior").glob("*.xlsx"), None)
    if prior is None:
        prior = next((folder / "prior").iterdir(), None)
    path = prior if which == "prior" else folder / "output" / "submission.xlsx"
    if path is None or not path.is_file():
        raise HTTPException(404, "Workbook is not available yet.")
    return await asyncio.to_thread(workbook_json, path, prior if which == "output" else None)


@app.get("/runs/{run_id}/download")
async def download(run_id: str):
    path = run_folder(run_id) / "output" / "submission.xlsx"
    if not path.is_file():
        raise HTTPException(404, "No output workbook yet. Approve a plan in chat first.")
    return FileResponse(path, filename="submission.xlsx", media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
