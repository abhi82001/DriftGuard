"""Snapshots (run stamp + input file hashes per saved run) and the evidence-to-question audit trail."""
import csv
import hashlib
import io
from datetime import date

import pytest

import dg_helpers as h
from dg_helpers import PACK, webapp
from evidence import audit_trail as at
from evidence.reproducibility import canonical_result

AS_OF = date(2026, 10, 8)


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("DRIFTGUARD_REQUIRE_AUTH", "1")
    h.use_tmp_uploads(monkeypatch, tmp_path)
    webapp._RATE_BUCKETS.clear()


def test_run_stamp_records_per_file_hashes():
    r = webapp.analyze_payloads("v", PACK, assessment_date=AS_OF)
    got = {f["filename"]: f for f in r.run_stamp["input_files"]}
    assert set(got) == {n for n, _ in PACK}
    for name, data in PACK:
        assert got[name]["sha256"] == hashlib.sha256(data).hexdigest() and got[name]["bytes"] == len(data)


def test_identical_inputs_give_identical_results_and_stamp():
    a = webapp.analyze_payloads("v", PACK, assessment_date=AS_OF)
    b = webapp.analyze_payloads("v", list(reversed(PACK)), assessment_date=AS_OF)   # upload order must not matter
    assert a.assessment_id != b.assessment_id
    assert canonical_result(a) == canonical_result(b)
    assert a.run_stamp == b.run_stamp
    c = webapp.analyze_payloads("v", [PACK[0], (PACK[1][0], PACK[1][1] + b"carol,user,true\n")], assessment_date=AS_OF)
    assert c.run_stamp["input_hash"] != a.run_stamp["input_hash"]


def test_stamp_and_hashes_survive_save_and_reload_through_the_app():
    c = h.register(h.make_client())
    first, second = h.analyze(c), h.analyze(c)
    blobs = [webapp._accounts().load_saved(h.uid_of(c), "doc-results", x) for x in (first, second)]
    saved = [webapp._deserialize_state(b) for b in blobs]
    assert saved[0].run_stamp["input_hash"] == saved[1].run_stamp["input_hash"]
    assert saved[0].run_stamp["input_files"] == saved[1].run_stamp["input_files"]
    assert {f["sha256"] for f in saved[0].run_stamp["input_files"]} == {hashlib.sha256(d).hexdigest() for _, d in PACK}
    assert canonical_result(saved[0]) == canonical_result(saved[1])      # same inputs, same result, after a round trip
    export = c.get(f"/export/{first}").json()
    assert export["run_stamp"]["input_files"] == saved[0].run_stamp["input_files"]


def _trail(c, aid, **q):
    return c.get(f"/audit-trail/{aid}", params=q)


def test_audit_trail_links_file_fact_question_and_locator():
    c = h.register(h.make_client())
    aid = h.analyze(c)
    trail = _trail(c, aid).json()
    assert trail["row_count"] == len(trail["rows"]) > 0
    names = {n for n, _ in PACK}
    digests = {hashlib.sha256(d).hexdigest() for _, d in PACK}
    for row in trail["rows"]:
        assert row["file"] in names and row["file_sha256"] in digests
        assert row["question_id"] and row["fact"] and "locator" in row
    # query one question: only its rows
    qid = trail["rows"][0]["question_id"]
    one = _trail(c, aid, question=qid).json()
    assert one["rows"] and {r["question_id"] for r in one["rows"]} == {qid}
    assert one["row_count"] < trail["row_count"] or len({r["question_id"] for r in trail["rows"]}) == 1
    assert _trail(c, aid, question="QN-NOPE-999").status_code == 404
    # questions with no linked evidence are listed, not silently dropped
    assert set(trail["questions_without_evidence"]).isdisjoint({r["question_id"] for r in trail["rows"]})


def test_audit_trail_csv_export_and_formula_neutralised():
    c = h.register(h.make_client())
    aid = h.analyze(c)
    r = _trail(c, aid, format="csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert rows and set(at.COLUMNS) == set(rows[0])
    assert at.to_csv({"rows": [dict.fromkeys(at.COLUMNS, "=HYPERLINK(1)")]}).splitlines()[1].startswith("'=HYPERLINK")


def test_audit_trail_survives_cache_loss():
    c = h.register(h.make_client())
    aid = h.analyze(c)
    before = _trail(c, aid).json()
    webapp.DOC_ASSESSMENTS.pop(aid)
    assert _trail(c, aid).json() == before
