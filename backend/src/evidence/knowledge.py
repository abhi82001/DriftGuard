#!/usr/bin/env python3
"""Read-only access to the evidence record that grounds CP007 validation.

Validation checks must be anchored in the existing knowledge base, never in
rules invented by application code. This module only reads; it never repairs,
extends, or renames a knowledge record.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Optional


class EvidenceKnowledgeError(Exception):
    pass


@lru_cache(maxsize=8)
def load_evidence_record(evidence_id: str, root: Optional[str] = None) -> dict:
    base = Path(root) if root else _knowledge_root()
    path = base / "evidence" / f"{evidence_id}.json"
    if not path.is_file():
        raise EvidenceKnowledgeError(f"unknown evidence record {evidence_id!r}")
    return json.loads(path.read_text(encoding="utf-8"))


def validation_rule(evidence_id: str, rule_id: str) -> dict:
    """Return an existing validation rule, or fail loudly if it is not there."""
    record = load_evidence_record(evidence_id)
    for rule in record.get("validation_rules", []):
        if rule.get("rule_id") == rule_id:
            return rule
    raise EvidenceKnowledgeError(f"{evidence_id} has no validation rule {rule_id!r}")


def grounding(evidence_id: str, rule_id: str = "") -> str:
    """A traceable grounding string, verified against the knowledge base."""
    if not rule_id:
        load_evidence_record(evidence_id)
        return evidence_id
    validation_rule(evidence_id, rule_id)
    return f"{evidence_id}/{rule_id}"


def _knowledge_root() -> Path:
    from evaluation.engine import resolve_knowledge_root

    return resolve_knowledge_root()
