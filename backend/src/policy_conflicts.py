"""Deterministic cross-document polarity conflict detection (no LLM)."""
from __future__ import annotations
import re

_STRONG = r"(?:enforced|required|mandatory|enabled|compulsory)"
_WEAK = r"(?:optional|not\s+required|not\s+enforced|disabled|exempt(?:ed)?|waived)"
_TOPICS = {
    "mfa": r"\b(?:mfa|multi-?factor|2fa|two-?factor)\b",
    "encryption": r"\bencrypt\w*\b",
    "logging": r"\b(?:audit\s+)?logging\b",
    "backups": r"\bbackups?\b",
    "access reviews": r"\baccess\s+reviews?\b",
    "vulnerability scanning": r"\bvulnerability\s+scan\w*\b",
}
_SENT = re.compile(r"[^.!?\n]+")


def _polarity(sentence: str) -> str | None:
    s = sentence.lower()
    if re.search(_WEAK, s) and re.search(_STRONG, re.sub(_WEAK, " ", s)):
        return None  # mixed scoping within one sentence, e.g. "required for admins, optional for kiosks"
    if re.search(_WEAK, s):
        return "weak"
    if re.search(r"\b(?:not|never|no)\b", s) and re.search(_STRONG, s):
        return "weak"
    if re.search(_STRONG, s):
        return "strong"
    return None


def detect_polarity_conflicts(documents) -> list[dict]:
    seen: dict[str, dict[str, list]] = {}
    for d in documents:
        for chunk in d.chunks:
            for m in _SENT.finditer(chunk.text):
                sent = m.group(0).strip()
                pol = _polarity(sent)
                if not pol:
                    continue
                for topic, rx in _TOPICS.items():
                    if re.search(rx, sent, re.I):
                        seen.setdefault(topic, {"strong": [], "weak": []})[pol].append((d.filename, sent[:220]))
    out = []
    for topic, v in sorted(seen.items()):
        for sf, ss in v["strong"]:
            for wf, ws in v["weak"]:
                if sf != wf or ss != ws:
                    out.append({"topic": topic, "attribute": "polarity", "kind": "RULE_BASED_POLARITY",
                                "source_file": sf, "deterministic_value": ss,
                                "other_source_file": wf, "semantic_value": ws})
                    break
            else:
                continue
            break
    return out
