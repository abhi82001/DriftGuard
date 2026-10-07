"""Negative upload boundary tests; local API auth remains opt-in, not enterprise RBAC."""
import asyncio
import os
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from app import app
from upload_security import validate_file
from fastapi import HTTPException

@pytest.mark.parametrize('name,data,status', [
    ('../escape.txt', b'data', 400), ('folder\\file.csv', b'a,b', 400),
    ('bad.exe', b'MZ', 415), ('empty.txt', b'', 400),
    ('fake.pdf', b'not a PDF', 415), ('fake.xlsx', b'not a zip', 415),
    pytest.param('large.txt', b'x' * (5 * 1024 * 1024 + 1), 413, id='large.txt'),
])
def test_upload_rejection(name, data, status):
    with pytest.raises(HTTPException) as error:
        validate_file(name, data)
    assert error.value.status_code == status


def test_upload_auth_and_count(monkeypatch):
    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            monkeypatch.setenv('DRIFTGUARD_API_KEY', 'test-secret')
            files = [('files', ('evidence.txt', b'hello', 'text/plain'))]
            assert (await client.post('/api/evidence-map', files=files)).status_code == 401
            headers = {'x-driftguard-api-key': 'test-secret'}
            assert (await client.post('/api/evidence-map', files=files, headers=headers)).status_code == 200
            many = [('files', (f'evidence{i}.txt', b'hello', 'text/plain')) for i in range(101)]
            assert (await client.post('/api/evidence-map', files=many, headers=headers)).status_code == 413
    asyncio.run(check())
