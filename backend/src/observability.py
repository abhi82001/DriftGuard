"""Structured JSON logging with request/assessment ids and typed error codes.

Logs carry identifiers, counts, timings and error classes only. Evidence content,
filenames, cookies, credentials and exception messages (which can embed content) are
never written: unknown field names are dropped unless allow-listed, and values are
scrubbed for secret-shaped strings.
"""
from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
from datetime import datetime, timezone
from enum import Enum

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("dg_request_id", default="-")
assessment_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("dg_assessment_id", default="-")

LOGGER = logging.getLogger("driftguard.struct")


class ErrorCode(str, Enum):
    AUTH_REQUIRED = "DG-AUTH-001"
    NOT_FOUND = "DG-NOTFOUND-001"
    RATE_LIMITED = "DG-RATE-001"
    UPLOAD_REJECTED = "DG-UPLOAD-001"
    BAD_REQUEST = "DG-REQUEST-001"
    CROSS_SITE_REJECTED = "DG-CSRF-001"
    STAGE_FAILED = "DG-JOB-001"
    STAGE_TIMEOUT = "DG-JOB-002"
    JOB_NOT_RESUMABLE = "DG-JOB-003"
    JOB_INTERRUPTED = "DG-JOB-004"
    STORAGE_FAILED = "DG-STORE-001"
    INTERNAL = "DG-INTERNAL-001"


def code_for_status(status: int) -> ErrorCode:
    return {401: ErrorCode.AUTH_REQUIRED, 403: ErrorCode.AUTH_REQUIRED, 404: ErrorCode.NOT_FOUND,
            429: ErrorCode.RATE_LIMITED, 413: ErrorCode.UPLOAD_REJECTED, 415: ErrorCode.UPLOAD_REJECTED}.get(
        status, ErrorCode.BAD_REQUEST if 400 <= status < 500 else ErrorCode.INTERNAL)


# Only these fields are ever emitted; anything else is dropped (default-deny).
ALLOWED_FIELDS = frozenset({
    "method", "path", "status", "duration_ms", "stage", "state", "progress", "file_count", "bytes",
    "files_parsed", "parse_errors", "error_type", "attempt", "timeout_s", "action", "kind", "user_id",
    "completed_stages", "resumed_from"})
_SECRET = re.compile(r"(sk-[A-Za-z0-9_-]{8,}|Bearer\s+\S+|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_.-]+|"
                     r"(?i:(password|secret|token|api[_-]?key)\s*[=:]\s*\S+))")


def _clean(value):
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in list(value)[:20]]
    return _SECRET.sub("[redacted]", str(value))[:200]


def log_event(event: str, *, code: ErrorCode | None = None, level: int = logging.INFO, **fields) -> dict:
    record = {"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), "level": logging.getLevelName(level),
              "event": event, "request_id": request_id_var.get(), "assessment_id": assessment_id_var.get()}
    if code is not None:
        record["error_code"] = code.value
    record.update({k: _clean(v) for k, v in fields.items() if k in ALLOWED_FIELDS})
    LOGGER.log(level, json.dumps(record, sort_keys=True, ensure_ascii=True))
    return record


def configure() -> None:
    """One JSON-lines handler on stderr; idempotent and left alone if the host app configured its own."""
    if LOGGER.handlers:
        return
    h = logging.StreamHandler(sys.stderr)
    h.setFormatter(logging.Formatter("%(message)s"))
    LOGGER.addHandler(h)
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = True


_REQUEST_ID_OK = re.compile(r"^[A-Za-z0-9-]{8,64}$")
_PATH_AID = re.compile(r"/([0-9a-f]{32})(?:[/?#]|$)")


def new_request_id(inbound: str | None) -> str:
    import uuid
    return inbound if inbound and _REQUEST_ID_OK.match(inbound) else uuid.uuid4().hex[:16]


def assessment_id_from_path(path: str) -> str:
    m = _PATH_AID.search(path)
    return m.group(1) if m else "-"
