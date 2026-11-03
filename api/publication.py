import asyncio
import json
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile, ZipFile

from openpyxl.utils.exceptions import InvalidFileException

from api.validation import check


class WorkbookPublisher:
    """Independently validate a local candidate before atomically publishing it."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.candidate: Path | None = None

    def prepare(self) -> Path:
        folder = self.root / "work" / f"turn-{uuid4().hex}"
        folder.mkdir()
        self.candidate = folder / "submission.xlsx"
        return self.candidate

    async def publish(self) -> dict:
        source = self.candidate
        if source is None or not source.is_file():
            raise ValueError("Generate this turn's candidate workbook at the supplied local path before publishing.")
        if source.resolve() != source or source.is_symlink():
            raise ValueError("The candidate must be a regular file at this turn's supplied local path.")
        if source.stat().st_size > 30 * 1024 * 1024:
            raise ValueError("Generated workbook exceeds the 30 MB output limit.")
        try:
            with ZipFile(source) as archive:
                if sum(item.file_size for item in archive.infolist()) > 150 * 1024 * 1024:
                    raise ValueError("Generated workbook expands beyond the 150 MB limit.")
        except BadZipFile as error:
            raise ValueError("Generated output is not a valid XLSX archive.") from error
        stage = self.root / "work" / f"candidate-{uuid4().hex}.xlsx"
        shutil.copyfile(source, stage)
        try:
            try:
                validation = await asyncio.to_thread(check, str(stage))
            except (BadZipFile, ParseError, InvalidFileException, KeyError, subprocess.TimeoutExpired) as error:
                raise ValueError(f"Generated workbook validation failed: {error}") from error
            if not validation["valid"]:
                raise ValueError(f"Generated workbook was not published: {json.dumps(validation, default=str)}")
            target = self.root / "output" / "submission.xlsx"
            temporary = target.with_name(f".submission-{uuid4().hex}.xlsx")
            try:
                shutil.copyfile(stage, temporary)
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
            return {"published": True, "path": "output/submission.xlsx", "validation": validation}
        finally:
            stage.unlink(missing_ok=True)
