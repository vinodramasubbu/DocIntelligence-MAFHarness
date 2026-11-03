import asyncio
import json
import shutil
from pathlib import Path

import pytest
from agent_framework import AgentSession
from fastapi.testclient import TestClient

from api import main
from conftest import ROOT


class FakeAgent:
    def __init__(self, root):
        self.lock = asyncio.Lock()
        self.root = root
        self.session = AgentSession()
        self.turn = 0
        self.closed = False

    def restore(self, state, turn):
        self.session = AgentSession.from_dict(state) if state is not None else AgentSession()
        self.turn = turn

    async def stream(self, message, selection=None):
        self.turn += 1
        previous = self.session.state.get("last_message", "")
        self.session.state["last_message"] = message
        if message == "fail":
            yield "text", {"text": "Partial response"}
            raise RuntimeError("Test failure")
        if message == "recovered":
            yield "progress", {
                "text": "Local shell execution failed (exit code 1)", "status": "failed",
                "details": 'Traceback\n' + ('generated frame\n' * 50) + 'Parser Error: syntax error at or near "year"',
            }
            yield "progress", {"text": "Using run_shell"}
        yield "text", {"text": f"Plan ready. Waiting for your approval. Previous message: {previous}"}

    async def close(self):
        self.closed = True


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "ROOT", tmp_path)
    monkeypatch.setattr(main, "RunAgent", FakeAgent)
    with TestClient(main.app) as client:
        yield client


def create(client):
    prior = ROOT / "samples/harborview/prior/submission_2025.xlsx"
    return client.post("/runs", files=[
        ("prior", ("submission.xlsx", prior.read_bytes())),
        ("raw", ("notes.md", b"Roll to 2026")),
    ])


def test_upload_plan_preview_and_download_gate(client):
    response = create(client)
    assert response.status_code == 200
    run_id = response.json()["run_id"]
    assert client.get(f"/runs/{run_id}/workbook").status_code == 200
    assert client.get(f"/runs/{run_id}/workbook?which=invalid").status_code == 422
    assert client.get(f"/runs/{run_id}/download").status_code == 404
    chat = client.post(f"/runs/{run_id}/chat", json={"message": "Make a plan"})
    assert "event: text" in chat.text and "event: done" in chat.text
    assert '"has_output": false' in chat.text
    assert len([r for r in main.app.routes if getattr(r, "path", "").startswith("/runs")]) == 8


def test_error_event_and_lock_cleanup(client):
    run_id = create(client).json()["run_id"]
    reply = client.post(f"/runs/{run_id}/chat", json={"message": "fail"})
    assert "Test failure" in reply.text
    assert '"status": "failed"' in reply.text
    assert '"error":' in reply.text
    assert not main.sessions[run_id].lock.locked()
    assert client.post(f"/runs/{run_id}/chat", json={"message": "retry"}).status_code == 200


def test_transient_windows_lock_during_stream_does_not_fail_turn(client, monkeypatch):
    run_id = create(client).json()["run_id"]
    replace = Path.replace
    attempts = 0
    waits = []

    def locked_once(source, target):
        nonlocal attempts
        attempts += 1
        if attempts == 2:
            error = PermissionError("Checkpoint reader denied replacement")
            error.winerror = 5
            raise error
        return replace(source, target)

    monkeypatch.setattr(Path, "replace", locked_once)
    monkeypatch.setattr("api.persistence.time.sleep", waits.append)
    reply = client.post(f"/runs/{run_id}/chat", json={"message": "Make a plan"})
    assert "event: done" in reply.text and '"error": null' in reply.text
    assert waits == [0.05]
    saved = client.get(f"/runs/{run_id}").json()
    assert saved["error"] is None
    assert not main.sessions[run_id].lock.locked()
    main.sessions.clear()
    assert "Previous message: Make a plan" in client.post(
        f"/runs/{run_id}/chat", json={"message": "Continue"},
    ).text


def test_recovered_failure_preserves_full_details_in_sse_and_saved_activity(client):
    run_id = create(client).json()["run_id"]
    response = client.post(f"/runs/{run_id}/chat", json={"message": "recovered"})
    assert "Parser Error" in response.text and '"error": null' in response.text
    saved = client.get(f"/runs/{run_id}").json()
    failure = saved["progress"][0]
    assert failure["status"] == "failed" and len(failure["details"]) > 500
    assert 'syntax error at or near "year"' in failure["details"]
    assert saved["error"] is None
    main.sessions.clear()
    assert client.get(f"/runs/{run_id}").json()["progress"] == saved["progress"]

def test_rejects_bad_uploads_and_unknown_runs(client):
    bad = client.post("/runs", files=[("prior", ("../bad.xlsx", b"bad")), ("raw", ("a.txt", b"notes"))])
    assert bad.status_code == 400
    assert not list(main.ROOT.iterdir())
    assert client.get("/runs/nope/download").status_code == 404
    invalid = client.post("/runs", files=[("prior", ("bad.xlsx", b"not a workbook")), ("raw", ("a.txt", b"notes"))])
    assert invalid.status_code == 400


