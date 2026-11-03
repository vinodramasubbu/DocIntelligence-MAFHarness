import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from agent_framework import AgentSession, Content, Message

import api.agent as module
from api.agent import RunAgent


@pytest.fixture
def configured(monkeypatch, tmp_path):
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://example.services.ai.azure.com/api/projects/example")
    def skills(paths, script_extensions, disable_caching):
        assert disable_caching is True
        assert script_extensions == ()
        return object()

    publisher = SimpleNamespace(
        prepare=Mock(return_value=tmp_path / "work" / "turn-candidate" / "submission.xlsx"),
        publish=AsyncMock(return_value={"published": True}),
    )
    monkeypatch.setattr(module, "SkillsProvider", SimpleNamespace(
        from_paths=skills, all_tools_auto_approval_rule=lambda *args: True,
    ))
    monkeypatch.setattr(module, "FoundryChatClient", lambda **kwargs: SimpleNamespace(
        client=SimpleNamespace(close=AsyncMock()), project_client=SimpleNamespace(close=AsyncMock()),
    ))
    monkeypatch.setattr(module, "WorkbookPublisher", lambda *args: publisher)
    monkeypatch.setattr(module, "DefaultAzureCredential", lambda **kwargs: SimpleNamespace(close=AsyncMock()))
    monkeypatch.setattr(module, "LocalShellTool", lambda **kwargs: SimpleNamespace(
        **kwargs, close=AsyncMock(), as_function=lambda: SimpleNamespace(result_parser=lambda value: value),
    ))
    monkeypatch.setattr(module, "create_harness_agent", lambda **kwargs: SimpleNamespace(
        create_session=lambda: AgentSession(), options=kwargs,
    ))
    for folder in ("prior", "raw", "work", "output"):
        (tmp_path / folder).mkdir()
    return RunAgent(tmp_path), publisher


@pytest.mark.parametrize("endpoint", ["", "https://<RESOURCE>.services.ai.azure.com/api/projects/<PROJECT>"])
def test_missing_or_placeholder_project_endpoint_is_explicit(monkeypatch, tmp_path, endpoint):
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", endpoint)
    with pytest.raises(ValueError, match="Set FOUNDRY_PROJECT_ENDPOINT"):
        RunAgent(tmp_path)


def test_stream_does_not_duplicate_final_text_or_tool_deltas(configured):
    agent, publisher = configured
    assert agent.agent.options["shell_executor"] is agent.shell
    assert agent.shell.mode == "stateless"
    assert agent.shell.workdir == agent.root
    assert agent.shell.env["PATH"].split(module.os.pathsep)[0] == str(agent.python.parent)
    assert agent.shell.acknowledge_unsafe is True
    assert agent.shell.approval_mode == "never_require"

    class FakeHarness:
        async def run(self, *args, **kwargs):
            assert "tools" not in kwargs
            assert "Current LOCAL submission files" in args[0]
            assert str(agent.python) in args[0]
            assert str(publisher.prepare.return_value) in args[0]
            for content in (
                Content.from_text("Plan", merge_mode="append"),
                Content.from_text(" ready.", merge_mode="append"),
                Content.from_text("Plan ready.", merge_mode="replace"),
                Content.from_function_call(call_id="call-1", name="load_skill", arguments=""),
                Content.from_function_call(call_id="call-1", name="load_skill", arguments="{}"),
                Content.from_text("Updating.", merge_mode="append"),
            ):
                yield SimpleNamespace(contents=[content])

    agent.agent = FakeHarness()

    async def collect():
        return [event async for event in agent.stream("Make a plan")]

    events = asyncio.run(collect())
    assert "".join(data["text"] for kind, data in events if kind == "text") == "Plan ready.\n\nUpdating."
    assert sum(data["text"] == "Using load_skill" for kind, data in events if kind == "progress") == 1
    agent.shell.close.assert_awaited_once()


def test_publication_requires_later_turn_and_validated_runtime(configured):
    agent, runtime = configured
    publish = agent.agent.options["tools"][0]
    with pytest.raises(ValueError, match="approval"):
        asyncio.run(publish())
    runtime.publish.assert_not_awaited()
    agent.turn = 2
    assert json.loads(asyncio.run(publish()))["published"] is True
    runtime.publish.assert_awaited_once()


def test_publication_failures_are_reported_to_agent(configured):
    agent, runtime = configured
    agent.turn = 2
    runtime.publish.side_effect = ValueError("Workbook could not be recalculated.")
    result = asyncio.run(agent.agent.options["tools"][0]())
    assert json.loads(result)["error"] == "Workbook could not be recalculated."
    assert agent.progress.get_nowait()["status"] == "failed"


def test_stream_preserves_failed_step_status(configured):
    agent, _ = configured

    class FakeHarness:
        async def run(self, *args, **kwargs):
            agent.progress.put_nowait({"text": "Generated code failed: invalid year", "status": "failed"})
            yield SimpleNamespace(contents=[Content.from_text("Please clarify the invalid year.")])

    agent.agent = FakeHarness()

    async def collect():
        return [event async for event in agent.stream("Inspect")]

    events = asyncio.run(collect())
    assert ("progress", {"text": "Generated code failed: invalid year", "status": "failed"}) in events


