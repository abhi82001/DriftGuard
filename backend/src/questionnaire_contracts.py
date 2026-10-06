"""Executable questionnaire evidence contracts for all DriftGuard MVP questions.

Contracts define the normalized facts required to evaluate a question.  They do
not extract facts and never imply compliance.  Source-role gating is enforced by
the evaluator in documents.py.
"""
from dataclasses import dataclass

DESIGN_ROLES = frozenset({"POLICY", "PROCEDURE"})
OPERATING_ROLES = frozenset({"OPERATING_EVIDENCE", "CONFIGURATION", "RECORD"})

@dataclass(frozen=True)
class Spec:
    topic: str
    design: tuple[tuple[str, str], ...]
    operating: tuple[tuple[str, str], ...]
    design_roles: frozenset[str] = DESIGN_ROLES
    operating_roles: frozenset[str] = OPERATING_ROLES
    temporal_expectation: str = "current examination-period evidence where the question asks about operation"
    clarification_rule: str = "ask only for the unresolved material fact; never infer a failure from absence"

S = Spec
QUESTION_SPECS: dict[str, Spec] = {
# Access management
"QN-ACCESS-001-Q01": S("mfa", (("requirement","a second factor is required"),("scope","the systems the requirement covers")), (("enforcement_evidence","configuration showing the factor is enforced"),)),
"QN-ACCESS-001-Q02": S("authentication_paths", (("idp_governance_requirement","the documented identity-provider governance requirement"),), (("authentication_path_inventory","inventory of authentication paths and documented exceptions"),)),
"QN-ACCESS-001-Q03": S("access_review", (("cadence","the documented access review cadence"),), (("latest_review","the most recent completed review"),)),
"QN-ACCESS-001-Q04": S("access_review", (("populations","the identity populations in scope of the review"),), (("reviewed_populations","the population covered by the most recent review"),)),
"QN-ACCESS-001-Q05": S("access_review", (), (("removal_evidence","evidence that flagged access was removed"),("removal_confirmation","confirmation in the underlying system"))),
"QN-ACCESS-001-Q06": S("termination", (("revocation_timeframe","the committed revocation timeframe"),), (("revocation_evidence","evidence of an actual revocation"),("revocation_measurement","measurement of revocation against the commitment"))),
"QN-ACCESS-001-Q07": S("entitlement_approval", (("approval_requirement","the documented pre-provisioning approval requirement"),), (("approval_record","record identifying approver and entitlement before issuance"),)),
"QN-ACCESS-001-Q08": S("privileged_access", (("privilege_restricted","privilege is restricted to authorized personnel"),("privileged_review_cadence","the documented privileged access review cadence"),("privilege_model","standing versus time-bounded privilege")), (("privileged_review_evidence","a privileged access review or inventory"),)),
"QN-ACCESS-001-Q09": S("encryption_at_rest", (("rest_requirement","the documented encryption-at-rest requirement"),), (("rest_config_evidence","storage configuration and key-custody evidence"),("key_custody_evidence","evidence identifying data-read and key-administration custody"))),
"QN-ACCESS-001-Q10": S("shared_accounts", (("individual_accountability_requirement","the documented individual-accountability/shared-account requirement"),), (("shared_account_inventory","inventory of shared or generic accounts"),("shared_account_attribution","evidence of attribution or approved exception controls"))),
"QN-ACCESS-001-Q11": S("security_configuration", (("configuration_baseline_requirement","the documented security-configuration baseline/approval requirement"),), (("configuration_period_evidence","evidence the configuration remained effective through the examination period"),("configuration_change_record","change history or monitoring for security-relevant configuration"))),
# Network / endpoint
"QN-NETSEC-001-Q01": S("public_admin_exposure", (("public_admin_requirement","the documented restriction/approval requirement for public administrative interfaces"),), (("public_interface_inventory","inventory of publicly reachable administrative interfaces"),("exposure_approval","evidence each intended exposure is approved"))),
"QN-NETSEC-001-Q02": S("boundary_baseline", (("boundary_baseline","the approved boundary-rule baseline"),), (("live_boundary_configuration","the live boundary configuration"),("boundary_drift_detection","evidence of drift detection or comparison"))),
"QN-NETSEC-001-Q03": S("temporary_boundary_rule", (("temporary_rule_requirement","the documented temporary-rule expiry/closure requirement"),), (("temporary_rule_expiry","expiry or closure mechanism on temporary rules"),("temporary_rule_record","operating record showing temporary rule lifecycle"))),
"QN-NETSEC-001-Q04": S("transport_encryption", (("transport_requirement","the documented encrypted-transport requirement"),), (("transport_config_evidence","deployed endpoint configuration or verification output"),)),
"QN-NETSEC-001-Q05": S("data_egress", (("egress_requirement","the documented protected-data egress restriction/monitoring requirement"),), (("egress_route_inventory","inventory of protected-data egress routes"),("egress_control_evidence","evidence routes are restricted, logged, or monitored"))),
"QN-NETSEC-001-Q06": S("endpoint_protection", (("endpoint_requirement","the documented endpoint-protection requirement and asset scope"),), (("endpoint_coverage","measured protective-software coverage against an inventory"),("endpoint_detection_response","evidence detections are assigned and acted upon"))),
# Operations
"QN-OPS-001-Q01": S("configuration_vulnerability", (("configuration_monitoring_requirement","the documented security-change monitoring requirement"),("vulnerability_applicability_process","the documented process for assessing disclosed vulnerabilities against deployed technology")), (("configuration_change_detection","operating evidence of security-relevant change detection"),("vulnerability_applicability_evidence","record of vulnerability applicability assessment"))),
"QN-OPS-001-Q02": S("logging", (("logging_requirement","the documented central logging coverage and retention requirement"),), (("log_source_coverage","measured security-log source coverage"),("log_retention_evidence","operating/configuration evidence of retention"))),
"QN-OPS-001-Q03": S("alert_triage", (("triage_requirement","the documented alert triage ownership and timeframe"),), (("alert_triage_record","record of alert review, timing, owner, and disposition"),)),
"QN-OPS-001-Q04": S("incident_declaration", (("incident_criteria","written incident declaration criteria"),("incident_authority","roles authorized to declare/escalate incidents"),("external_reporting_path","documented intake path for customer/researcher reports")), (("incident_intake_evidence","operating record showing event intake/escalation"),)),
"QN-OPS-001-Q05": S("incident_exercise", (("exercise_requirement","the documented incident-response exercise requirement"),), (("latest_exercise","the most recent completed incident-response exercise"),("exercise_findings","findings from the exercise"),("exercise_actions","tracked actions resulting from the exercise"))),
"QN-OPS-001-Q06": S("postmortem", (("postmortem_trigger","the documented trigger for root-cause/postmortem review"),), (("postmortem_record","completed root-cause/postmortem record"),("postmortem_actions","tracked corrective actions from the review"))),
"QN-OPS-001-Q07": S("vulnerability_management", (("scan_scope_requirement","the documented vulnerability scanning scope"),("remediation_timeframe","severity-based remediation timeframe")), (("scan_coverage","operating evidence of scan coverage"),("overdue_handling","evidence of handling findings beyond remediation timeframe"))),
# Physical / media
"QN-PHYSEC-001-Q01": S("facility_security", (("facility_responsibility","documented responsibility model for self-operated versus provider-operated facilities"),), (("facility_inventory","inventory of facilities holding protected assets/endpoints"),("provider_physical_assurance","provider assurance for provider-operated facilities where applicable"))),
"QN-PHYSEC-001-Q02": S("physical_offboarding", (("physical_revocation_trigger","documented trigger for physical-access removal on departure/role change"),("logical_physical_alignment","documented alignment or distinction between logical and physical triggers")), (("physical_revocation_evidence","operating evidence of physical-access removal"),)),
"QN-PHYSEC-001-Q03": S("physical_access_review", (("physical_review_cadence","documented physical-access roster review cadence"),("physical_review_owner","documented review owner")), (("physical_latest_review","most recent completed physical-access review"),("physical_removal_evidence","evidence that identified physical access was removed"))),
"QN-PHYSEC-001-Q04": S("media_disposal", (("media_disposal_requirement","documented requirement to render protected data unrecoverable before media leaves control"),), (("media_disposal_record","record of disposal/transfer and sanitization"),("sanitization_verification","evidence data was rendered unrecoverable before disposition"))),
"QN-PHYSEC-001-Q05": S("cryptographic_erasure", (("crypto_erasure_requirement","documented cryptographic-erasure/cloud-deletion requirement"),), (("crypto_erasure_evidence","evidence of cryptographic erasure or provider deletion commitment"),("unrecoverability_evidence","evidence supporting data unrecoverability"))),
}
