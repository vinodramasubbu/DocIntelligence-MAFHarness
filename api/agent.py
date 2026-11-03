import asyncio
import json
import logging
import os
from pathlib import Path
from uuid import uuid4

from agent_framework import AgentSession, Content, Message, SkillsProvider, create_harness_agent
from agent_framework.foundry import FoundryChatClient
from agent_framework.tools import LocalShellTool
from azure.identity.aio import DefaultAzureCredential
from dotenv import load_dotenv
from pydantic import BaseModel

from api.publication import WorkbookPublisher

HERE = Path(__file__).resolve().parent
logger = logging.getLogger(__name__)
load_dotenv(HERE.parent / ".env", override=False)


class RunAgent:
    """One harness per run, with a restorable native conversation session."""

    def __init__(self, root: Path):
        project_endpoint = os.getenv("FOUNDRY_PROJECT_ENDPOINT", "").strip()
        if not project_endpoint or "<" in project_endpoint or ">" in project_endpoint:
            raise ValueError("Set FOUNDRY_PROJECT_ENDPOINT to your Foundry project URL in the local .env file.")
        self.root = root.resolve()
        self.lock = asyncio.Lock()
        self.progress: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        self.turn = 0
        self.credential = DefaultAzureCredential(process_timeout=90)

        async def publish_workbook() -> str:
            """Independently recalculate and validate this turn's local candidate before publishing it."""
            if self.turn <= 1:
                raise ValueError("Present the plan and wait for broker approval first.")
            try:
                result = await self.publisher.publish()
            except (ValueError, OSError, RuntimeError) as error:
                logger.exception("Generated workbook publication failed for %s", root.name)
                await self.progress.put({"text": f"Workbook publication failed: {error}", "status": "failed"})
                return json.dumps({"error": str(error)})
            await self.progress.put({"text": "Generated workbook independently recalculated, validated and published."})
            return json.dumps(result)

        self.client = FoundryChatClient(
            project_endpoint=project_endpoint,
            model=os.getenv("FOUNDRY_MODEL", "gpt-6.1-sol"),
            credential=self.credential,
        )
        self.publisher = WorkbookPublisher(self.root)
        environment = HERE.parent / ".venv"
        self.python = environment / "Scripts" / "python.exe"
        self.shell = LocalShellTool(
            mode="stateless", workdir=self.root,
            env={
                "VIRTUAL_ENV": str(environment),
                "PATH": str(environment / "Scripts") + os.pathsep + os.environ.get("PATH", ""),
                "PYTHONIOENCODING": "utf-8",
                "PYTHONSAFEPATH": "1",
            },
            timeout=120, max_output_bytes=65536,
            approval_mode="never_require", acknowledge_unsafe=True,
            on_command=self.record_command,
        )
        self.agent = create_harness_agent(
            client=self.client, name="submission-builder",
            agent_instructions=(HERE / "AGENTS.md").read_text(encoding="utf-8"),
            skills_provider=SkillsProvider.from_paths(
                HERE / "skills", script_extensions=(), disable_caching=True,
            ),
            tools=[publish_workbook],
            shell_executor=self.shell,
            auto_approval_rules=[SkillsProvider.all_tools_auto_approval_rule],
            disable_web_search=True, disable_file_memory=True, disable_mode=True,
            max_output_tokens=8000,
            default_options={"store": False},
        )
        self.session = self.agent.create_session()

    def record_command(self, command: str):
        try:
            folder = self.root / "work" / "generated"
            folder.mkdir(exist_ok=True)
            (folder / f"{uuid4().hex}.ps1").write_text(command, encoding="utf-8")
        except OSError as error:
            logger.exception("Could not save local shell audit for %s", self.root.name)
            self.progress.put_nowait({"text": f"Local shell audit could not be saved: {error}", "status": "failed"})

    def restore(self, state: dict | None, turn: int):
        self.session = AgentSession.from_dict(state) if state is not None else self.agent.create_session()
        self.turn = turn
        self.preserve_shell_history()

    def preserve_shell_history(self):
        # Native session serialization omits raw provider items needed for stateless shell replay.
        def visit(value):
            if isinstance(value, Message):
                visit(value.contents)
            elif isinstance(value, Content):
                if value.text is not None:
                    value.text = str(value.text)
                raw = value.raw_representation
                if isinstance(raw, BaseModel):
                    raw = raw.model_dump(mode="json", exclude_none=True)
                if isinstance(raw, dict) and raw.get("type") in ("shell_call", "shell_call_output", "local_shell_call"):
                    value.additional_properties["submission_shell_item"] = raw
                elif "submission_shell_item" in value.additional_properties:
                    value.raw_representation = value.additional_properties["submission_shell_item"]
                visit(value.items)
                visit(value.outputs)
                visit(value.function_call)
            elif isinstance(value, dict):
                for item in value.values():
                    visit(item)
            elif isinstance(value, (list, tuple)):
                for item in value:
                    visit(item)

        visit(self.session.state)

    async def stream(self, message: str, selection: str | None = None):
        self.turn += 1
        while not self.progress.empty():
            self.progress.get_nowait()
        announced_calls = set()
        shell_calls = set()
        emitted_text = False
        needs_separator = False
        try:
            yield "progress", {"text": "Using the harness LocalShellTool with the project .venv (local execution; no Docker)."}
            candidate = self.publisher.prepare()
            files = [
                {"folder": folder, "name": path.name, "path": str(path.resolve())}
                for folder in ("prior", "raw", "output")
                for path in sorted((self.root / folder).iterdir()) if path.is_file()
            ]
            context = (
                "Current LOCAL submission files (supersede old cloud attachments and paths):\n"
                f"{json.dumps(files)}\nRun folder: {self.root}\n"
                f"Project Python: {self.python}\nThis turn's candidate workbook: {candidate}\n"
                "Use the harness run_shell tool to generate and execute document-specific Python locally. "
                "Each shell command starts fresh in this run folder; Python variables do not persist. "
                "Save reusable generated scripts under work\\generated. Re-read local inputs when resuming. "
                "No Azure Code Interpreter, uploaded file IDs, /mnt/data or Docker. "
                "Only publish_workbook may write the deliverable in output; it validates this turn's candidate. "
                "Do not create a candidate workbook before broker approval.\n"
            )
            if selection:
                context += f"Broker selected cells: {selection}\n"
            async for update in self.agent.run(
                context + "\nBroker message:\n" + message, session=self.session, stream=True,
            ):
                while not self.progress.empty():
                    yield "progress", self.progress.get_nowait()
                for content in update.contents:
                    if content.type == "function_call" and content.name and content.call_id not in announced_calls:
                        announced_calls.add(content.call_id)
                        if content.name == "run_shell":
                            shell_calls.add(content.call_id)
                        yield "progress", {"text": f"Using {content.name}"}
                        needs_separator = emitted_text
                    if content.type == "function_result" and content.call_id in shell_calls:
                        if content.exception or content.status == "failed":
                            yield "progress", {
                                "text": "Local shell execution failed", "status": "failed",
                                "details": str(content.exception or content.result),
                            }
                        else:
                            for item in content.items or []:
                                details = item.additional_properties or {}
                                if details.get("timed_out") or details.get("exit_code") not in (0, None):
                                    reason = "timed out" if details.get("timed_out") else f"exit code {details['exit_code']}"
                                    yield "progress", {
                                        "text": f"Local shell execution failed ({reason})", "status": "failed",
                                        "details": str(details.get("stderr") or item.text or reason),
                                    }
                    if content.type == "text" and content.text and content.merge_mode != "replace":
                        yield "text", {"text": ("\n\n" if needs_separator else "") + content.text}
                        emitted_text = True
                        needs_separator = False
        finally:
            await self.shell.close()
        self.preserve_shell_history()
        while not self.progress.empty():
            yield "progress", self.progress.get_nowait()

    async def close(self):
        await self.shell.close()
        await self.client.client.close()
        await self.client.project_client.close()
        await self.credential.close()
