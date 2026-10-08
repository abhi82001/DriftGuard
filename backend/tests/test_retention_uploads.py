"""Stored uploads: sanitized names, owner-scoped storage, removal on delete/purge/expiry."""
import json
from datetime import datetime, timedelta, timezone

import pytest

import dg_helpers as h
from dg_helpers import PACK, webapp
from upload_store import UploadStore, sanitize_filename


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("DRIFTGUARD_REQUIRE_AUTH", "1")
    h.use_tmp_uploads(monkeypatch, tmp_path)
    webapp._RATE_BUCKETS.clear()


@pytest.mark.parametrize("raw", ["../../etc/passwd", "..\\..\\boot.ini", "CON.txt", "nul", ".hidden.csv", "a" * 400 + ".csv",
                                 "rep ort (final)?.xlsx", "naïve–名前.txt", "x\x00y.txt", "   .csv", "NUL"])
def test_sanitized_names_cannot_traverse_or_collide_with_devices(raw):
    s = sanitize_filename(raw)
    assert s and len(s) <= 100
    assert not any(c in s for c in '/\\:*?"<>|\x00 ') and not s.startswith(".")
    assert s.split(".")[0].lower() not in {"con", "nul", "prn", "aux"}


def test_files_are_stored_under_sanitized_names_with_integrity_check(tmp_path):
    store = UploadStore(tmp_path / "s")
    aid = "ab" * 16
    manifest = store.save(7, aid, [("../../evil name.csv", b"a,b\n1,2\n"), ("../../evil name.csv", b"a,b\n3,4\n")])
    stored = sorted(p.name for p in (tmp_path / "s" / "u7" / aid).iterdir())
    assert stored == ["000_evil_name.csv", "001_evil_name.csv", "manifest.json"]      # same name twice cannot collide
    assert store.load(7, aid) == [("../../evil name.csv", b"a,b\n1,2\n"), ("../../evil name.csv", b"a,b\n3,4\n")]
    (tmp_path / "s" / "u7" / aid / "000_evil_name.csv").write_bytes(b"tampered")
    with pytest.raises(ValueError):
        store.load(7, aid)
    assert manifest[0]["original"] == "../../evil name.csv"                         # original kept only in the manifest


@pytest.mark.parametrize("uid,aid", [(1, "../x"), (1, "g" * 32), (1, "ab" * 15), (-1, "ab" * 16), ("1", "ab" * 16)])
def test_store_rejects_ids_that_could_escape_the_root(tmp_path, uid, aid):
    with pytest.raises(ValueError):
        UploadStore(tmp_path).dir_for(uid, aid)


def test_upload_stored_for_signed_in_user_and_removed_on_delete(tmp_path):
    c = h.register(h.make_client())
    aid = h.analyze(c)
    uid = h.uid_of(c)
    d = webapp.UPLOADS.dir_for(uid, aid)
    assert {m["original"] for m in json.loads((d / "manifest.json").read_text())} == {n for n, _ in PACK}
    assert c.post("/my-assessments/delete", data={"kind": "doc-results", "aid": aid}).status_code == 303
    assert not d.exists()                                                           # raw evidence gone immediately
    assert webapp._accounts().load_saved(uid, "doc-results", aid) is None           # state hidden
    assert c.get(f"/doc-results/{aid}").status_code == 404 and c.get(f"/export/{aid}").status_code == 404
    assert webapp.DOC_ASSESSMENTS.get(aid) is None and ("doc-results", aid) not in webapp._ASSESSMENT_OWNERS
    meta = [r for r in webapp._accounts().list_saved(uid, deleted=True) if r.aid == aid]
    assert meta, "soft-deleted row stays restorable until retention expires"
    assert c.post("/my-assessments/purge", data={"kind": "doc-results", "aid": aid}).status_code == 303
    assert not [r for r in webapp._accounts().list_saved(uid, deleted=True) if r.aid == aid]
    assert not any(p for p in (tmp_path / "uploads" / f"u{uid}").glob("*") if p.name == aid)


def test_expired_trash_is_purged_with_its_files(monkeypatch, tmp_path):
    c = h.register(h.make_client())
    aid = h.analyze(c)
    uid = h.uid_of(c)
    c.post("/my-assessments/delete", data={"kind": "doc-results", "aid": aid})
    d = webapp.UPLOADS.dir_for(uid, aid)
    d.mkdir(parents=True)                                                           # simulate a leftover directory
    (d / "000_x.csv").write_text("a")
    far = (datetime.now(timezone.utc) + timedelta(days=400)).isoformat()
    monkeypatch.setattr(webapp, "_now_iso", lambda: far)
    c.get("/my-assessments")
    assert not d.exists()
    assert not [r for r in webapp._accounts().list_saved(uid, deleted=True) if r.aid == aid]


def _age(path, seconds):
    import os
    import time
    t = time.time() - seconds
    for p in [path, *path.iterdir()]:
        os.utime(p, (t, t))


def test_orphaned_directories_are_swept_but_live_fresh_and_running_ones_are_not():
    c = h.register(h.make_client())
    keep = h.analyze(c)
    uid = h.uid_of(c)
    mk = lambda aid, state=None: (webapp.UPLOADS.dir_for(uid, aid).mkdir(parents=True), 
                                  (webapp.UPLOADS.dir_for(uid, aid) / "000_a.csv").write_text("a"),
                                  state and (webapp.UPLOADS.dir_for(uid, aid) / "job.json").write_text(json.dumps({"state": state})),
                                  webapp.UPLOADS.dir_for(uid, aid))[-1]
    old_orphan, fresh, running = mk("cd" * 16), mk("ef" * 16), mk("12" * 16, "running")
    _age(old_orphan, 3600), _age(running, 3600)
    c.get("/my-assessments")
    assert webapp.UPLOADS.exists(uid, keep)
    assert not old_orphan.exists()          # old and unreferenced: swept
    assert fresh.exists()                   # row may not be written yet: protected by the grace window
    assert running.exists()                 # a running job is never swept


def test_other_users_files_are_untouched_by_delete_and_sweep():
    a, b = h.register(h.make_client(), "a"), h.register(h.make_client(), "b")
    aid = h.analyze(a)
    b.post("/my-assessments/delete", data={"kind": "doc-results", "aid": aid})
    b.post("/my-assessments/purge", data={"kind": "doc-results", "aid": aid})
    b.get("/my-assessments")
    assert webapp.UPLOADS.exists(h.uid_of(a), aid) and a.get(f"/doc-results/{aid}").status_code == 200
