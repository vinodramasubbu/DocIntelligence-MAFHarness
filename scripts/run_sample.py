"""Live Foundry acceptance test; sends synthetic files only, never the answer key."""
import argparse
import asyncio
import hashlib
import json
import math
import shutil
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from api.agent import RunAgent
from scripts.create_samples import PACK_NAMES
from openpyxl import load_workbook


async def run(name: str):
    sample = ROOT / "samples" / name
    root = ROOT / "runs" / str(uuid4())
    for folder in ("prior", "raw", "work", "output"):
        (root / folder).mkdir(parents=True)
    for folder in ("prior", "raw"):
        for path in (sample / folder).iterdir():
            shutil.copyfile(path, root / folder / path.name)
    prior = next((root / "prior").iterdir())
    original = hashlib.sha256(prior.read_bytes()).digest()
    agent = RunAgent(root)
    try:
        for message in (
            "Inspect every template region and raw file. Propose a plan, then STOP for my approval. Do not write a workbook.",
            "Go ahead. Apply the plan, validate, and publish output/submission.xlsx.",
        ):
            async for event, data in agent.stream(message):
                print(data.get("text", ""), end="\n" if event == "progress" else "", flush=True)
            print()
            if message.startswith("Inspect") and (root / "output" / "submission.xlsx").exists():
                raise AssertionError("Approval gate violated.")
            if message.startswith("Inspect"):
                checkpoint = json.loads(json.dumps(agent.session.to_dict()))
                turn = agent.turn
                await agent.close()
                agent = RunAgent(root)
                agent.restore(checkpoint, turn)
        output = root / "output" / "submission.xlsx"
        assert output.exists(), f"Agent did not publish output. Inspect {root}"
        key = json.loads((sample / "answer_key.md").read_text().split("```json\n")[1].split("```")[0])
        assert hashlib.sha256(prior.read_bytes()).digest() == original, "Prior was changed."
        for category, data_only in (("cells", False), ("calculated", True)):
            wb = load_workbook(output, data_only=data_only)
            for address, expected in key[category].items():
                sheet, cell = address.rsplit("!", 1)
                actual = wb[sheet][cell].value
                assert math.isclose(actual, expected, rel_tol=1e-8) if isinstance(expected, (int, float)) and isinstance(actual, (int, float)) else actual == expected, f"{address}: expected {expected!r}, got {actual!r}"
            wb.close()
        print(f"\nPASS {name}: approval gate, saved-session resume, original hash, cell values and recalculated totals. Output: {output}")
    finally:
        await agent.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("sample", choices=PACK_NAMES)
    args = parser.parse_args()
    asyncio.run(run(args.sample))
