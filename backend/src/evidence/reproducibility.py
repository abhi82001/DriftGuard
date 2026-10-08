#!/usr/bin/env python3
"""Run reproducibility: canonical (comparable) result form and a run stamp.

The stamp records the input hash, the assessment date actually used, and a
version stamp for the engine, grammar, knowledge base and authority rules, so
two runs are comparable. ``canonical_result`` drops volatile fields (assessment
ids, timestamps) and sorts every collection so equal inputs give equal output.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date
from pathlib import Path
from typing import Iterable, Optional

ENGINE_VERSION = "CP019.1"
AUTHORITY_RULES_VERSION = "1.0.0"
VOLATILE_KEYS = frozenset({"assessment_id", "created_at", "timestamp", "generated_at", "correlation_id", "result_id"})


def input_hash(payloads: Iterable[tuple[str, bytes]]) -> str:
    """Order-independent SHA-256 over (filename, content-hash) pairs."""
    pairs = sorted((name, hashlib.sha256(data).hexdigest()) for name, data in payloads)
    return hashlib.sha256(json.dumps(pairs).encode()).hexdigest()


def knowledge_hash(root: Optional[Path] = None) -> str:
    from evaluation.engine import resolve_knowledge_root
    base = Path(root) if root else resolve_knowledge_root()
    h = hashlib.sha256()
    for p in sorted(base.rglob("*.json")):
        h.update(p.relative_to(base).as_posix().encode())
        h.update(hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()


def run_stamp(payloads, assessment_date: Optional[date], ai_status: str = "DETERMINISTIC_ONLY") -> dict:
    from evaluation.engine import GAP_GRAMMAR_VERSION
    return dict(
        input_hash=input_hash(payloads),
        assessment_date=(assessment_date or date.today()).isoformat(),
        assessment_date_source="supplied" if assessment_date else "system date (not supplied)",
        engine_version=ENGINE_VERSION,
        grammar_version=GAP_GRAMMAR_VERSION,
        knowledge_hash=knowledge_hash(),
        authority_rules_version=AUTHORITY_RULES_VERSION,
        ai_status=ai_status,
        ocr_enabled=os.getenv("DRIFTGUARD_OCR", "").strip().lower() in ("1", "true", "yes", "on"),
    )


def _plain(value):
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0])) if k not in VOLATILE_KEYS}
    if isinstance(value, (set, frozenset)):
        return sorted((_plain(v) for v in value), key=lambda v: json.dumps(v, sort_keys=True, default=str))
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if hasattr(value, "__dataclass_fields__"):
        return _plain({k: getattr(value, k) for k in value.__dataclass_fields__})
    return value


def canonical_result(result) -> dict:
    """A deterministic, comparable view of a DocumentAssessment (no ids/timestamps)."""
    def key(x):
        return json.dumps(x, sort_keys=True, default=str)
    questions = []
    for a in result.areas:
        q = _plain(a)
        for k in ("known_facts", "missing_facts", "evidence_needed", "scoped_observations",
                  "context_sources", "rejected_sources", "conflict_details", "detail_ids"):
            if k in q:
                q[k] = sorted(q[k], key=key)
        questions.append(q)
    questions.sort(key=lambda q: (q["questionnaire_id"], q["question_id"]))
    g = getattr(result, "evidence_graph", None)
    rec = getattr(result, "recovery", None)
    return dict(
        counts=_plain(result.counts),
        documents=sorted(result.documents),
        errors=sorted(result.errors),
        extraction=sorted(_plain(result.extraction), key=key),
        questions=questions,
        evidence=sorted((_plain(e) for e in result.evidence), key=key),
        cross_artifact=sorted((_plain(o) for o in (g.observations if g else [])), key=key),
        recovery=sorted((_plain(i) for i in (rec.issues if rec else [])), key=key),
        semantic_status=result.semantic_status,
        run_stamp=_plain(getattr(result, "run_stamp", {})),
    )