def test_native_session_and_approval_turn_survive_json_round_trip(configured):
    agent, _ = configured
    agent.session.state["history"] = [
        Message(role="assistant", contents=[Content.from_text("Plan: keep the original and update B2.")]),
    ]
    snapshot = json.loads(json.dumps(agent.session.to_dict()))
    restored = RunAgent(agent.root)
    restored.restore(snapshot, 1)
    assert restored.session.session_id == agent.session.session_id
    assert restored.session.state["history"][0].text == "Plan: keep the original and update B2."
    with pytest.raises(ValueError, match="approval"):
        asyncio.run(restored.agent.options["tools"][0]())


def test_shell_provider_transcripts_survive_json_checkpoint_and_restore(configured):
    from openai.types.responses import ResponseFunctionShellToolCall, ResponseFunctionShellToolCallOutput

    agent, _ = configured
    raw_call = ResponseFunctionShellToolCall.model_validate({
        "id": "sh_test", "type": "shell_call", "call_id": "call_test", "status": "completed",
        "action": {"commands": ["python -V"]}, "environment": {"type": "local"},
    })
    raw_result = ResponseFunctionShellToolCallOutput.model_validate({
        "id": "sho_test", "type": "shell_call_output", "call_id": "call_test", "status": "completed",
        "output": [{"stdout": "Python 3.11", "stderr": "", "outcome": {"type": "exit", "exit_code": 0}}],
    })
    call = Content.from_shell_tool_call(call_id="call_test", commands=["python -V"], raw_representation=raw_call)
    result = Content.from_shell_tool_result(call_id="call_test", raw_representation=raw_result)
    agent.session.state["history"] = [
        Message(role="assistant", contents=[call]), Message(role="tool", contents=[result]),
    ]
    agent.preserve_shell_history()
    snapshot = json.loads(json.dumps(agent.session.to_dict()))
    restored = RunAgent(agent.root)
    restored.restore(snapshot, 1)
    history = restored.session.state["history"]
    assert history[0].contents[0].raw_representation == raw_call.model_dump(mode="json", exclude_none=True)
    assert history[1].contents[0].raw_representation == raw_result.model_dump(mode="json", exclude_none=True)


def test_prepare_failure_still_closes_local_shell(configured):
    agent, publisher = configured
    publisher.prepare.side_effect = OSError("Working directory is not writable.")

    async def collect():
        return [event async for event in agent.stream("Inspect")]

    with pytest.raises(OSError, match="not writable"):
        asyncio.run(collect())
    agent.shell.close.assert_awaited_once()


def test_native_shell_failures_and_timeouts_are_reported_without_stdout_parsing(configured):
    agent, _ = configured

    class FakeHarness:
        async def run(self, *args, **kwargs):
            for identifier, details in (
                ("failed", {"exit_code": 7, "stderr": "Invalid year"}),
                ("timeout", {"exit_code": None, "timed_out": True}),
                ("okay", {"exit_code": 0, "stderr": "Informational warning"}),
            ):
                yield SimpleNamespace(contents=[Content.from_function_call(
                    call_id=identifier, name="run_shell", arguments="{}",
                )])
                yield SimpleNamespace(contents=[Content.from_function_result(
                    identifier, result=[Content.from_text("Native shell output", additional_properties=details)],
                )])

    agent.agent = FakeHarness()

    async def collect():
        return [event async for event in agent.stream("Inspect")]

    events = asyncio.run(collect())
    failures = [data for kind, data in events if kind == "progress" and data.get("status") == "failed"]
    assert len(failures) == 2
    assert "exit code 7" in failures[0]["text"] and "Invalid year" in failures[0]["details"]
    assert "timed out" in failures[1]["text"]


def test_shell_error_details_retain_parser_message_after_long_traceback(configured):
    agent, _ = configured
    stderr = "Traceback (most recent call last):\n" + ("  generated script frame\n" * 50)
    stderr += '_duckdb.ParserException: Parser Error: syntax error at or near "year"\n'

    class FakeHarness:
        async def run(self, *args, **kwargs):
            yield SimpleNamespace(contents=[Content.from_function_call(
                call_id="failed", name="run_shell", arguments="{}",
            )])
            yield SimpleNamespace(contents=[Content.from_function_result(
                "failed", result=[Content.from_text("Native shell output", additional_properties={
                    "exit_code": 1, "stderr": stderr,
                })],
            )])

    agent.agent = FakeHarness()

    async def collect():
        return [event async for event in agent.stream("Inspect")]

    events = asyncio.run(collect())
    failure = next(data for kind, data in events if kind == "progress" and data.get("status") == "failed")
    assert failure["text"] == "Local shell execution failed (exit code 1)"
    assert failure["details"] == stderr


def test_executed_commands_are_audited_and_close_releases_all_clients(configured):
    agent, _ = configured
    agent.shell.on_command("python generated.py")
    audit = list((agent.root / "work" / "generated").glob("*.ps1"))
    assert len(audit) == 1 and audit[0].read_text() == "python generated.py"
    asyncio.run(agent.close())
    agent.shell.close.assert_awaited_once()
    agent.client.client.close.assert_awaited_once()
    agent.client.project_client.close.assert_awaited_once()
    agent.credential.close.assert_awaited_once()
