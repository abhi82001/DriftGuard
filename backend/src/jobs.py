"""Resumable staged job runner with checkpoints, progress and per-stage timeouts.

A job is a directory (see upload_store) holding `job.json` plus one `ckpt_<stage>.json`
per durable stage. `run` walks the stages in order; a stage whose checkpoint loads is
restored, the first stage that cannot be restored and every later one is (re)computed.
A stage that overruns its timeout fails the job with a typed code; Python cannot kill a
thread, so the overrunning stage is abandoned (its context is discarded) and never
writes a checkpoint, which only this runner does.
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from observability import ErrorCode, assessment_id_var, log_event, request_id_var

DEFAULT_TIMEOUT_S = 300.0
ACTIVE: set[str] = set()          # job ids with a live worker in this process
_ACTIVE_LOCK = threading.Lock()


@dataclass
class Stage:
    name: str
    run: Callable[[Any], None]                        # mutates ctx only
    save: Optional[Callable[[Any], Any]] = None       # -> JSON-able checkpoint payload, or None if not durable
    load: Optional[Callable[[Any, Any], None]] = None
    required: bool = True


def stage_timeout(name: str) -> float:
    for key in (f"DRIFTGUARD_STAGE_TIMEOUT_{name.upper()}", "DRIFTGUARD_STAGE_TIMEOUT"):
        raw = os.getenv(key)
        if raw:
            try:
                return max(0.01, float(raw))
            except ValueError:
                pass
    return DEFAULT_TIMEOUT_S


def _replace(tmp: Path, target: Path) -> None:
    """Atomic swap; Windows refuses while a reader holds the target open, so retry briefly."""
    for attempt in range(40):
        try:
            os.replace(tmp, target)
            return
        except PermissionError:
            if attempt == 39:
                raise
            time.sleep(0.02)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Job:
    def __init__(self, directory: Path) -> None:
        self.dir = Path(directory)
        self.path = self.dir / "job.json"

    # -- persistence ------------------------------------------------------
    def read(self) -> dict:
        for attempt in range(5):          # a concurrent atomic swap can briefly hide or lock the file
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                return {}
            except (OSError, ValueError):
                time.sleep(0.02)
        return {}

    def write(self, rec: dict) -> None:
        rec["updated_at"] = _now()
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(rec, indent=1), encoding="utf-8")
        _replace(tmp, self.path)

    def create(self, job_id: str, vendor: str, stage_names: list[str]) -> dict:
        rec = dict(job_id=job_id, vendor=vendor, state="queued", stage="", stages=stage_names, completed_stages=[],
                   progress=0, error_code="", warnings=[], attempts=0, stage_seconds={}, created_at=_now())
        self.dir.mkdir(parents=True, exist_ok=True)
        self.write(rec)
        return rec

    def status(self) -> dict:
        """Public view; a job left running with no live worker (server restart) reads as interrupted."""
        rec = self.read()
        if not rec:
            return {}
        if rec.get("state") in ("running", "queued") and rec["job_id"] not in ACTIVE:
            rec = {**rec, "state": "interrupted", "error_code": ErrorCode.JOB_INTERRUPTED.value}
        keys = ("job_id", "state", "stage", "stages", "completed_stages", "progress", "error_code", "warnings",
                "attempts", "stage_seconds", "created_at", "updated_at", "summary")
        return {k: rec[k] for k in keys if k in rec}

    def resumable(self) -> bool:
        return self.status().get("state") in ("failed", "timed_out", "interrupted")

    # -- execution --------------------------------------------------------
    def _ckpt(self, name: str) -> Path:
        return self.dir / f"ckpt_{name}.json"

    def run(self, stages: list[Stage], ctx: Any, on_complete: Optional[Callable[[Any], None]] = None) -> dict:
        rec = self.read()
        rec.update(attempts=rec.get("attempts", 0) + 1, state="running", error_code="")
        restoring = True
        done: list[str] = []
        with _ACTIVE_LOCK:
            ACTIVE.add(rec["job_id"])
        try:
            for st in stages:
                if restoring and st.name in rec.get("completed_stages", []) and st.load and self._try_load(st, ctx):
                    done.append(st.name)
                    log_event("stage_restored", stage=st.name)
                    continue
                restoring = False
                rec.update(stage=st.name, completed_stages=list(done), progress=round(100 * len(done) / len(stages)))
                self.write(rec)
                outcome, secs = self._execute(st, ctx)
                rec["stage_seconds"][st.name] = secs
                if outcome == "ok":
                    self._checkpoint(st, ctx)
                elif not st.required:
                    rec["warnings"] = [w for w in rec.get("warnings", []) if not w.startswith(st.name + ":")] + [
                        f"{st.name}: skipped ({outcome})"]
                else:
                    code = ErrorCode.STAGE_TIMEOUT if outcome == "timeout" else ErrorCode.STAGE_FAILED
                    rec.update(state="timed_out" if outcome == "timeout" else "failed", error_code=code.value,
                               completed_stages=list(done), progress=round(100 * len(done) / len(stages)))
                    self.write(rec)
                    log_event("job_stopped", code=code, level=40, stage=st.name, state=rec["state"],
                              timeout_s=stage_timeout(st.name))
                    return self.status()
                done.append(st.name)
            if on_complete is not None:
                try:
                    on_complete(ctx)
                except Exception as exc:   # noqa: BLE001 - typed code and class name only
                    rec.update(state="failed", error_code=ErrorCode.STORAGE_FAILED.value, completed_stages=list(done))
                    self.write(rec)
                    log_event("job_stopped", code=ErrorCode.STORAGE_FAILED, level=40, stage="finalize",
                              error_type=type(exc).__name__)
                    return self.status()
            summary = getattr(ctx, "summary", None)
            rec.update(state="completed", stage="", completed_stages=list(done), progress=100)
            if summary:
                rec["summary"] = summary
            self.write(rec)
            log_event("job_completed", state="completed", completed_stages=done)
            return self.status()
        finally:
            with _ACTIVE_LOCK:
                ACTIVE.discard(rec["job_id"])

    def _try_load(self, st: Stage, ctx: Any) -> bool:
        try:
            st.load(ctx, json.loads(self._ckpt(st.name).read_text(encoding="utf-8")))
            return True
        except Exception:   # noqa: BLE001 - an unreadable or undecodable checkpoint means recompute from here
            return False

    def _checkpoint(self, st: Stage, ctx: Any) -> None:
        if st.save is None:
            return
        target = self._ckpt(st.name)
        try:
            payload = st.save(ctx)
            if payload is None:
                target.unlink(missing_ok=True)
                return
            tmp = target.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            _replace(tmp, target)
        except (TypeError, ValueError, OSError):
            target.unlink(missing_ok=True)   # not durable: a resume recomputes this stage

    def _execute(self, st: Stage, ctx: Any) -> tuple[str, float]:
        box: dict = {}
        rid, aid = request_id_var.get(), assessment_id_var.get()

        def target():
            request_id_var.set(rid)
            assessment_id_var.set(aid)
            try:
                st.run(ctx)
                box["ok"] = True
            except BaseException as exc:   # noqa: BLE001 - recorded by class name only
                box["err"] = type(exc).__name__

        t0 = time.monotonic()
        t = threading.Thread(target=target, daemon=True, name=f"dg-stage-{st.name}")
        t.start()
        t.join(stage_timeout(st.name))
        secs = round(time.monotonic() - t0, 3)
        if t.is_alive():
            return "timeout", secs
        if "err" in box:
            log_event("stage_failed", code=ErrorCode.STAGE_FAILED, level=40, stage=st.name, error_type=box["err"])
            return "error", secs
        return "ok", secs
