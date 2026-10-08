#!/usr/bin/env python3
"""Minimal local document text extraction. Uploaded content is data, never code
and never instructions: nothing here is executed, evaluated, or interpreted as
a directive."""

from __future__ import annotations

import csv
import hashlib
import io
import os
from dataclasses import dataclass, asdict
from typing import Iterable
from production_hardening import neutralize_formula

MAX_FILES = 25
MAX_BYTES = 5 * 1024 * 1024
MAX_CHUNKS_PER_FILE = 400
SUPPORTED = (".pdf", ".docx", ".xlsx", ".csv", ".json", ".txt", ".md")

POLICY_WORDS = ("policy", "standard", "procedure", "charter", "guideline", "plan")


# Typed extraction statuses. All of them describe *unread material*; none is
# "missing evidence" or a negative control result.
EXTRACTED = "EXTRACTED"
UNREADABLE_SCAN_NEEDS_OCR = "UNREADABLE_SCAN_NEEDS_OCR"
ENCRYPTED_OR_DEPENDENCY_MISSING = "ENCRYPTED_OR_DEPENDENCY_MISSING"
CORRUPT = "CORRUPT"
UNSUPPORTED = "UNSUPPORTED"
DUPLICATE = "DUPLICATE"
EXTRACTION_STATUSES = (EXTRACTED, UNREADABLE_SCAN_NEEDS_OCR, ENCRYPTED_OR_DEPENDENCY_MISSING,
                       CORRUPT, UNSUPPORTED, DUPLICATE)

_PIP_NAMES = {"docx": "python-docx", "cryptography": "cryptography", "openpyxl": "openpyxl", "pypdf": "pypdf"}


class IngestionError(Exception):
    def __init__(self, message: str = "", status: str = CORRUPT, remediation: str = ""):
        super().__init__(message)
        self.status = status
        self.remediation = remediation


@dataclass(frozen=True)
class ExtractionResult:
    filename: str
    status: str
    detail: str = ""
    remediation: str = ""
    sha256: str = ""
    duplicate_of: str = ""
    note: str = "Unread material is not evidence of a missing or failed control."

    def to_dict(self) -> dict:
        return asdict(self)

    def message(self) -> str:
        return f"{self.status}: {self.detail}" + (f" Next step: {self.remediation}" if self.remediation else "")


def ocr_enabled() -> bool:
    return os.getenv("DRIFTGUARD_OCR", "").strip().lower() in ("1", "true", "yes", "on")


def ocr_missing_requirements() -> list[str]:
    """Optional OCR libraries not importable here (the Tesseract binary is checked at use)."""
    import importlib.util
    return [m for m in ("pytesseract", "pypdfium2") if importlib.util.find_spec(m) is None]


_TESSERACT_WINDOWS_PATHS = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
)


def find_tesseract() -> str | None:
    """Tesseract executable: TESSERACT_CMD, then PATH, then the standard Windows install folders."""
    import shutil
    explicit = os.getenv("TESSERACT_CMD", "").strip().strip('"')
    if explicit and os.path.isfile(explicit):
        return explicit
    on_path = shutil.which("tesseract")
    if on_path:
        return on_path
    return next((p for p in _TESSERACT_WINDOWS_PATHS if os.path.isfile(p)), None)


@dataclass(frozen=True)
class Chunk:
    filename: str
    locator: str          # "page 12" | "sheet Users row 4" | "paragraph 7" | "line 3"
    text: str
    heading: str = ""
    segment_type: str = "text"


@dataclass(frozen=True)
class Document:
    filename: str
    kind: str             # policy | artifact
    chunks: tuple[Chunk, ...]

    @property
    def text(self) -> str:
        return "\n".join(c.text for c in self.chunks)


def _ext(filename: str) -> str:
    return ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""


def _kind(filename: str, text: str, ext: str) -> str:
    if any(w in filename.lower() for w in POLICY_WORDS):
        return "policy"
    if ext in (".csv", ".xlsx"):        # tabular exports are artifacts, not prose
        return "artifact"
    head = text[:1500].lower()
    return "policy" if any(w in head for w in POLICY_WORDS) else "artifact"


