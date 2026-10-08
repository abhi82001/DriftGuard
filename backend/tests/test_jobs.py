"""Staged background job: checkpoints, resume, progress, per-stage timeouts, status endpoint, ownership."""
import json
import time

import pytest

import dg_helpers as h
from dg_helpers import PACK, webapp
from evidence.reproducibility import canonical_result
import jobs as J

STAGES = ["extract", "classify", "validate", "map", "sufficiency", "report"]


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("DRIFTGUARD_REQUIRE_AUTH", "1")
    h.use_tmp_uploads(monkeypatch, tmp_path)
    webapp._RATE_BUCKETS.clear()


def _submit(c, payloads=PACK):
    r = c.post("/jobs", data={"vendor": "Job Vendor"}, files=h.files(payloads))
    assert r.status_code == 202, r.text
    return r.json()


# ---- runner unit tests (fake stages) --------------------------------------------------------------------------------
class Ctx:
    def __init__(self):
        self.vals, self.summary = {}, None


def _runner(tmp_path, calls, fail_at=None, sleep_at=None, durable=True):
    def mk(name):
        def run(c):
            calls.append(name)
            if name == fail_at:
                raise RuntimeError("boom SECRET-CONTENT")
            if name == sleep_at:
                time.sleep(2)
            c.vals[name] = len(calls)
        return J.Stage(name, run, (lambda c, n=name: {"v": c.vals[n]}) if durable else None,
                       lambda c, p, n=name: c.vals.__setitem__(n, p["v"]) if durable else None)
    job = J.Job(tmp_path / "job")
    job.create("j" * 32, "v", STAGES[:4])
    return job, [mk(n) for n in STAGES[:4]]


def test_runner_checkpoints_progress_and_resumes_from_failed_stage(tmp_path):
    calls = []
    job, stages = _runner(tmp_path, calls, fail_at="validate")
    st = job.run(stages, Ctx())
    assert st["state"] == "failed" and st["error_code"] == "DG-JOB-001" and st["stage"] == "validate"
    assert st["completed_stages"] == ["extract", "classify"] and st["progress"] == 50
    assert "SECRET-CONTENT" not in json.dumps(job.read())              # exception text is never stored
    calls.clear()
    job, stages = _runner(tmp_path / "x", calls)                       # same layout, healthy stages
    (tmp_path / "x" / "job").mkdir(parents=True, exist_ok=True)
    for f in (tmp_path / "job").iterdir():
        (tmp_path / "x" / "job" / f.name).write_bytes(f.read_bytes())
    ctx = Ctx()
    st = J.Job(tmp_path / "x" / "job").run(stages, ctx)
    assert st["state"] == "completed" and st["progress"] == 100 and st["attempts"] == 2
    assert calls == ["validate", "map"]                                # extract/classify restored, not re-run
    assert set(ctx.vals) == {"extract", "classify", "validate", "map"}


