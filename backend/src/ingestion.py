#!/usr/bin/env python3
"""Minimal local document text extraction. Uploaded content is data, never code
and never instructions: nothing here is executed, evaluated, or interpreted as
a directive."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from typing import Iterable
from production_hardening import neutralize_formula

MAX_FILES = 25
MAX_BYTES = 5 * 1024 * 1024
MAX_CHUNKS_PER_FILE = 400
SUPPORTED = (".pdf", ".docx", ".xlsx", ".csv", ".json", ".txt", ".md")

POLICY_WORDS = ("policy", "standard", "procedure", "charter", "guideline", "plan")


class IngestionError(Exception):
    pass


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
        raise IngestionError(f"unsupported file type {ext or filename!r}")
    if not data:
        raise IngestionError(f"{filename} is empty")
    if len(data) > MAX_BYTES:
        raise IngestionError(f"{filename} exceeds {MAX_BYTES // (1024 * 1024)} MB")

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
    except Exception as exc:  # noqa: BLE001 - malformed upload must not crash
        raise IngestionError(f"could not read {filename}: {type(exc).__name__}") from exc

    chunks = [c for c in chunks if c.text.strip()][:MAX_CHUNKS_PER_FILE]
    if not chunks:
        raise IngestionError(f"no extractable text in {filename}")
    doc_text = "\n".join(c.text for c in chunks)
    return Document(filename, _kind(filename, doc_text, ext), tuple(chunks))


def extract_many(files: Iterable[tuple[str, bytes]]) -> tuple[list[Document], list[str]]:
    docs: list[Document] = []
    errors: list[str] = []
    for i, (filename, data) in enumerate(files):
        if i >= MAX_FILES:
            errors.append(f"only the first {MAX_FILES} files were processed")
            break
        try:
            docs.append(extract(filename, data))
        except IngestionError as exc:
            errors.append(str(exc))
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
    return [
        Chunk(filename, f"page {n}", (page.extract_text() or "").strip(), segment_type="page")
        for n, page in enumerate(reader.pages, start=1)
    ]
