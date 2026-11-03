import os
import shutil
import socket
import subprocess
import sys

import pytest

from conftest import ROOT

POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")
pytestmark = pytest.mark.skipif(sys.platform != "win32" or not POWERSHELL, reason="Windows PowerShell launcher")


def test_launcher_parses():
    env = dict(os.environ, START_ALL_PATH=str(ROOT / "start-all.ps1"))
    result = subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-Command",
         "$tokens=$null; $errors=$null; "
         "[System.Management.Automation.Language.Parser]::ParseFile($env:START_ALL_PATH,[ref]$tokens,[ref]$errors) > $null; "
         "if ($errors.Count) { $errors | Out-String | Write-Error; exit 1 }"],
        env=env, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_launcher_does_not_take_over_existing_server():
    if not (ROOT / ".venv" / "Scripts" / "python.exe").is_file() or not (ROOT / "web" / "node_modules" / "next").is_dir():
        pytest.skip("Launcher prerequisites not installed.")
    with socket.socket() as blocker:
        try:
            blocker.bind(("127.0.0.1", 8000))
            blocker.listen()
        except OSError:
            pass  # An existing listener already exercises the same refusal path.
        result = subprocess.run(
            [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", str(ROOT / "start-all.ps1")],
            cwd=ROOT.parent, capture_output=True, text=True, timeout=60,
        )
    assert result.returncode != 0
    assert "Port 8000 is in use" in result.stdout + result.stderr
