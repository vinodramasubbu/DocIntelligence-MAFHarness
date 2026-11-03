import os
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class SavedMessage(BaseModel):
    role: Literal["user", "assistant"]
    text: str
    selection: str | None = None


class SavedProgress(BaseModel):
    text: str
    status: Literal["failed"] | None = None
    details: str | None = None


class Submission(BaseModel):
    version: Literal[1] = 1
    name: str
    created_at: datetime
    updated_at: datetime
    messages: list[SavedMessage] = Field(default_factory=list)
    progress: list[SavedProgress] = Field(default_factory=list)
    error: str | None = None
    in_progress: bool = False
    turn: int = Field(default=0, ge=0)
    session: dict[str, Any] | None = None


def load_submission(folder: Path) -> Submission:
    path = folder / "submission.json"
    if path.exists():
        return Submission.model_validate_json(path.read_text(encoding="utf-8"))
    prior = next((folder / "prior").glob("*.xlsx"), None)
    if prior is None:
        raise ValueError("The saved submission has no prior workbook.")
    created = datetime.fromtimestamp(folder.stat().st_ctime, timezone.utc)
    return Submission(name=prior.stem, created_at=created, updated_at=created)


def save_submission(folder: Path, submission: Submission):
    submission.updated_at = datetime.now(timezone.utc)
    temporary = folder / f".submission-{uuid4().hex}.tmp"
    try:
        with temporary.open("w", encoding="utf-8") as file:
            file.write(submission.model_dump_json())
            file.flush()
            os.fsync(file.fileno())
        # Windows readers and antivirus can briefly deny replacement of a closed file.
        delays = (0.05, 0.1, 0.2, 0.4, 0.8, 1.6)
        for attempt in range(len(delays) + 1):
            try:
                temporary.replace(folder / "submission.json")
                if attempt:
                    logger.info("Saved submission %s after %s replacement retries", folder.name, attempt)
                break
            except OSError as error:
                if getattr(error, "winerror", None) not in (5, 32, 33) or attempt == len(delays):
                    raise
                if attempt == 0:
                    logger.warning("Windows blocked checkpoint replacement for submission %s; retrying: %s", folder.name, error)
                time.sleep(delays[attempt])
    finally:
        temporary.unlink(missing_ok=True)
