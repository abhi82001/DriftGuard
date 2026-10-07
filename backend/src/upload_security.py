"""Bounded local upload boundary. Reverse proxy must independently cap request bodies.

No MIME trust, no path use, no execution. The API key is optional only for local
DEMO operation; deployment guide requires an authenticated perimeter.
"""
from __future__ import annotations

import hmac
import os
from pathlib import PurePath
from zipfile import BadZipFile, ZipFile
from io import BytesIO

from fastapi import HTTPException, Request
from ingestion import MAX_BYTES, MAX_FILES, SUPPORTED

MAX_UPLOAD_FILES = MAX_FILES
MAX_TOTAL_BYTES = 100 * 1024 * 1024


def authorize_api(request: Request) -> None:
    configured = os.getenv('DRIFTGUARD_API_KEY', '')
    if configured and not hmac.compare_digest(request.headers.get('x-driftguard-api-key', ''), configured):
        raise HTTPException(status_code=401, detail='Unauthorized')


def validate_file(filename: str, data: bytes) -> str:
    if not filename or filename in ('.', '..') or '/' in filename or '\\' in filename or '\x00' in filename:
        raise HTTPException(status_code=400, detail='Invalid upload filename')
    if len(filename) > 180 or any(ord(c) < 32 for c in filename):
        raise HTTPException(status_code=400, detail='Invalid upload filename')
    extension = PurePath(filename).suffix.lower()
    if extension not in SUPPORTED:
        raise HTTPException(status_code=415, detail='Unsupported file extension')
    if not data:
        raise HTTPException(status_code=400, detail='Empty upload')
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413, detail='File exceeds configured size limit')
    if extension == '.pdf' and not data.lstrip().startswith(b'%PDF-'):
        raise HTTPException(status_code=415, detail='Invalid PDF signature')
    if extension in ('.docx', '.xlsx'):
        try:
            with ZipFile(BytesIO(data)) as archive:
                names = set(archive.namelist())
                expected = 'word/document.xml' if extension == '.docx' else 'xl/workbook.xml'
                if expected not in names:
                    raise HTTPException(status_code=415, detail='Invalid office document structure')
                unsafe = [n for n in names if n.lower().endswith(('.bin','.vba')) or 'externallinks/' in n.lower()]
                if unsafe:
                    raise HTTPException(status_code=415, detail='Active or externally linked office content is not accepted')
                # Reject zip bombs before any parser is invoked.
                if len(names) > 10000 or sum(x.file_size for x in archive.infolist()) > 100 * 1024 * 1024:
                    raise HTTPException(status_code=413, detail='Expanded document exceeds safety limit')
        except BadZipFile as exc:
            raise HTTPException(status_code=415, detail='Invalid office document') from exc
    return filename


async def read_uploads(form) -> list[tuple[str, bytes]]:
    uploads = [f for f in form.getlist('files') if getattr(f, 'filename', '')]
    if len(uploads) > MAX_UPLOAD_FILES:
        raise HTTPException(status_code=413, detail='Too many uploaded files')
    payloads = []
    total = 0
    for upload in uploads:
        data = await upload.read(MAX_BYTES + 1)
        name = validate_file(upload.filename, data)
        total += len(data)
        if total > MAX_TOTAL_BYTES:
            raise HTTPException(status_code=413, detail='Total upload size exceeded')
        payloads.append((name, data))
    return payloads