def extract(filename: str, data: bytes) -> Document:
    ext = _ext(filename)
    if ext not in SUPPORTED:
        raise IngestionError(f"unsupported file type {ext or filename!r}", UNSUPPORTED,
                             "Convert to one of: " + ", ".join(SUPPORTED) + ".")
    if not data:
        raise IngestionError(f"{filename} is empty", CORRUPT, "Re-export the file; it contains no bytes.")
    if len(data) > MAX_BYTES:
        raise IngestionError(f"{filename} exceeds {MAX_BYTES // (1024 * 1024)} MB", UNSUPPORTED,
                             "Split or reduce the file below the size limit.")

    try:
        if ext in (".txt", ".md"):
            chunks = _plain(filename, data)
        elif ext == ".csv":
            chunks = _csv(filename, data)
        elif ext == ".json":
            chunks = _json(filename, data)
        elif ext == ".xlsx":
            chunks = _xlsx(filename, data)
        elif ext == ".docx":
            chunks = _docx(filename, data)
        else:
            chunks = _pdf(filename, data)
    except IngestionError:
        raise
    except ModuleNotFoundError as exc:
        pkg = _PIP_NAMES.get((exc.name or "").split(".")[0], exc.name or "the missing package")
        raise IngestionError(f"could not read {filename}: optional dependency {pkg!r} is not installed",
                             ENCRYPTED_OR_DEPENDENCY_MISSING, f"pip install {pkg}") from exc
    except Exception as exc:  # noqa: BLE001 - malformed upload must not crash
        if type(exc).__name__ == "DependencyError":      # pypdf: AES-encrypted PDF needs cryptography
            raise IngestionError(
                f"could not read {filename}: encrypted PDF needs the optional 'cryptography' package",
                ENCRYPTED_OR_DEPENDENCY_MISSING, "pip install cryptography") from exc
        raise IngestionError(f"could not read {filename}: {type(exc).__name__}", CORRUPT,
                             "Re-export or re-download the file; it could not be parsed.") from exc

    chunks = [c for c in chunks if c.text.strip()][:MAX_CHUNKS_PER_FILE]
    if not chunks and ext == ".pdf":
        chunks = _ocr_or_raise(filename, data)
    if not chunks:
        raise IngestionError(f"no extractable text in {filename}", UNSUPPORTED,
                             "The file has no readable content; supply a text-bearing export.")
    doc_text = "\n".join(c.text for c in chunks)
    return Document(filename, _kind(filename, doc_text, ext), tuple(chunks))


def extract_many_detailed(files: Iterable[tuple[str, bytes]]):
    """Return (documents, errors, per-file ExtractionResult list, unique payloads).

    Byte-identical files are de-duplicated by SHA-256 and reported once as
    DUPLICATE; a duplicate is not an error and is not processed twice.
    """
    docs: list[Document] = []
    errors: list[str] = []
    records: list[ExtractionResult] = []
    unique: list[tuple[str, bytes]] = []
    seen: dict[str, str] = {}
    for i, (filename, data) in enumerate(files):
        if i >= MAX_FILES:
            errors.append(f"only the first {MAX_FILES} files were processed")
            break
        digest = hashlib.sha256(data).hexdigest()
        if digest in seen:
            records.append(ExtractionResult(
                filename, DUPLICATE, f"{filename} is byte-identical to {seen[digest]}; processed once.",
                "No action needed; remove the duplicate upload.", digest, seen[digest]))
            continue
        seen[digest] = filename
        unique.append((filename, data))
        try:
            docs.append(extract(filename, data))
            records.append(ExtractionResult(filename, EXTRACTED, "", "", digest))
        except IngestionError as exc:
            rec = ExtractionResult(filename, exc.status, str(exc), exc.remediation, digest)
            records.append(rec)
            errors.append(rec.message())
    return docs, errors, records, unique


def extract_many(files: Iterable[tuple[str, bytes]]) -> tuple[list[Document], list[str]]:
    docs, errors, _records, _unique = extract_many_detailed(files)
    return docs, errors


