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


def framework_identity(root: Optional[Path] = None) -> tuple[str, str]:
    """(framework id, framework version) of a knowledge directory.

    Read from ``framework/metadata.json``; a directory without it is labelled by
    its own name with an empty version rather than guessed.
    """
    base = Path(root) if root else _knowledge_root()
    path = base / "framework" / "metadata.json"
    if not path.is_file():
        return base.name, ""
    meta = json.loads(path.read_text(encoding="utf-8"))
    return meta.get("framework", base.name), str(meta.get("registry_version", ""))


def load_controls(root: Optional[Path] = None) -> list[dict]:
    """Control records stamped with ``framework`` / ``framework_version``.

    A value already on the record wins; the stamp only fills a missing one.
    """
    base = Path(root) if root else _knowledge_root()
    key, version = framework_identity(base)
    out = []
    for path in sorted((base / "controls").glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        record.setdefault("framework", key)
        record.setdefault("framework_version", version)
        out.append(record)
    return out


def load_questionnaire(questionnaire_id: str, root: Optional[Path] = None) -> dict:
    """A questionnaire whose questions each carry ``framework`` / ``framework_version``."""
    base = Path(root) if root else _knowledge_root()
    path = base / "questionnaires" / f"{questionnaire_id}.json"
    if not path.is_file():
        raise ValueError(f"unknown questionnaire {questionnaire_id!r}")
    record = json.loads(path.read_text(encoding="utf-8"))
    key, version = framework_identity(base)
    record.setdefault("framework", key)
    record.setdefault("framework_version", version)
    for question in record["questions"]:
        question.setdefault("framework", record["framework"])
        question.setdefault("framework_version", record["framework_version"])
    return record


def evaluated_questions(questionnaire_id: str, root: Optional[Path] = None) -> frozenset[str]:
    """Question ids the evidence mapping evaluates, from ``framework/mapping_profile.json``."""
    base = Path(root) if root else _knowledge_root()
    path = base / "framework" / "mapping_profile.json"
    if not path.is_file():
        return frozenset()
    profile = json.loads(path.read_text(encoding="utf-8"))
    entry = profile.get("questionnaires", {}).get(questionnaire_id, {})
    return frozenset(entry.get("evaluated_questions", ()))


def _knowledge_root() -> Path:
    from evaluation.engine import resolve_knowledge_root

    return resolve_knowledge_root()