def test_runner_timeout_is_typed_and_abandons_the_stage(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTGUARD_STAGE_TIMEOUT_CLASSIFY", "0.1")
    calls = []
    job, stages = _runner(tmp_path, calls, sleep_at="classify")
    t0 = time.monotonic()
    st = job.run(stages, Ctx())
    assert time.monotonic() - t0 < 1.5
    assert st["state"] == "timed_out" and st["error_code"] == "DG-JOB-002" and st["stage"] == "classify"
    assert job.resumable() and not (tmp_path / "job" / "ckpt_classify.json").exists()


def test_non_durable_stage_is_recomputed_on_resume(tmp_path):
    calls = []
    job, stages = _runner(tmp_path, calls, durable=False)
    assert job.run(stages, Ctx())["state"] == "completed"
    assert not list((tmp_path / "job").glob("ckpt_*"))
    calls.clear()
    job.run(stages, Ctx())
    assert calls == ["extract", "classify", "validate", "map"]


def test_optional_stage_failure_is_a_warning_not_a_failed_job(tmp_path):
    ok = J.Stage("a", lambda c: None)
    bad = J.Stage("b", lambda c: 1 / 0, required=False)
    job = J.Job(tmp_path / "j")
    job.create("k" * 32, "v", ["a", "b"])
    st = job.run([ok, bad], Ctx())
    assert st["state"] == "completed" and st["warnings"] == ["b: skipped (error)"]


def test_running_job_without_a_worker_reads_as_interrupted(tmp_path):
    job = J.Job(tmp_path / "j")
    rec = job.create("m" * 32, "v", ["a"])
    rec["state"] = "running"
    job.write(rec)
    assert job.status()["state"] == "interrupted" and job.status()["error_code"] == "DG-JOB-004" and job.resumable()


# ---- end to end through HTTP ---------------------------------------------------------------------------------------
def test_job_completes_with_progress_status_and_same_result_as_synchronous_run():
    c = h.register(h.make_client())
    made = _submit(c)
    aid = made["job_id"]
    assert made["status_url"] == f"/jobs/{aid}" and made["stages"] == STAGES
    st = h.wait_job(c, aid)
    assert st["state"] == "completed", st
    assert st["completed_stages"] == STAGES and st["progress"] == 100 and st["result_url"] == f"/doc-results/{aid}"
    assert set(st["stage_seconds"]) == set(STAGES)
    assert st["summary"]["sufficiency"]["requirements"] > 0 and st["summary"]["report"]["questions"] > 0
    assert c.get(st["result_url"]).status_code == 200
    job_result = webapp._deserialize_state(webapp._accounts().load_saved(h.uid_of(c), "doc-results", aid))
    sync_result = webapp.analyze_payloads("Job Vendor", PACK)
    assert job_result.assessment_id == aid
    assert canonical_result(job_result) == canonical_result(sync_result)         # background path == synchronous path
    assert job_result.run_stamp["input_hash"] == sync_result.run_stamp["input_hash"]
    assert c.get(f"/audit-trail/{aid}").json()["row_count"] > 0


def test_stage_timeout_then_resume_does_not_redo_finished_stages(monkeypatch):
    c = h.register(h.make_client())
    real_extract, real_validate = webapp._st_extract, webapp._st_validate
    counts = {"extract": 0}

    def counting_extract(ctx):
        counts["extract"] += 1
        real_extract(ctx)

    monkeypatch.setattr(webapp, "_st_extract", counting_extract)
    monkeypatch.setattr(webapp, "_st_validate", lambda ctx: time.sleep(3))
    monkeypatch.setenv("DRIFTGUARD_STAGE_TIMEOUT_VALIDATE", "0.2")
    aid = _submit(c)["job_id"]
    st = h.wait_job(c, aid)
    assert st["state"] == "timed_out" and st["error_code"] == "DG-JOB-002" and st["stage"] == "validate"
    assert st["completed_stages"] == ["extract", "classify"] and st["progress"] == 33
    assert c.get(f"/doc-results/{aid}").status_code == 404                        # nothing is published for a failed job
    monkeypatch.setattr(webapp, "_st_validate", real_validate)
    monkeypatch.delenv("DRIFTGUARD_STAGE_TIMEOUT_VALIDATE")
    assert c.post(f"/jobs/{aid}/resume").status_code == 202
    st = h.wait_job(c, aid)
    assert st["state"] == "completed" and st["attempts"] == 2
    assert counts["extract"] == 1                                                  # restored from its checkpoint
    assert c.get(f"/doc-results/{aid}").status_code == 200


def test_resume_is_refused_for_completed_job_and_for_other_users():
    a, b = h.register(h.make_client(), "a"), h.register(h.make_client(), "b")
    aid = _submit(a)["job_id"]
    assert h.wait_job(a, aid)["state"] == "completed"
    assert a.post(f"/jobs/{aid}/resume").status_code == 409
    assert a.post(f"/jobs/{aid}/resume").json()["error_code"] == "DG-JOB-003"
    assert b.get(f"/jobs/{aid}").status_code == 404 and b.post(f"/jobs/{aid}/resume").status_code == 404
    assert h.make_client().get(f"/jobs/{aid}").status_code in (303, 401)
    assert h.make_client().post("/jobs", files=h.files()).status_code in (303, 401)


def test_interrupted_job_resumes_from_real_checkpoints_without_recomputing(monkeypatch):
    c = h.register(h.make_client())
    aid = _submit(c)["job_id"]
    assert h.wait_job(c, aid)["state"] == "completed"
    d = webapp.UPLOADS.dir_for(h.uid_of(c), aid)
    assert {p.name for p in d.glob("ckpt_*")} >= {"ckpt_extract.json", "ckpt_validate.json", "ckpt_map.json"}   # durable, not skipped
    before = webapp._deserialize_state(webapp._accounts().load_saved(h.uid_of(c), "doc-results", aid))
    job = J.Job(d)
    rec = job.read()
    rec.update(state="running", completed_stages=["extract", "classify", "validate", "map"])
    job.write(rec)                                                                 # worker died after the map stage
    assert c.get(f"/jobs/{aid}").json()["state"] == "interrupted"
    ran = []
    for name in ("_st_extract", "_st_classify", "_st_validate", "_st_map"):
        monkeypatch.setattr(webapp, name, lambda ctx, n=name: ran.append(n))
    assert c.post(f"/jobs/{aid}/resume").status_code == 202
    st = h.wait_job(c, aid)
    assert st["state"] == "completed" and ran == []                                # all four restored from checkpoints
    after = webapp._deserialize_state(webapp._accounts().load_saved(h.uid_of(c), "doc-results", aid))
    assert canonical_result(after) == canonical_result(before) and after.assessment_id == aid


def test_job_rejects_empty_and_invalid_uploads():
    c = h.register(h.make_client())
    assert c.post("/jobs", data={"vendor": "x"}).status_code == 400
    assert c.post("/jobs", files=[("files", ("evil.exe", b"MZ"))]).status_code == 415