def _decode(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def _plain(filename: str, data: bytes) -> list[Chunk]:
    out, buf, start = [], [], 1
    for n, line in enumerate(_decode(data).splitlines(), start=1):
        if line.strip():
            buf.append(line.strip())
        elif buf:
            out.append(Chunk(filename, f"lines {start}-{n - 1}", " ".join(buf)))
            buf, start = [], n + 1
        if not buf:
            start = n + 1
    if buf:
        out.append(Chunk(filename, f"lines {start}-", " ".join(buf)))
    return out


def _csv(filename: str, data: bytes) -> list[Chunk]:
    rows = list(csv.reader(io.StringIO(_decode(data))))
    return [
        Chunk(filename, f"row {n}", " | ".join(neutralize_formula(c).strip() for c in row if str(c).strip()), segment_type="table_row")
        for n, row in enumerate(rows, start=1)
    ]


def _json(filename: str, data: bytes) -> list[Chunk]:
    """Parse bounded JSON as data; keep key paths and source attribution."""
    import json
    try:
        value = json.loads(data.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise IngestionError(f"invalid JSON in {filename}") from exc
    out: list[Chunk] = []
    def walk(item, path: str, depth: int) -> None:
        if depth > 16 or len(out) >= MAX_CHUNKS_PER_FILE:
            return
        if isinstance(item, dict):
            for key, child in item.items():
                walk(child, f"{path}.{key}", depth + 1)
        elif isinstance(item, list):
            for i, child in enumerate(item):
                walk(child, f"{path}[{i}]", depth + 1)
        elif item is not None:
            out.append(Chunk(filename, path, f"{path}: {item}"))
    walk(value, "$", 0)
    return out


def _xlsx(filename: str, data: bytes) -> list[Chunk]:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    out = []
    for ws in wb.worksheets:
        for n, row in enumerate(ws.iter_rows(values_only=True), start=1):
            cells = [neutralize_formula(c).strip() for c in row if c is not None and str(c).strip()]
            if cells:
                out.append(Chunk(filename, f"sheet {ws.title} row {n}", " | ".join(cells), heading=ws.title, segment_type="table_row"))
    wb.close()
    return out


def _docx(filename: str, data: bytes) -> list[Chunk]:
    import docx

    document = docx.Document(io.BytesIO(data))
    out = []
    current_heading = ""
    for n, p in enumerate(document.paragraphs, start=1):
        text = p.text.strip()
        if not text:
            continue
        style = (getattr(getattr(p, "style", None), "name", "") or "").lower()
        is_heading = style.startswith("heading") or style in {"title", "subtitle"}
        if is_heading:
            current_heading = text
        out.append(Chunk(filename, f"paragraph {n}", text, heading=current_heading,
                         segment_type="heading" if is_heading else "paragraph"))
    for t, table in enumerate(document.tables, start=1):
        for r, row in enumerate(table.rows, start=1):
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                out.append(Chunk(filename, f"table {t} row {r}", " | ".join(cells), heading=current_heading, segment_type="table_row"))
    return out


def _pdf(filename: str, data: bytes) -> list[Chunk]:
    import logging

    from pypdf import PdfReader

    logging.getLogger("pypdf").setLevel(logging.CRITICAL)

    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        # The empty user password covers owner-restricted PDFs; a real password is never guessed.
        if not reader.decrypt(""):
            raise IngestionError(f"could not read {filename}: password-protected PDF",
                                 ENCRYPTED_OR_DEPENDENCY_MISSING,
                                 "Supply an unencrypted copy; DriftGuard does not guess passwords.")
    return [
        Chunk(filename, f"page {n}", (page.extract_text() or "").strip(), segment_type="page")
        for n, page in enumerate(reader.pages, start=1)
    ]


def _ocr_or_raise(filename: str, data: bytes) -> list[Chunk]:
    """Image-only PDF: OCR behind DRIFTGUARD_OCR=1 when libraries exist, else a typed status."""
    steps = ("pip install pytesseract pypdfium2, install the Tesseract OCR binary yourself "
             "(DriftGuard does not install system binaries), then set DRIFTGUARD_OCR=1")
    if not ocr_enabled():
        raise IngestionError(f"no extractable text in {filename}: image-only scan", UNREADABLE_SCAN_NEEDS_OCR,
                             f"Provide a text-searchable copy, or enable OCR: {steps}.")
    missing = ocr_missing_requirements()
    if missing:
        raise IngestionError(f"no extractable text in {filename}: image-only scan; OCR requested but "
                             f"{', '.join(missing)} not installed", UNREADABLE_SCAN_NEEDS_OCR,
                             f"pip install {' '.join(missing)} and install the Tesseract OCR binary.")
    try:
        import pypdfium2
        import pytesseract
        binary = find_tesseract()
        if binary:
            pytesseract.pytesseract.tesseract_cmd = binary
        pdf = pypdfium2.PdfDocument(data)
        out = []
        for n in range(len(pdf)):
            text = pytesseract.image_to_string(pdf[n].render(scale=2).to_pil()).strip()
            if text:
                out.append(Chunk(filename, f"page {n + 1} (OCR)", text, segment_type="ocr_page"))
    except Exception as exc:  # noqa: BLE001 - OCR engine/binary failure must not crash ingestion
        raise IngestionError(f"no extractable text in {filename}: OCR failed ({type(exc).__name__})",
                             UNREADABLE_SCAN_NEEDS_OCR,
                             f"Check the Tesseract binary is installed and on PATH ({steps}).") from exc
    if not out:
        raise IngestionError(f"no extractable text in {filename}: OCR found no text", UNREADABLE_SCAN_NEEDS_OCR,
                             "Provide a clearer or text-searchable copy.")
    return out