def test_saved_submission_restores_chat_native_session_and_output_after_restart(client):
    run_id = create(client).json()["run_id"]
    client.post(f"/runs/{run_id}/chat", json={"message": "Make a plan", "selection": "Sheet!B2"})
    folder = main.ROOT / run_id
    shutil.copyfile(folder / "prior" / "submission.xlsx", folder / "output" / "submission.xlsx")
    assert client.get("/runs").json()[0]["run_id"] == run_id
    saved = client.get(f"/runs/{run_id}").json()
    assert saved["messages"][0] == {"role": "user", "text": "Make a plan", "selection": "Sheet!B2"}
    assert saved["has_output"] is True
    assert "session" not in saved
    main.sessions.clear()
    reopened = client.get(f"/runs/{run_id}").json()
    assert reopened == saved
    response = client.post(f"/runs/{run_id}/chat", json={"message": "Continue"})
    assert "Previous message: Make a plan" in response.text
    assert main.sessions[run_id].turn == 2
    assert len(client.get(f"/runs/{run_id}").json()["messages"]) == 4
    assert client.get(f"/runs/{run_id}/download").status_code == 200


def test_failed_turn_preserves_partial_chat_but_restores_last_complete_checkpoint(client):
    run_id = create(client).json()["run_id"]
    client.post(f"/runs/{run_id}/chat", json={"message": "Make a plan"})
    client.post(f"/runs/{run_id}/chat", json={"message": "fail"})
    detail = client.get(f"/runs/{run_id}").json()
    assert detail["messages"][-1]["text"] == "Partial response"
    assert "Test failure" in detail["error"]
    assert detail["progress"][-1]["status"] == "failed"
    main.sessions.clear()
    retry = client.post(f"/runs/{run_id}/chat", json={"message": "Retry"})
    assert "Previous message: Make a plan" in retry.text
    assert main.sessions[run_id].turn == 2


def test_interrupted_and_legacy_submissions_are_explicit_and_resumable(client):
    run_id = create(client).json()["run_id"]
    folder = main.ROOT / run_id
    path = folder / "submission.json"
    saved = json.loads(path.read_text())
    saved["in_progress"] = True
    path.write_text(json.dumps(saved), encoding="utf-8")
    assert "interrupted" in client.get(f"/runs/{run_id}").json()["notice"]
    path.unlink()
    assert "no saved chat" in client.get(f"/runs/{run_id}").json()["notice"]
    assert client.get("/runs").json()[0]["name"] == "submission"
    assert client.post(f"/runs/{run_id}/chat", json={"message": "Inspect existing files"}).status_code == 200
    assert main.sessions[run_id].turn == 1
    assert path.exists()


def test_corrupt_state_is_not_overwritten_or_silently_reset(client):
    run_id = create(client).json()["run_id"]
    path = main.ROOT / run_id / "submission.json"
    path.write_text("{bad json", encoding="utf-8")
    assert client.get(f"/runs/{run_id}").status_code == 500
    assert client.post(f"/runs/{run_id}/chat", json={"message": "Continue"}).status_code == 500
    assert client.get("/runs").json()[0]["unavailable"]
    assert path.read_text() == "{bad json"


def test_optional_name_and_concurrent_turn_protection(client):
    prior = ROOT / "samples" / "harborview" / "prior" / "submission_2025.xlsx"
    response = client.post("/runs", data={"name": "Harborview renewal"}, files=[
        ("prior", ("submission.xlsx", prior.read_bytes())),
        ("raw", ("notes.md", b"Roll to 2026")),
    ])
    run_id = response.json()["run_id"]
    assert client.get(f"/runs/{run_id}").json()["name"] == "Harborview renewal"
    client.post(f"/runs/{run_id}/chat", json={"message": "Make a plan"})
    session = main.sessions[run_id]
    asyncio.run(session.lock.acquire())
    try:
        assert client.get(f"/runs/{run_id}").json()["busy"] is True
        assert client.post(f"/runs/{run_id}/chat", json={"message": "Second tab"}).status_code == 409
        assert len(client.get(f"/runs/{run_id}").json()["messages"]) == 2
    finally:
        session.lock.release()


def test_invalid_native_checkpoint_is_reported_without_resetting_saved_work(client):
    run_id = create(client).json()["run_id"]
    path = main.ROOT / run_id / "submission.json"
    saved = json.loads(path.read_text())
    saved["session"] = {"state": {}}
    path.write_text(json.dumps(saved), encoding="utf-8")
    original = path.read_bytes()
    response = client.post(f"/runs/{run_id}/chat", json={"message": "Continue"})
    assert response.status_code == 500
    assert "checkpoint could not be restored" in response.text
    assert path.read_bytes() == original
    assert not main.sessions[run_id].lock.locked()


def test_initial_save_failure_does_not_start_agent_or_keep_lock(client, monkeypatch):
    run_id = create(client).json()["run_id"]
    path = main.ROOT / run_id / "submission.json"
    original = path.read_bytes()

    def fail(*args):
        raise OSError("Disk full")

    monkeypatch.setattr(main, "save_submission", fail)
    response = client.post(f"/runs/{run_id}/chat", json={"message": "Make a plan"})
    assert response.status_code == 500
    assert "agent has not been started" in response.text
    assert main.sessions[run_id].turn == 0
    assert not main.sessions[run_id].lock.locked()
    assert path.read_bytes() == original


