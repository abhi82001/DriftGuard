#!/usr/bin/env python3
"""CP019 step 2: typed extraction statuses, dependency hints, de-duplication, OCR flag."""
import io
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
os.environ["DRIFTGUARD_DEMO_MODE"] = "1"

import ingestion  # noqa: E402
from ingestion import (CORRUPT, DUPLICATE, ENCRYPTED_OR_DEPENDENCY_MISSING, EXTRACTED,  # noqa: E402
                       UNREADABLE_SCAN_NEEDS_OCR, UNSUPPORTED, IngestionError, extract, extract_many_detailed)

pypdf = pytest.importorskip("pypdf")


def _blank_pdf(password=None) -> bytes:
    w = pypdf.PdfWriter()
    w.add_blank_page(200, 200)
    if password:
        w.encrypt(password)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def _status(name, data):
    with pytest.raises(IngestionError) as e:
        extract(name, data)
    return e.value


def test_image_only_pdf_is_unreadable_scan_needing_ocr(monkeypatch):
    monkeypatch.delenv("DRIFTGUARD_OCR", raising=False)
    err = _status("scan.pdf", _blank_pdf())
    assert err.status == UNREADABLE_SCAN_NEEDS_OCR
    assert "DRIFTGUARD_OCR=1" in err.remediation and "does not install system binaries" in err.remediation


def test_ocr_flag_without_libraries_still_unread_and_names_the_install(monkeypatch):
    monkeypatch.setenv("DRIFTGUARD_OCR", "1")
    monkeypatch.setattr(ingestion, "ocr_missing_requirements", lambda: ["pytesseract"])
    err = _status("scan.pdf", _blank_pdf())
    assert err.status == UNREADABLE_SCAN_NEEDS_OCR and "pip install pytesseract" in err.remediation


def test_password_protected_pdf_is_encrypted_status():
    err = _status("locked.pdf", _blank_pdf("secret"))
    assert err.status == ENCRYPTED_OR_DEPENDENCY_MISSING and "password" in str(err)


def test_missing_cryptography_dependency_names_exact_install(monkeypatch):
    class DependencyError(Exception):
        pass

    def boom(filename, data):
        raise DependencyError("cryptography>=3.1 is required for AES algorithm")
    monkeypatch.setattr(ingestion, "_pdf", boom)
    err = _status("enc.pdf", b"%PDF-1.7")
    assert err.status == ENCRYPTED_OR_DEPENDENCY_MISSING and err.remediation == "pip install cryptography"


def test_missing_python_package_maps_to_pip_name(monkeypatch):
    def boom(filename, data):
        raise ModuleNotFoundError("No module named 'docx'", name="docx")
    monkeypatch.setattr(ingestion, "_docx", boom)
    assert _status("a.docx", b"x").remediation == "pip install python-docx"


def test_corrupt_and_unsupported_statuses():
    assert _status("bad.pdf", b"%PDF-1.7 not really a pdf").status == CORRUPT
    assert _status("empty.txt", b"").status == CORRUPT
    assert _status("tool.exe", b"MZ").status == UNSUPPORTED


def test_byte_identical_files_are_reported_once_as_duplicate_not_error():
    data = b"Multi-factor authentication is required for all employees."
    docs, errors, records, unique = extract_many_detailed([("a.txt", data), ("b.txt", data), ("c.txt", b"other text here")])
    assert [r.status for r in records] == [EXTRACTED, DUPLICATE, EXTRACTED]
    assert len(docs) == 2 and len(unique) == 2 and errors == []
    dup = records[1]
    assert dup.duplicate_of == "a.txt" and dup.sha256 == records[0].sha256


def test_unread_material_message_never_says_missing_evidence(monkeypatch):
    monkeypatch.delenv("DRIFTGUARD_OCR", raising=False)
    _, errors, records, _ = extract_many_detailed([("scan.pdf", _blank_pdf())])
    assert errors[0].startswith(UNREADABLE_SCAN_NEEDS_OCR)
    assert "missing evidence" not in errors[0].lower() and "unread material" in records[0].note.lower()


def test_analyze_payloads_carries_status_per_file_and_dedupes(monkeypatch):
    monkeypatch.delenv("DRIFTGUARD_OCR", raising=False)
    import app as webapp
    text = b"Access Control Policy\n\nMulti-factor authentication is required for all administrators."
    result = webapp.analyze_payloads("v", [("policy_a.txt", text), ("policy_b.txt", text), ("scan.pdf", _blank_pdf())])
    by_name = {r["filename"]: r["status"] for r in result.extraction}
    assert by_name == {"policy_a.txt": EXTRACTED, "policy_b.txt": DUPLICATE, "scan.pdf": UNREADABLE_SCAN_NEEDS_OCR}
    assert result.files_received == 3 and len(result.documents) == 1 and len(result.errors) == 1


def test_find_tesseract_prefers_env_then_windows_install(monkeypatch, tmp_path):
    exe = tmp_path / "tesseract.exe"
    exe.write_bytes(b"")
    monkeypatch.setenv("TESSERACT_CMD", str(exe))
    assert ingestion.find_tesseract() == str(exe)
    monkeypatch.delenv("TESSERACT_CMD")
    monkeypatch.setattr("shutil.which", lambda _n: None)
    monkeypatch.setattr(ingestion, "_TESSERACT_WINDOWS_PATHS", (str(exe),))
    assert ingestion.find_tesseract() == str(exe)
    monkeypatch.setattr(ingestion, "_TESSERACT_WINDOWS_PATHS", (str(tmp_path / "missing.exe"),))
    assert ingestion.find_tesseract() is None
