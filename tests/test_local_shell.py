import asyncio
import json
import os
from pathlib import Path

from agent_framework.tools import LocalShellTool

from conftest import ROOT


def test_native_local_shell_uses_project_python_and_persistent_files(tmp_path):
    async def verify():
        shell = LocalShellTool(
            mode="stateless", workdir=tmp_path,
            env={"PATH": str(ROOT / ".venv" / "Scripts") + os.pathsep + os.environ["PATH"]},
            approval_mode="never_require", acknowledge_unsafe=True, timeout=15,
        )
        try:
            result = await shell.run(
                'python -c "import json,sys; from pathlib import Path; '
                "Path('generated.txt').write_text('kept'); "
                'print(json.dumps([sys.executable,str(Path.cwd())]))"; exit $LASTEXITCODE'
            )
            assert result.exit_code == 0
            executable, cwd = json.loads(result.stdout)
            assert Path(executable) == ROOT / ".venv" / "Scripts" / "python.exe"
            assert Path(cwd) == tmp_path
            second = await shell.run(
                'python -c "from pathlib import Path; print(Path(\'generated.txt\').read_text())"; exit $LASTEXITCODE'
            )
            assert second.exit_code == 0 and second.stdout.strip() == "kept"
        finally:
            await shell.close()
    asyncio.run(verify())


def test_native_result_parser_preserves_failure_metadata(tmp_path):
    async def verify():
        shell = LocalShellTool(
            mode="stateless", workdir=tmp_path, timeout=15,
            env={"PATH": str(ROOT / ".venv" / "Scripts") + os.pathsep + os.environ["PATH"]},
            approval_mode="never_require", acknowledge_unsafe=True,
        )
        try:
            function = shell.as_function()
            result = await function.invoke(arguments={
                "command": 'python -c "import sys; sys.stderr.write(\'bad year\'); sys.exit(7)"; exit $LASTEXITCODE',
            }, skip_parsing=True)
            parsed = function.result_parser(result)
            assert parsed[0].additional_properties["exit_code"] == 7
            assert "bad year" in parsed[0].additional_properties["stderr"]
        finally:
            await shell.close()
    asyncio.run(verify())