def test_closing_stream_retains_partial_chat_and_releases_lock(client):
    run_id = create(client).json()["run_id"]

    async def disconnect():
        response = await main.chat(run_id, main.ChatInput(message="Inspect"))
        first = await anext(response.body_iterator)
        assert first["event"] == "text"
        await response.body_iterator.aclose()

    asyncio.run(disconnect())
    saved = client.get(f"/runs/{run_id}").json()
    assert saved["messages"][-1]["text"].startswith("Plan ready.")
    assert "interrupted" in saved["error"]
    assert not main.sessions[run_id].lock.locked()
    snapshot = json.loads((main.ROOT / run_id / "submission.json").read_text())
    assert snapshot["turn"] == 0
    assert snapshot["session"] is None
    assert snapshot["in_progress"] is False


def test_rerun_copies_only_original_inputs_and_starts_a_fresh_submission(client):
    identifier = create(client).json()["run_id"]
    client.post(f"/runs/{identifier}/chat", json={"message": "Make a plan"})
    source = main.ROOT / identifier
    (source / "output" / "submission.xlsx").write_bytes(b"old output")
    (source / "work" / "intermediate.txt").write_text("old work")
    before = {str(path.relative_to(source)): path.read_bytes() for path in source.rglob("*") if path.is_file()}
    response = client.post(f"/runs/{identifier}/rerun")
    assert response.status_code == 200
    new_id = response.json()["run_id"]
    assert new_id != identifier
    target = main.ROOT / new_id
    assert (target / "prior" / "submission.xlsx").read_bytes() == (source / "prior" / "submission.xlsx").read_bytes()
    assert (target / "raw" / "notes.md").read_bytes() == (source / "raw" / "notes.md").read_bytes()
    assert not list((target / "output").iterdir()) and not list((target / "work").iterdir())
    saved = client.get(f"/runs/{new_id}").json()
    assert saved["messages"] == [] and saved["progress"] == [] and saved["has_output"] is False
    checkpoint = json.loads((target / "submission.json").read_text())
    assert checkpoint["turn"] == 0 and checkpoint["session"] is None
    assert saved["name"].endswith("(rerun)")
    assert before == {str(path.relative_to(source)): path.read_bytes() for path in source.rglob("*") if path.is_file()}
    assert "Previous message: " in client.post(f"/runs/{new_id}/chat", json={"message": "Inspect"}).text
    assert main.sessions[new_id].turn == 1


def test_delete_removes_only_the_selected_submission_and_closes_its_session(client):
    first = create(client).json()["run_id"]
    other = create(client).json()["run_id"]
    client.post(f"/runs/{first}/chat", json={"message": "Inspect"})
    session = main.sessions[first]
    response = client.delete(f"/runs/{first}")
    assert response.status_code == 200 and response.json()["deleted"] is True
    assert session.closed and first not in main.sessions
    assert not (main.ROOT / first).exists()
    assert client.get(f"/runs/{first}").status_code == 404
    assert client.get(f"/runs/{other}").status_code == 200
    assert [item["run_id"] for item in client.get("/runs").json()] == [other]
    assert client.delete("/runs/not-a-uuid").status_code == 404


def test_busy_submissions_cannot_be_deleted_or_rerun(client):
    identifier = create(client).json()["run_id"]
    client.post(f"/runs/{identifier}/chat", json={"message": "Inspect"})
    session = main.sessions[identifier]
    asyncio.run(session.lock.acquire())
    try:
        assert client.delete(f"/runs/{identifier}").status_code == 409
        assert client.post(f"/runs/{identifier}/rerun").status_code == 409
        assert len(client.get("/runs").json()) == 1
    finally:
        session.lock.release()


def test_failed_rerun_does_not_change_source_or_leave_an_empty_submission(client, monkeypatch):
    identifier = create(client).json()["run_id"]
    source = main.ROOT / identifier
    before = (source / "submission.json").read_bytes()

    def fail(*args):
        raise OSError("Disk full")

    monkeypatch.setattr(main.shutil, "copyfile", fail)
    assert client.post(f"/runs/{identifier}/rerun").status_code == 500
    assert (source / "submission.json").read_bytes() == before
    assert [path.name for path in main.ROOT.iterdir()] == [identifier]


def test_delete_failure_is_explicit_and_releases_the_session_lock(client, monkeypatch):
    identifier = create(client).json()["run_id"]
    client.post(f"/runs/{identifier}/chat", json={"message": "Inspect"})
    session = main.sessions[identifier]

    def fail(*args):
        raise PermissionError("Workbook is open")

    monkeypatch.setattr(main.shutil, "rmtree", fail)
    response = client.delete(f"/runs/{identifier}")
    assert response.status_code == 500
    assert "could not be fully deleted" in response.json()["detail"]
    assert (main.ROOT / identifier).exists()
    assert not session.lock.locked()
    assert identifier not in main.sessions
