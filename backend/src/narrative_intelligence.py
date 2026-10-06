"""Grounded narrative evidence extraction for DriftGuard CP010.

This module extracts *candidate evidence facts*, not compliance conclusions.
Every fact is bound to an exact source segment.  Deterministic extraction is
intentionally conservative; semantic providers may add candidates later but
must pass ``validate_semantic_fact`` before entering the evidence pipeline.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Iterable

from ingestion import Document, Chunk

CLAIM_TYPES = frozenset({"REQUIREMENT","IMPLEMENTATION","OBSERVATION","RESULT","EXCEPTION","REMEDIATION","SCOPE","CADENCE","OWNERSHIP","METRIC"})
SOURCE_ROLES = frozenset({"POLICY","PROCEDURE","CONFIGURATION","OPERATING_EVIDENCE","REPORT","TICKET","REGISTER","TEST_RESULT","UNKNOWN"})

@dataclass(frozen=True)
class FactProvenance:
    filename: str
    locator: str
    excerpt: str
    page: str = ""
    section: str = ""
    paragraph: str = ""
    table: str = ""

@dataclass(frozen=True)
class NarrativeFact:
    fact_id: str
    concept: str
    attribute: str
    value: object
    normalized_value: object
    claim_type: str
    qualifiers: tuple[str, ...]
    scope: tuple[str, ...]
    subject: str
    time_period: str
    effective_date: str
    source_role: str
    artifact_type: str
    confidence: float
    extraction_method: str
    provenance: FactProvenance

@dataclass(frozen=True)
class SemanticFactCandidate:
    concept: str
    attribute: str
    value: object
    claim_type: str
    supporting_quote: str
    source_locator: str
    confidence: float
    source_role: str

@dataclass(frozen=True)
class SemanticFactValidation:
    accepted: bool
    reason: str

# Broad concept ontology.  These are concept signals, not evidence conclusions.
ONTOLOGY: dict[str, tuple[str, ...]] = {
    "identity_access": ("access", "identity", "account", "entitlement"),
    "mfa": ("mfa", "multi-factor", "multifactor", "two-factor", "second factor", "additional verification factor", "additional authentication factor", "another authentication factor", "hardware key", "security key"),
    "joiner_mover_leaver": ("termination", "offboarding", "leaver", "revocation", "deprovision"),
    "access_review": ("access review", "recertification", "access certification", "entitlement review"),
    "privileged_access": ("privileged", "administrator", "administrative access", "root", "elevation"),
    "authentication": ("authentication", "identity provider", "idp", "login", "ssh", "vpn"),
    "encryption_at_rest": ("encryption at rest", "encrypted at rest", "disk encryption", "encrypted storage", "kms"),
    "encryption_in_transit": ("tls", "https", "encryption in transit", "transport encryption", "encrypted protocol"),
    "key_management": ("key management", "kms", "key rotation", "key custody"),
    "network_security": ("network security", "security group", "boundar", "ingress", "egress", "outbound"),
    "firewalls": ("firewall", "security group", "network rule", "temporary rule", "boundary rule"),
    "segmentation": ("segmentation", "microsegmentation", "network zone", "boundary"),
    "endpoint_security": ("endpoint", "edr", "antimalware", "anti-malware"),
    "logging": ("logging", "logged", "logs", "log source", "retention", "siem"),
    "monitoring": ("monitoring", "monitor", "telemetry"),
    "alerting": ("alert", "triage", "detection"),
    "incident_response": ("incident", "postmortem", "root cause", "escalation"),
    "vulnerability_management": ("vulnerability", "scan", "finding", "cve", "remediation"),
    "patching": ("patch", "patching"),
    "change_management": ("change", "pull request", "deployment", "approval"),
    "backup": ("backup", "restore"),
    "business_continuity": ("business continuity", "bcp", "continuity"),
    "disaster_recovery": ("disaster recovery", "recovery exercise", "rto", "rpo"),
    "vendor_management": ("vendor", "supplier", "third party"),
    "risk_management": ("risk", "residual", "inherent", "treatment"),
    "asset_management": ("asset inventory", "asset", "hostname"),
    "data_inventory": ("data inventory", "dataset", "classification", "retention"),
    "data_deletion": ("data deletion", "deletion request", "erasure", "sanitization", "media disposal", "media sanitization"),
    "physical_security": ("physical access", "badge", "facilit", "visitor"),
    "security_awareness": ("security awareness", "training"),
    "background_screening": ("background check", "screening"),
}

_NEG = re.compile(r"\b(?:not|no|never|without|has not|have not|was not|were not|isn't|aren't)\b", re.I)
_PLAN = re.compile(r"\b(?:plan(?:ned)?|target(?:ed)?|intend(?:ed)?|will|future|roadmap)\b", re.I)
_EXCEPTION = re.compile(r"\b(?:except|exception|exempt|exemption|excluding|excluded|unless)\b", re.I)
_CONDITIONAL = re.compile(r"\b(?:where feasible|generally|where possible|as appropriate|should|may)\b", re.I)
_HISTORICAL = re.compile(r"\b(?:was|were|previously|historically|during|formerly)\b", re.I)
_REQUIREMENT = re.compile(r"\b(?:must|shall|required|required to|requires|policy requires|mandated)\b", re.I)
_RESULT = re.compile(r"\b(?:completed|result|passed|failed|success|successful|closed|verified|tested|observed)\b", re.I)
_REMEDIATION = re.compile(r"\b(?:remediat|corrective action|action item|fix(?:ed)?)\b", re.I)
_OWNER = re.compile(r"\b(?:owner|owned by|responsible|accountable)\b", re.I)
_CADENCE = re.compile(r"\b(?:daily|weekly|monthly|quarterly|semi[- ]?annual(?:ly)?|annual(?:ly)?|every\s+\d+\s+(?:day|week|month|year)s?)\b", re.I)
_DATE = re.compile(r"\b(20\d{2}-\d{2}-\d{2}|20\d{2}/\d{1,2}/\d{1,2}|\d{1,2}/\d{1,2}/20\d{2})\b")


def classify_source_role(document: Document) -> str:
    """Content-first evidence role classification; filename is only a tie-breaker."""
    text = document.text[:12000].lower()
    name = document.filename.lower()
    # Strong content markers first.
    if re.search(r"\b(?:policy|standard)\b", text) and re.search(r"\b(?:must|shall|required|purpose|scope)\b", text):
        return "POLICY"
    if re.search(r"\bprocedure\b", text) and re.search(r"\b(?:step|process|responsib|must|shall)\b", text):
        return "PROCEDURE"
    if re.search(r"\b(?:test results?|exercise results?|validation report)\b", text):
        return "TEST_RESULT"
    if re.search(r"\b(?:access|entitlement).{0,60}(?:review|certification).{0,80}(?:completed|closed|certified).{0,50}20\d{2}", text):
        return "REPORT"
    if re.search(r"\b(?:ticket|case|request)\b", text) and re.search(r"\b(?:approver|status|closed|completed)\b", text):
        return "TICKET"
    if re.search(r"\b(?:register|inventory|roster|tracker)\b", text) and "|" in text:
        return "REGISTER"
    if re.search(r"\b(?:configuration|configured|setting|enabled|security group|tls)\b", text) and ("{" in text or "$" in text or "|" in text):
        return "CONFIGURATION"
    if re.search(r"\b(?:report|summary|coverage|results?|record|log)\b", text) and ("|" in text or len(document.chunks) > 1):
        return "REPORT"
    # Weak filename tie breakers.
    if "policy" in name or "plan" in name:
        return "POLICY"
    if "procedure" in name:
        return "PROCEDURE"
    if any(x in name for x in ("ticket", "case")):
        return "TICKET"
    if any(x in name for x in ("register", "inventory", "roster", "tracker")):
        return "REGISTER"
    if any(x in name for x in ("config", "configuration", "security_group")):
        return "CONFIGURATION"
    if any(x in name for x in ("test", "validation")):
        return "TEST_RESULT"
    if any(x in name for x in ("report", "record", "log", "review", "export")):
        return "REPORT"
    return "UNKNOWN"


def claim_type(text: str, role: str) -> str:
    if _EXCEPTION.search(text): return "EXCEPTION"
    if _REMEDIATION.search(text): return "REMEDIATION"
    if _REQUIREMENT.search(text) or role in {"POLICY","PROCEDURE"}: return "REQUIREMENT"
    if _RESULT.search(text) or role == "TEST_RESULT": return "RESULT"
    if _CADENCE.search(text): return "CADENCE"
    if _OWNER.search(text): return "OWNERSHIP"
    if re.search(r"\b(?:%|percent|count|number|hours?|days?|rto|rpo)\b", text, re.I): return "METRIC"
    if role in {"CONFIGURATION","REPORT","REGISTER","TICKET"}: return "OBSERVATION"
    return "IMPLEMENTATION"


def _qualifiers(text: str) -> tuple[str, ...]:
    q=[]
    if _NEG.search(text): q.append("NEGATED")
    if _PLAN.search(text): q.append("PLANNED_OR_FUTURE")
    if _EXCEPTION.search(text): q.append("EXCEPTION")
    if _CONDITIONAL.search(text): q.append("CONDITIONAL")
    if _HISTORICAL.search(text): q.append("HISTORICAL")
    return tuple(q)


def _concepts(text: str) -> tuple[str, ...]:
    low=text.lower()
    return tuple(k for k, signals in ONTOLOGY.items() if any(s in low for s in signals))

# Mapping from ontology concepts to questionnaire topic/attribute facts.  A rule
# fires only when its evidence phrase is in the exact source segment.
_RULES: tuple[tuple[str,str,str,re.Pattern,str], ...] = (
("mfa","requirement","mfa",re.compile(r"\b(?:mfa|multi[- ]?factor|two[- ]?factor|second factor|(?:additional|another) (?:verification|authentication) factor).{0,90}(?:must|required|requires|shall|mandatory)|(?:must|required|requires|shall).{0,90}(?:mfa|multi[- ]?factor|two[- ]?factor|second factor|(?:additional|another) (?:verification|authentication) factor)",re.I),"required"),
("mfa","enforcement_evidence","mfa",re.compile(r"\b(?:mfa|multi[- ]?factor).{0,80}(?:\benabled|\benforced|\bactive|\btrue|\byes)\b",re.I),"true"),
("mfa","scope_exception","mfa",re.compile(r"\b(?:service accounts?|emergency accounts?|break[- ]?glass accounts?).{0,80}(?:exempt|excluded|exception)|(?:exempt|excluded|exception).{0,80}(?:service accounts?|emergency accounts?|break[- ]?glass accounts?)",re.I),"exception"),
("mfa","planned_change","mfa",re.compile(r"\b(?:hardware keys?|security keys?|authentication factors?).{0,100}(?:will|planned|roadmap|next (?:quarter|month|year))|(?:will|planned|roadmap).{0,100}(?:hardware keys?|security keys?)",re.I),"planned"),
("access_review","cadence","access_review",re.compile(r"\b(?:access|entitlement).{0,50}review.{0,50}(daily|weekly|monthly|quarterly|annually|annual|semi[- ]annually)",re.I),"$1"),
("access_review","latest_review","access_review",re.compile(r"\b(?:access|entitlement).{0,50}review.{0,80}(?:completed|closed|certified).{0,40}(20\d{2}-\d{2}-\d{2})",re.I),"$1"),
("termination","revocation_timeframe","joiner_mover_leaver",re.compile(r"\b(?:terminat|offboard|leaver).{0,100}within\s+(\d+\s+(?:hours?|days?))",re.I),"$1"),
("termination","revocation_evidence","joiner_mover_leaver",re.compile(r"\b(?:terminat|offboard|leaver).{0,120}(?:disabled|revoked|deprovisioned|completed)\b",re.I),"true"),
("privileged_access","privilege_model","privileged_access",re.compile(r"\b(?:just[- ]in[- ]time|jit|time[- ]bound(?:ed)?|standing)\b",re.I),"$0"),
("privileged_access","privilege_restricted","privileged_access",re.compile(r"\b(?:privileg\w*|administrative access|admin access).{0,100}(?:authorized|least privilege|restricted|approved)\b",re.I),"restricted to authorized personnel"),
("encryption_at_rest","rest_requirement","encryption_at_rest",re.compile(r"\b(?:encrypt\w*.{0,60}at rest|at rest.{0,60}encrypt\w*).{0,80}(?:must|required|shall)?",re.I),"storage encrypted at rest"),
("encryption_at_rest","rest_config_evidence","encryption_at_rest",re.compile(r"\b(?:encryption|encrypted).{0,70}(?:enabled|aes|kms|true|yes)\b",re.I),"true"),
("transport_encryption","transport_requirement","encryption_in_transit",re.compile(r"\b(?:tls|https|transport encryption|in transit).{0,100}(?:must|required|minimum|shall)\b",re.I),"required"),
("transport_encryption","transport_config_evidence","encryption_in_transit",re.compile(r"\b(?:tls\s*1\.[23]|https).{0,80}(?:enabled|supported|pass|yes|true)|(?:pass|supported).{0,80}tls\s*1\.[23]",re.I),"true"),
("logging","logging_requirement","logging",re.compile(r"\b(?:logs?|logging).{0,100}(?:central|retain|retention|must|required|shall)\b",re.I),"required"),
("logging","log_source_coverage","logging",re.compile(r"\b(?:log source|reporting|coverage).{0,100}(?:%|expected|assets?|status|reporting)\b",re.I),"measured"),
("alert_triage","triage_requirement","alerting",re.compile(r"\b(?:alert|triage).{0,100}(?:within|owner|analyst|must|required|shall)\b",re.I),"required"),
("alert_triage","alert_triage_record","alerting",re.compile(r"\b(?:alert|severity).{0,120}(?:reviewed|analyst|disposition|ticket)\b",re.I),"recorded"),
("incident_declaration","incident_criteria","incident_response",re.compile(r"\bincident.{0,100}(?:criteria|declare|severity|threshold)\b",re.I),"documented"),
("incident_exercise","latest_exercise","incident_response",re.compile(r"\b(?:incident|response).{0,80}(?:exercise|tabletop|test).{0,80}(?:completed|conducted|result)\b",re.I),"completed"),
("postmortem","postmortem_record","incident_response",re.compile(r"\b(?:postmortem|root cause).{0,100}(?:incident|completed|cause|action)\b",re.I),"completed"),
("vulnerability_management","scan_scope_requirement","vulnerability_management",re.compile(r"\bvulnerab.{0,100}(?:scan|scanning).{0,80}(?:scope|all|must|required|shall)\b",re.I),"required"),
("vulnerability_management","scan_coverage","vulnerability_management",re.compile(r"\b(?:scan|finding|vulnerab).{0,120}(?:asset|coverage|critical|high|status)\b",re.I),"measured"),
("endpoint_protection","endpoint_requirement","endpoint_security",re.compile(r"\b(?:endpoint|edr).{0,100}(?:must|required|shall|protection)\b",re.I),"required"),
("endpoint_protection","endpoint_coverage","endpoint_security",re.compile(r"\b(?:edr|endpoint).{0,100}(?:installed|coverage|last seen|status|yes|true)\b",re.I),"measured"),
("security_configuration","configuration_baseline_requirement","change_management",re.compile(r"\b(?:change|configuration).{0,100}(?:approval|approved|baseline|must|required|shall)\b",re.I),"required"),
("security_configuration","configuration_change_record","change_management",re.compile(r"\b(?:change|deployment|pull request).{0,120}(?:approved|implemented|status|approver)\b",re.I),"recorded"),
("facility_security","facility_responsibility","physical_security",re.compile(r"\b(?:physical|facility).{0,100}(?:responsib|provider|operated|must|required)\b",re.I),"documented"),
("physical_access_review","physical_latest_review","physical_security",re.compile(r"\b(?:badge|physical access).{0,100}(?:review|reviewer).{0,100}(?:decision|status|completed)\b",re.I),"completed"),
("media_disposal","media_disposal_requirement","data_deletion",re.compile(r"\b(?:media|device).{0,100}(?:disposal|sanitiz|destroy).{0,80}(?:must|required|shall|unrecoverable)\b",re.I),"required"),
("media_disposal","media_disposal_record","data_deletion",re.compile(r"\b(?:sanitization|disposal).{0,120}(?:certificate|method|vendor|approved|date)\b",re.I),"recorded"),
("cryptographic_erasure","crypto_erasure_requirement","data_deletion",re.compile(r"\b(?:cryptographic erasure|crypto[- ]?erase|deletion).{0,100}(?:must|required|shall|unrecoverable)\b",re.I),"required"),
("entitlement_approval","approval_record","identity_access",re.compile(r"\b(?:entitlement|access).{0,100}(?:approver|approved).{0,100}(?:ticket|status|identity)\b",re.I),"recorded"),
("public_admin_exposure","public_interface_inventory","network_security",re.compile(r"\b(?:0\.0\.0\.0/0|public).{0,100}(?:22|3389|admin|ssh|rdp)\b",re.I),"observed"),
("boundary_baseline","live_boundary_configuration","network_security",re.compile(r"\b(?:security group|firewall|boundary).{0,120}(?:allow|deny|ingress|egress|port|rule)\b",re.I),"observed"),
("temporary_boundary_rule","temporary_rule_expiry","firewalls",re.compile(r"\b(?:temporary|expiry|expires|expiration).{0,100}(?:rule|firewall|security group)|(?:rule|firewall).{0,100}(?:expiry|expires)\b",re.I),"recorded"),
("data_egress","egress_control_evidence","network_security",re.compile(r"\begress.{0,100}(?:restrict|monitor|log|allow|deny)\b",re.I),"observed"),

("mfa","scope","mfa",re.compile(r"\b(?:mfa|multi[- ]?factor).{0,100}(production|administrat|cloud|vpn|repository)",re.I),"production systems"),
("access_review","populations","access_review",re.compile(r"\b(?:access|entitlement).{0,70}review.{0,120}(?:employee|contractor|service account|privileged)\b",re.I),"documented populations"),
("privileged_access","privileged_review_cadence","privileged_access",re.compile(r"\bprivileg.{0,80}(?:review|recertif).{0,60}(quarterly|monthly|annually|annual|periodically)",re.I),"$1"),
("encryption_at_rest","key_custody_evidence","key_management",re.compile(r"\b(?:key|kms).{0,100}(?:administration|admin|custody|rotation|owner)\b",re.I),"documented"),
("public_admin_exposure","public_admin_requirement","network_security",re.compile(r"\badministrative interfaces?.{0,120}(?:public internet|publicly).{0,80}(?:approved|protected|should not|must not)\b",re.I),"restricted"),
("boundary_baseline","boundary_baseline","network_security",re.compile(r"\b(?:network boundaries|boundary rules?|firewall).{0,120}(?:restrict|approved business|baseline|shall|must)\b",re.I),"documented"),
("temporary_boundary_rule","temporary_rule_requirement","firewalls",re.compile(r"\btemporary rules?.{0,100}(?:expiration|expiry|owner|require)\b",re.I),"required"),
("data_egress","egress_requirement","network_security",re.compile(r"\b(?:outbound|egress).{0,100}(?:restrict|approved|monitor|shall|must)\b",re.I),"required"),
("incident_declaration","incident_authority","incident_response",re.compile(r"\b(?:incident commander|authorized role|commander).{0,80}(?:declare|escalate)\b",re.I),"documented"),
("incident_exercise","exercise_requirement","incident_response",re.compile(r"\b(?:plan|incident response).{0,100}(?:exercis|test).{0,80}(?:annual|periodic|must|shall|expected)\b",re.I),"required"),
("incident_exercise","exercise_findings","incident_response",re.compile(r"\b(?:exercise|test).{0,100}(?:finding|observation|corrective action)\b",re.I),"tracked"),
("postmortem","postmortem_record","incident_response",re.compile(r"\b(?:security incident postmortem|root cause).{0,160}(?:root cause|corrective actions?|incident)\b",re.I),"completed"),
("postmortem","postmortem_actions","incident_response",re.compile(r"\bcorrective actions?.{0,160}(?:open|closed|action|rotate|update)\b",re.I),"tracked"),
("vulnerability_management","remediation_timeframe","vulnerability_management",re.compile(r"\b(?:vulnerab|finding).{0,100}(?:due date|within|remediation timeframe|sla)\b",re.I),"documented"),
("vulnerability_management","overdue_handling","vulnerability_management",re.compile(r"\b(?:finding|vuln).{0,120}(?:open|exception|overdue|due)\b",re.I),"recorded"),
("endpoint_protection","endpoint_detection_response","endpoint_security",re.compile(r"\b(?:edr|endpoint).{0,120}(?:alert|detection|status|last seen)\b",re.I),"recorded"),
("physical_offboarding","physical_revocation_trigger","physical_security",re.compile(r"\bphysical access.{0,100}(?:removed|revoked).{0,80}(?:termination|role change)\b",re.I),"documented"),
("physical_access_review","physical_review_cadence","physical_security",re.compile(r"\b(?:facilit|physical access).{0,100}reviewed.{0,60}(periodically|quarterly|monthly|annually)",re.I),"$1"),
("media_disposal","sanitization_verification","data_deletion",re.compile(r"\b(?:sanitization|cryptographic erase|physical destruction).{0,120}(?:certificate|verified|approved)\b",re.I),"recorded"),
("cryptographic_erasure","crypto_erasure_evidence","data_deletion",re.compile(r"\bcryptographic erase.{0,120}(?:certificate|record|asset|date)\b",re.I),"recorded"),
("cryptographic_erasure","unrecoverability_evidence","data_deletion",re.compile(r"\b(?:securely deleted|rendered unrecoverable|key destruction).{0,100}(?:record|evidence|certificate|shall|must)\b",re.I),"documented"),
)


def _extract_value(match: re.Match, template: str):
    if template == "$0": return match.group(0).strip().lower()
    if template.startswith("$"):
        try: return match.group(int(template[1:])).strip().lower()
        except (IndexError, ValueError): return "observed"
    if template == "true": return True
    return template


def _scope(text: str) -> tuple[str, ...]:
    values=[]
    for token,label in (("production","production systems"),("employee","employees"),("administrator","administrators"),("identity provider","identity provider"),("contractor","contractors"),("service account","service accounts"),("privileged","privileged"),("cloud management console","cloud management console"),("repositor","source code repository"),("vpn","VPN")):
        if token in text.lower(): values.append(label)
    return tuple(sorted(set(values)))


def _prov(chunk: Chunk, excerpt: str | None = None) -> FactProvenance:
    loc=chunk.locator
    page=loc if loc.startswith("page ") else ""
    para=loc if loc.startswith("paragraph ") else ""
    table=loc if loc.startswith("table ") or loc.startswith("sheet ") or loc.startswith("row ") else ""
    return FactProvenance(chunk.filename, loc, " ".join((excerpt if excerpt is not None else chunk.text).split())[:500], page=page, paragraph=para, table=table)


def extract_narrative_facts(documents: Iterable[Document]) -> list[NarrativeFact]:
    facts=[]
    seen=set()
    for doc in documents:
        role=classify_source_role(doc)
        document_concepts = set(_concepts(doc.text[:12000]))
        for chunk in doc.chunks:
            # Header rows describe schema, not operating facts. Structured QA
            # owns CSV/XLSX row semantics; narrative extraction must not promote
            # a column heading such as "EDR Installed" into evidence.
            if (chunk.locator == "row 1" or re.search(r"sheet .+ row 1$", chunk.locator)) and "|" in chunk.text:
                continue
            # Preserve chunk provenance; split prose into bounded statements but
            # keep tables/rows intact because column relationships matter.
            statements=[chunk.text]
            if not ("|" in chunk.text):
                statements=[x.strip() for x in re.split(r"(?<=[.!?])\s+|\n+", chunk.text) if x.strip()]
            for text in statements:
                qs=_qualifiers(text)
                concepts=tuple(set(_concepts(text)) | document_concepts)
                ctype=claim_type(text, role)
                for topic,attr,concept,pattern,value_tpl in _RULES:
                    if concept not in concepts: continue
                    m=pattern.search(text)
                    if not m: continue
                    # Negative/planned/conditional statements are preserved as
                    # facts but never normalized into affirmative evidence.
                    val=_extract_value(m,value_tpl)
                    if attr == "privilege_model":
                        lv = str(val).lower()
                        val = "standing" if "standing" in lv else "time-bounded"
                    if attr == "scope":
                        val = list(_scope(text))
                    if attr == "populations":
                        low = text.lower()
                        val = [x for x in ("employees","contractors","service accounts","shared accounts","third parties","interns","privileged accounts","administrative accounts","administrators") if x in low]
                    norm = False if "NEGATED" in qs else ("PLANNED" if "PLANNED_OR_FUTURE" in qs else val)
                    key=(doc.filename,chunk.locator,topic,attr,repr(norm))
                    if key in seen: continue
                    seen.add(key)
                    fid="NF-"+hashlib.sha256("|".join(map(str,key)).encode()).hexdigest()[:16]
                    dm=_DATE.search(text)
                    facts.append(NarrativeFact(fid,topic,attr,val,norm,ctype,qs,_scope(text),"", "", dm.group(1) if dm else "", role, role, 0.95,"deterministic-grounded-v1",_prov(chunk, text)))
    return facts


def validate_semantic_fact(candidate: SemanticFactCandidate, document: Document, allowed_concepts: set[str]) -> SemanticFactValidation:
    """Validate untrusted semantic-provider output before it can become evidence."""
    if candidate.concept not in allowed_concepts:
        return SemanticFactValidation(False,"concept is not allowed for this extraction request")
    if candidate.claim_type not in CLAIM_TYPES:
        return SemanticFactValidation(False,"invalid claim type")
    if candidate.source_role not in SOURCE_ROLES:
        return SemanticFactValidation(False,"invalid source role")
    if not (0.0 <= candidate.confidence <= 1.0) or candidate.confidence < 0.70:
        return SemanticFactValidation(False,"confidence below acceptance threshold")
    chunks=[c for c in document.chunks if c.locator == candidate.source_locator]
    if not chunks:
        return SemanticFactValidation(False,"source locator does not exist")
    quote=" ".join(candidate.supporting_quote.split())
    if not quote or not any(quote in " ".join(c.text.split()) for c in chunks):
        return SemanticFactValidation(False,"supporting quote is not grounded at the claimed locator")
    verdict=re.compile(r"\b(?:soc\s*2\s+compliant|control\s+(?:passed|failed)|certified)\b",re.I)
    if verdict.search(str(candidate.value)) or verdict.search(candidate.supporting_quote):
        return SemanticFactValidation(False,"prohibited compliance verdict language")
    return SemanticFactValidation(True,"grounded candidate accepted")

class SemanticNarrativeProvider:
    """Provider contract for semantic narrative extraction.

    Providers return untrusted candidates.  DriftGuard validates grounding and
    schema before promotion; the provider never evaluates questionnaire status.
    """
    def extract_candidates(self, document: Document, allowed_concepts: set[str]):
        raise NotImplementedError


def extract_validated_semantic_facts(document: Document, provider: SemanticNarrativeProvider, allowed_concepts: set[str]):
    """Return (accepted, rejected) semantic candidates after grounding checks.

    This function does not silently invoke a provider.  Callers must explicitly
    configure one; DEMO/local deterministic mode therefore remains truthful.
    """
    accepted=[]; rejected=[]
    for candidate in provider.extract_candidates(document, allowed_concepts):
        result=validate_semantic_fact(candidate, document, allowed_concepts)
        (accepted if result.accepted else rejected).append((candidate,result))
    return accepted,rejected
