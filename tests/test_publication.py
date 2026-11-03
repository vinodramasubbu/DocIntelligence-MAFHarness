import asyncio
import hashlib
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font

from api.publication import WorkbookPublisher


@pytest.fixture
def publisher(tmp_path):
    for folder in ("prior", "raw", "work", "output"):
        (tmp_path / folder).mkdir()
    book = Workbook()
    book.active["A1"] = "Premium"
    book.active["A1"].font = Font(bold=True)
    book.active["B2"] = 100
    book.active["B3"] = "=SUM(B2:B2)"
    book.save(tmp_path / "prior" / "template.xlsx")
    book.close()
    return WorkbookPublisher(tmp_path)


def write_candidate(publisher):
    candidate = publisher.prepare()
    candidate.write_bytes((publisher.root / "prior" / "template.xlsx").read_bytes())
    return candidate


def test_missing_current_candidate_cannot_be_published(publisher):
    with pytest.raises(ValueError, match="this turn's candidate"):
        asyncio.run(publisher.publish())
    write_candidate(publisher)
    publisher.prepare()
    with pytest.raises(ValueError, match="this turn's candidate"):
        asyncio.run(publisher.publish())
    assert not list((publisher.root / "output").iterdir())


def test_publish_preserves_original_and_requires_independent_validation(publisher, monkeypatch):
    prior = publisher.root / "prior" / "template.xlsx"
    original = hashlib.sha256(prior.read_bytes()).digest()
    write_candidate(publisher)
    validated = []

    def check(path):
        validated.append(path)
        assert path != str(publisher.candidate)
        return {"valid": True, "recalculated": True}

    monkeypatch.setattr("api.publication.check", check)
    result = asyncio.run(publisher.publish())
    assert result["published"] is True and validated
    output = publisher.root / "output" / "submission.xlsx"
    book = load_workbook(output)
    assert book.active["B2"].value == 100
    assert book.active["B3"].value == "=SUM(B2:B2)"
    assert book.active["A1"].font.bold
    book.close()
    assert hashlib.sha256(prior.read_bytes()).digest() == original
    assert not list((publisher.root / "work").glob("candidate-*.xlsx"))


def test_invalid_candidate_does_not_replace_existing_output(publisher, monkeypatch):
    output = publisher.root / "output" / "submission.xlsx"
    output.write_bytes(b"existing approved output")
    write_candidate(publisher)
    monkeypatch.setattr("api.publication.check", lambda path: {"valid": False, "recalculated": False})
    with pytest.raises(ValueError, match="not published"):
        asyncio.run(publisher.publish())
    assert output.read_bytes() == b"existing approved output"


def test_malformed_candidate_is_rejected(publisher):
    publisher.prepare().write_bytes(b"not an Excel archive")
    with pytest.raises(ValueError, match="valid XLSX"):
        asyncio.run(publisher.publish())
    assert not list((publisher.root / "output").iterdir())


def test_oversized_candidate_is_rejected_before_copy(publisher):
    candidate = publisher.prepare()
    with candidate.open("wb") as file:
        file.truncate(30 * 1024 * 1024 + 1)
    with pytest.raises(ValueError, match="30 MB"):
        asyncio.run(publisher.publish())
    assert not list((publisher.root / "work").glob("candidate-*.xlsx"))


def test_inflated_candidate_limit_is_enforced(publisher, monkeypatch):
    write_candidate(publisher)
    monkeypatch.setattr("api.publication.ZipFile", lambda path: nullcontext(SimpleNamespace(
        infolist=lambda: [SimpleNamespace(file_size=151 * 1024 * 1024)],
    )))
    with pytest.raises(ValueError, match="150 MB"):
        asyncio.run(publisher.publish())
    assert not list((publisher.root / "output").iterdir())
