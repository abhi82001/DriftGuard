from __future__ import annotations
from dataclasses import dataclass
from .facts import CanonicalFact

PRIVACY_PREDICATES=frozenset({"CONSENT_STATUS","CONSENT_WITHDRAWAL_DAYS","PARENTAL_CONSENT","RIGHTS_REQUEST_DAYS","BREACH_NOTIFICATION_HOURS","PROCESSOR_DPA","RETENTION_DAYS","DELETION_VERIFIED"})
@dataclass(frozen=True)
class PrivacyObservation: code:str; state:str; detail:str; fact_ids:tuple[str,...]

def evaluate_privacy_facts(facts, *, rights_sla_days=30, withdrawal_sla_days=7, breach_sla_hours=72):
    out=[]
    for f in facts:
        if f.predicate=="RIGHTS_REQUEST_DAYS" and isinstance(f.value,(int,float)) and f.value>rights_sla_days: out.append(PrivacyObservation("RIGHTS-SLA","EXCEPTION_IDENTIFIED",f"Rights request took {f.value} days; threshold is {rights_sla_days}.",(f.fact_id,)))
        if f.predicate=="CONSENT_WITHDRAWAL_DAYS" and isinstance(f.value,(int,float)) and f.value>withdrawal_sla_days: out.append(PrivacyObservation("WITHDRAWAL-SLA","EXCEPTION_IDENTIFIED",f"Consent withdrawal took {f.value} days; threshold is {withdrawal_sla_days}.",(f.fact_id,)))
        if f.predicate=="BREACH_NOTIFICATION_HOURS" and isinstance(f.value,(int,float)) and f.value>breach_sla_hours: out.append(PrivacyObservation("BREACH-SLA","EXCEPTION_IDENTIFIED",f"Breach notification took {f.value} hours; threshold is {breach_sla_hours}.",(f.fact_id,)))
        if f.predicate in {"PARENTAL_CONSENT","PROCESSOR_DPA","DELETION_VERIFIED"} and f.value is False: out.append(PrivacyObservation("PRIVACY-SAFEGUARD","NEEDS_REVIEW",f"{f.predicate} is not evidenced for {f.subject}.",(f.fact_id,)))
    return tuple(out)
