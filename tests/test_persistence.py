from datetime import datetime, timezone
import ctypes
import os
from pathlib import Path
import threading

import pytest

from api.persistence import Submission, load_submission, save_submission


def test_atomic_replace_failure_preserves_previous_snapshot(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    original = Submission(name="Original", created_at=now, updated_at=now)
    save_submission(tmp_path, original)
    snapshot = (tmp_path / "submission.json").read_bytes()

    def fail(*args):
        raise OSError("Disk write failed")

    monkeypatch.setattr(Path, "replace", fail)
    original.name = "Changed"
    with pytest.raises(OSError, match="Disk write failed"):
        save_submission(tmp_path, original)
    assert (tmp_path / "submission.json").read_bytes() == snapshot
    assert not list(tmp_path.glob(".submission-*.tmp"))
    assert load_submission(tmp_path).name == "Original"


def windows_error(code):
    error = PermissionError("Windows denied replacement")
    error.winerror = code
    return error


@pytest.mark.parametrize("code", [5, 32, 33])
def test_windows_replacement_failure_retries_same_complete_snapshot(tmp_path, monkeypatch, caplog, code):
    now = datetime.now(timezone.utc)
    submission = Submission(name="Original", created_at=now, updated_at=now)
    save_submission(tmp_path, submission)
    original = (tmp_path / "submission.json").read_bytes()
    replace = Path.replace
    calls = []
    delays = []

    def temporarily_locked(source, target):
        calls.append(source)
        assert (tmp_path / "submission.json").read_bytes() == original
        assert Submission.model_validate_json(source.read_text()).name == "Changed"
        if len(calls) <= 2:
            raise windows_error(code)
        return replace(source, target)

    monkeypatch.setattr(Path, "replace", temporarily_locked)
    monkeypatch.setattr("api.persistence.time.sleep", delays.append)
    submission.name = "Changed"
    save_submission(tmp_path, submission)
    assert len(calls) == 3 and len(set(calls)) == 1
    assert delays == [0.05, 0.1]
    assert "retrying" in caplog.text
    assert load_submission(tmp_path).name == "Changed"
    assert not list(tmp_path.glob(".submission-*.tmp"))


def test_persistent_windows_denial_is_bounded_and_preserves_snapshot(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    submission = Submission(name="Original", created_at=now, updated_at=now)
    save_submission(tmp_path, submission)
    original = (tmp_path / "submission.json").read_bytes()
    calls = []
    delays = []

    def denied(source, target):
        calls.append(source)
        raise windows_error(5)

    monkeypatch.setattr(Path, "replace", denied)
    monkeypatch.setattr("api.persistence.time.sleep", delays.append)
    submission.name = "Changed"
    with pytest.raises(PermissionError):
        save_submission(tmp_path, submission)
    assert len(calls) == 7
    assert sum(delays) == pytest.approx(3.15)
    assert (tmp_path / "submission.json").read_bytes() == original
    assert not list(tmp_path.glob(".submission-*.tmp"))


def test_other_windows_errors_are_not_retried(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    submission = Submission(name="Original", created_at=now, updated_at=now)
    delays = []

    def fail(source, target):
        raise windows_error(112)

    monkeypatch.setattr(Path, "replace", fail)
    monkeypatch.setattr("api.persistence.time.sleep", delays.append)
    with pytest.raises(PermissionError):
        save_submission(tmp_path, submission)
    assert delays == []
    assert not list(tmp_path.glob(".submission-*.tmp"))


@pytest.mark.skipif(os.name != "nt", reason="Windows file sharing semantics")
def test_real_windows_reader_lock_recovers_without_losing_checkpoint(tmp_path):
    from ctypes import wintypes

    now = datetime.now(timezone.utc)
    submission = Submission(name="Original", created_at=now, updated_at=now)
    save_submission(tmp_path, submission)
    path = tmp_path / "submission.json"
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = (
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    )
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    # Permit reads/writes but not deletion, as an external reader can on Windows.
    handle = kernel.CreateFileW(str(path), 0x80000000, 3, None, 3, 0x80, None)
    assert handle != ctypes.c_void_p(-1).value, ctypes.get_last_error()
    probe = tmp_path / "probe.tmp"
    probe.write_text("replacement", encoding="utf-8")
    release = None
    released = []

    def unlock():
        released.append(bool(kernel.CloseHandle(handle)))

    try:
        with pytest.raises(PermissionError) as blocked:
            probe.replace(path)
        assert blocked.value.winerror in (5, 32, 33)
        release = threading.Timer(0.15, unlock)
        release.start()
        submission.name = "Recovered"
        save_submission(tmp_path, submission)
    finally:
        if release is None:
            unlock()
        else:
            release.join()
        probe.unlink(missing_ok=True)
    assert released == [True]
    assert load_submission(tmp_path).name == "Recovered"
    assert not list(tmp_path.glob(".submission-*.tmp"))
