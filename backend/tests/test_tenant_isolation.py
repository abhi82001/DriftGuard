"""User B must not read, export, delete, compare or resume user A's assessments, files or jobs, on any route."""
import pytest

import dg_helpers as h
from dg_helpers import webapp

VENDOR = "Zephyr-Confidential-Vendor"


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("DRIFTGUARD_REQUIRE_AUTH", "1")
    h.use_tmp_uploads(monkeypatch, tmp_path)
    webapp._RATE_BUCKETS.clear()


@pytest.fixture
def world():
    a, b = h.register(h.make_client(), "a"), h.register(h.make_client(), "b")
    anon = h.make_client()
    aid = h.analyze(a, VENDOR)
    rid = a.post("/run", data={"vendor": VENDOR}).headers["location"].rsplit("/", 1)[-1]
    return a, b, anon, aid, rid


def _a_routes(aid, rid):
    return [("GET", f"/doc-results/{aid}"), ("GET", f"/results/{rid}"), ("GET", f"/export/{aid}"),
            ("GET", f"/export-pdf/{aid}"), ("GET", f"/evidence-report/{aid}"), ("GET", f"/gaps/{aid}"),
            ("GET", f"/gaps-csv/{aid}"), ("GET", f"/audit-trail/{aid}"), ("GET", f"/audit-trail/{aid}?format=csv"),
            ("POST", f"/clarify/{aid}"), ("GET", f"/jobs/{aid}"), ("POST", f"/jobs/{aid}/resume")]


def test_owner_can_use_every_route(world):
    a, _b, _anon, aid, rid = world
    for method, path in _a_routes(aid, rid):
        if path.startswith("/jobs/"):
            continue                       # no job exists for a synchronous analysis
        r = a.request(method, path, data={} if method == "POST" else None)
        assert r.status_code in (200, 303), (path, r.status_code)


def test_other_user_gets_nothing_from_any_route(world):
    a, b, anon, aid, rid = world
    for method, path in _a_routes(aid, rid):
        r = b.request(method, path, data={} if method == "POST" else None)
        assert r.status_code == 404, (method, path, r.status_code)
        assert VENDOR not in r.text and aid not in r.text.replace(path, ""), (path, "leaked")
        r = anon.request(method, path, data={} if method == "POST" else None)
        assert r.status_code in (303, 401, 403, 404), (method, path, r.status_code)
        assert VENDOR not in r.text, (path, "leaked to anonymous")


def test_isolation_holds_after_cache_loss_and_for_both_users(world):
    a, b, _anon, aid, rid = world
    webapp.DOC_ASSESSMENTS.pop(aid), webapp.ASSESSMENTS.pop(rid)
    webapp._ASSESSMENT_OWNERS.clear()
    for method, path in _a_routes(aid, rid):
        assert b.request(method, path, data={} if method == "POST" else None).status_code == 404, path
    assert a.get(f"/export/{aid}").status_code == 200           # owner is re-authorised from the database
    assert a.get(f"/doc-results/{aid}").status_code == 200 and a.get(f"/results/{rid}").status_code == 200


def test_other_user_cannot_delete_rename_archive_or_purge(world):
    a, b, _anon, aid, rid = world
    for action in ("rename", "archive", "unarchive", "delete", "restore", "purge"):
        assert b.post(f"/my-assessments/{action}", data={"kind": "doc-results", "aid": aid, "label": "x"}).status_code == 404, action
    uid_a = h.uid_of(a)
    assert webapp._accounts().load_saved(uid_a, "doc-results", aid) is not None
    assert webapp.UPLOADS.exists(uid_a, aid)                      # A's stored files untouched
    assert a.get(f"/doc-results/{aid}").status_code == 200


def test_other_user_cannot_compare_or_see_in_listing(world):
    a, b, _anon, aid, rid = world
    mine = h.analyze(b, "B vendor")
    r = b.get("/my-assessments/compare", params=[("pick", f"doc-results:{aid}"), ("pick", f"doc-results:{mine}")])
    assert r.status_code == 404 and VENDOR not in r.text
    r = b.get("/my-assessments/compare", params=[("pick", f"results:{rid}"), ("pick", f"doc-results:{mine}")])
    assert r.status_code == 404
    listing = b.get("/my-assessments")
    # B's own activity log echoes the ids B itself submitted; A's items must not be listed or linked.
    assert VENDOR not in listing.text
    assert f"/doc-results/{aid}" not in listing.text and f"/results/{rid}" not in listing.text
    assert "B vendor" in listing.text


def test_deleted_assessment_is_gone_for_owner_and_stays_gone_for_others(world):
    a, b, _anon, aid, _rid = world
    assert a.post("/my-assessments/delete", data={"kind": "doc-results", "aid": aid}).status_code == 303
    for who in (a, b):
        for path in (f"/doc-results/{aid}", f"/export/{aid}", f"/audit-trail/{aid}", f"/evidence-report/{aid}"):
            assert who.get(path).status_code == 404, path


def test_guest_assessments_are_not_visible_to_users_and_vice_versa(world):
    a, b, _anon, aid, _rid = world
    g = h.make_client()
    assert g.post("/guest/start").status_code in (200, 303)
    r = g.post("/guest/sample")
    assert r.status_code == 303
    gid = r.headers["location"].rsplit("/", 1)[-1]
    assert a.get(f"/doc-results/{gid}").status_code == 404
    assert g.get(f"/doc-results/{aid}").status_code == 404
    for path in (f"/export/{gid}", f"/audit-trail/{gid}", f"/gaps/{gid}"):
        assert g.get(path).status_code in (403, 404)               # guests have no export access
