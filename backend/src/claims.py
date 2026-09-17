#!/usr/bin/env python3
"""Conservative structured security-claim extraction from extracted document text.

Document text is untrusted data. A claim is only ever created from text that is
actually present, and every claim carries the source snippet it came from.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Protocol

from ingestion import Document

NATURES = ("POLICY", "PROCEDURE", "OPERATING_EVIDENCE", "CONFIGURATION", "RECORD", "UNKNOWN")
DESIGN_NATURES = {"POLICY", "PROCEDURE"}
OPERATING_NATURES = {"OPERATING_EVIDENCE", "CONFIGURATION", "RECORD"}

TOPICS = ("mfa", "access_review", "termination", "privileged_access",
          "encryption_at_rest", "transport_encryption")


@dataclass(frozen=True)
class SecurityClaim:
    topic: str
    statement: str
    source_filename: str
    source_locator: str
    snippet: str
    evidence_nature: str
    attributes: dict = field(default_factory=dict)


class ClaimExtractor(Protocol):
    def extract(self, documents: Iterable[Document]) -> list[SecurityClaim]:
        ...


_MFA = re.compile(r"\b(multi[- ]?factor|mfa|two[- ]?factor|2fa|second (authentication )?factor)\b", re.I)
_REQUIRE = re.compile(r"\b(require[sd]?|enforce[sd]?|enforcement|mandatory|must)\b", re.I)
_SCOPE = {
    "production": "production systems",
    "identity provider": "identity provider",
    "vpn": "VPN",
    "console": "cloud management console",
    "repositor": "source code repository",
    "employee": "employees",
    "admin": "administrators",
}
_REVIEW = re.compile(
    r"(?:\b(?:access|entitlement)\w*\b[^.]{0,80}\breview)"
    r"|(?:\breview\w*\b[^.]{0,80}\b(?:access|entitlement|employee|contractor|"
    r"service account|privileged account|shared account))",
    re.I,
)
_USER_POPULATION = re.compile(
    r"\b(user|users|employee|employees|contractor|contractors|service account|"
    r"shared account|workforce|personnel access)\b", re.I,
)
_SENTENCE = re.compile(r"(?<=[.;!])\s+")
_CADENCE = re.compile(r"\b(quarterly|monthly|semi[- ]annually|annually|annual|weekly|every \d+ (?:days|months))\b", re.I)
_POPULATIONS = ("employees", "contractors", "service accounts", "shared accounts",
                "third parties", "interns", "privileged accounts",
                "administrative accounts", "administrators")
_DATE = re.compile(r"\b(20\d{2}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/20\d{2})\b")
_LATEST = re.compile(r"\b(review[ _-]?date|reviewed on|review completed|completed on|last review)\b", re.I)
_REMOVAL = re.compile(r"\b(removed|revoked|deprovision(?:ed|ing)?|disabled)\b", re.I)
_TERMINATION = re.compile(r"\b(terminat\w+|offboard\w+|separation|departure)\b", re.I)
_TIMEFRAME = re.compile(r"\bwithin (\d+) (hours?|business days?|calendar days?|days?)\b", re.I)
_PRIVILEGED = re.compile(r"\b(privileged|administrative|administrator|admin|root|elevated)\b", re.I)
_JIT = re.compile(r"\b(just[- ]in[- ]time|jit|time[- ]bound(?:ed)?|time[- ]limited|temporary elevation)\b", re.I)
_STANDING = re.compile(r"\bstanding\b", re.I)
_INVENTORY = re.compile(r"\b(inventory|entitlement list|privileged[ _-]access[ _-]review)\b", re.I)
_RESTRICTED = re.compile(r"\b(restricted|limited|authorized personnel|approved personnel|least privilege)\b", re.I)
_REVIEWED = re.compile(r"\breview(?:ed|s|ing)?\b", re.I)
_AT_REST = re.compile(r"\b(encrypt\w*)\b[^.]{0,60}\b(at rest|database|databases|storage|volume|bucket|snapshot)s?\b|\b(at rest|database|databases|storage|volume|bucket)s?\b[^.]{0,60}\b(encrypt\w*)\b", re.I)
_KEY_MGMT = re.compile(r"\b(kms|key management|key custody|customer[- ]managed key|key rotation)\b", re.I)
_TRANSPORT = re.compile(r"\b(tls|https|in transit|encrypted transport|transport encryption|transport security|mutual tls)\b", re.I)
_VERIFIED = re.compile(r"\b(verified|validated|scan\w*|test result|handshake|certificate report)\b", re.I)
_ENFORCED_VALUE = re.compile(r"\b(enabled|enforced|active|true|compliant_state)\b", re.I)
_CONFIG = re.compile(r"\b(configuration|config|export|setting|conditional access|policy assignment)\b", re.I)


def _nature(document: Document, text: str) -> str:
    if document.kind == "policy":
        return "PROCEDURE" if "procedure" in document.filename.lower() else "POLICY"
    if _CONFIG.search(text) or _ENFORCED_VALUE.search(text):
        return "CONFIGURATION"
    if _DATE.search(text):
        return "RECORD"
    return "UNKNOWN"


def _statement(text: str) -> str:
    return " ".join(text.split())[:220]


class DemoClaimExtractor:
    """Deterministic, offline extractor for a small set of representative concepts.

    Not model analysis. Concepts it does not confidently recognise produce no
    claim at all, so nothing downstream can become partially established by a
    generic keyword.
    """

    source = "deterministic-local"

    def extract(self, documents: Iterable[Document]) -> list[SecurityClaim]:
        claims: list[SecurityClaim] = []
        for document in documents:
            for chunk in document.chunks:
                nature = _nature(document, chunk.text)
                # Sentence granularity keeps each fact bound to the text that
                # actually supports it.
                for sentence in _SENTENCE.split(chunk.text):
                    text = sentence.strip()
                    if not text:
                        continue
                    for topic, attributes in self._rules(text, nature):
                        if attributes:
                            claims.append(SecurityClaim(
                                topic=topic,
                                statement=_statement(text),
                                source_filename=chunk.filename,
                                source_locator=chunk.locator,
                                snippet=_statement(text),
                                evidence_nature=nature,
                                attributes=attributes,
                            ))
        return claims

    @staticmethod
    def _rules(text: str, nature: str) -> list[tuple[str, dict]]:
        low = text.lower()
        operating = nature in OPERATING_NATURES
        out: list[tuple[str, dict]] = []

        if _MFA.search(text):
            attrs: dict = {}
            if _REQUIRE.search(text):
                attrs["requirement"] = "required"
            scope = sorted({label for key, label in _SCOPE.items() if key in low})
            if scope:
                attrs["scope"] = scope
            if operating and _ENFORCED_VALUE.search(text):
                attrs["enforcement_evidence"] = True
            out.append(("mfa", attrs))

        # A privileged-only review sentence belongs to privileged_access, not to
        # the general user access review.
        privileged_only = _PRIVILEGED.search(text) and not _USER_POPULATION.search(text)
        if _REVIEW.search(text) and not privileged_only:
            attrs = {}
            cadence = _CADENCE.search(text)
            if cadence:
                attrs["cadence"] = cadence.group(1).lower()
            pops = [p for p in _POPULATIONS if p in low]
            if pops:
                attrs["populations"] = pops
            if operating and (_LATEST.search(text) or _DATE.search(text)):
                date = _DATE.search(text)
                attrs["latest_review"] = date.group(1) if date else True
            if operating and _REMOVAL.search(text):
                attrs["removal_evidence"] = True
            out.append(("access_review", attrs))

        if _TERMINATION.search(text):
            attrs = {}
            timeframe = _TIMEFRAME.search(text)
            if timeframe:
                attrs["revocation_timeframe"] = f"within {timeframe.group(1)} {timeframe.group(2)}"
            if operating and _REMOVAL.search(text) and _DATE.search(text):
                attrs["revocation_evidence"] = True
            out.append(("termination", attrs))

        if _PRIVILEGED.search(text):
            attrs = {}
            if _JIT.search(text):
                attrs["privilege_model"] = "time-bounded / just-in-time"
            elif _STANDING.search(text):
                attrs["privilege_model"] = "standing"
            if _RESTRICTED.search(text):
                attrs["privilege_restricted"] = "restricted to authorized personnel"
            cadence = _CADENCE.search(text)
            if cadence and _REVIEWED.search(text):
                attrs["privileged_review_cadence"] = cadence.group(1).lower()
            if operating and (_INVENTORY.search(text) or _REVIEW.search(text)):
                attrs["privileged_review_evidence"] = True
            out.append(("privileged_access", attrs))

        if _AT_REST.search(text):
            attrs = {"rest_requirement": "storage encrypted at rest"}
            if operating and (_CONFIG.search(text) or _ENFORCED_VALUE.search(text)
                              or _KEY_MGMT.search(text)):
                attrs["rest_config_evidence"] = True
            out.append(("encryption_at_rest", attrs))

        if _TRANSPORT.search(text):
            attrs = {"transport_requirement": "encrypted transport required"}
            if operating and (_VERIFIED.search(text) or _CONFIG.search(text)
                              or _ENFORCED_VALUE.search(text)):
                attrs["transport_config_evidence"] = True
            out.append(("transport_encryption", attrs))

        return out
