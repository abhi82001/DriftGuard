#!/usr/bin/env python3
"""Value specificity and contradiction rules for extracted claims.

A generic affirmation (True, required, recorded, yes ...) is not evidence by
itself: it supports a question only when its source snippet names a
question-relevant subject (an anchor term for the topic) in a real statement.
"""
from __future__ import annotations

GENERIC_VALUES = frozenset({
    "true", "yes", "required", "recorded", "documented", "tracked", "completed",
    "observed", "measured", "enabled", "restricted"})

# Topic -> anchor stems that must appear in the snippet for a generic value to count.
TOPIC_ANCHORS: dict[str, tuple[str, ...]] = {
    "mfa": ("mfa", "multi-factor", "multifactor", "multi factor", "two-factor", "second factor", "authentication factor", "verification factor"),
    "access_review": ("access review", "entitlement review", "recertif", "access certif", "user review", "review"),
    "termination": ("terminat", "offboard", "leaver", "deprovision", "separation"),
    "privileged_access": ("privileg", "administrat", "admin", "root", "elevat"),
    "encryption_at_rest": ("at rest", "encrypt", "kms", "key"),
    "transport_encryption": ("tls", "https", "ssl", "transit", "transport"),
    "alert_triage": ("alert", "triage"),
    "logging": ("log", "siem", "retention"),
    "incident_declaration": ("incident",),
    "incident_exercise": ("exercise", "tabletop", "incident"),
    "postmortem": ("postmortem", "post-mortem", "root cause", "corrective"),
    "vulnerability_management": ("vulnerab", "scan", "finding", "patch"),
    "endpoint_protection": ("endpoint", "edr", "antimalware", "anti-malware"),
}

# Attributes whose differing values are a real contradiction (a categorical choice).
CATEGORICAL_ATTRS = frozenset({"privilege_model", "cadence", "revocation_timeframe",
                               "privileged_review_cadence"})

MIN_WORDS = 4


def normalize_value(value) -> str:
    if isinstance(value, (list, tuple, set, frozenset)):
        return "|".join(sorted(str(v).strip().lower() for v in value))
    text = str(value).strip().lower()
    return {"annually": "annual", "semiannual": "semi-annual", "semi annually": "semi-annual",
            "semi-annually": "semi-annual", "just-in-time": "time-bounded", "jit": "time-bounded",
            "time-bound": "time-bounded", "time bound": "time-bounded"}.get(text, text)


def _is_generic(value) -> bool:
    if value is True:
        return True
    return isinstance(value, str) and value.strip().lower() in GENERIC_VALUES


def is_specific(claim, attr: str, topic: str) -> bool:
    """False only for a generic value lacking a topic anchor / real statement."""
    value = claim.attributes.get(attr)
    if not _is_generic(value):
        return True
    snippet = " ".join((getattr(claim, "snippet", "") or "").lower().split())
    if len(snippet.split()) < MIN_WORDS:
        return False
    anchors = TOPIC_ANCHORS.get(topic) or tuple(w[:5] for w in topic.split("_") if len(w) > 2)
    return any(a in snippet for a in anchors)
