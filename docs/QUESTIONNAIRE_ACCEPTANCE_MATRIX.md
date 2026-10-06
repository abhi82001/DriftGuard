# CP009 questionnaire coverage and acceptance matrix

This is a measured inventory, **not** a completed independent expected-result oracle. The existing deterministic evaluator only has eight executable specifications. Do not equate NOT_ESTABLISHED for unsupported specifications with a validated finding.

| Requirement | Question (abridged) | Expected evidence IDs | Executable specification | Actual LOCAL result | Provenance / limitation |
|---|---|---|---|---|---|
| QN-ACCESS-001-Q01 | Is a second authentication factor enforced for all human access to in-scope  | EV-IAM-001 | YES | PARTIALLY_ESTABLISHED | Information_Security_Policy.docx:paragraph 8; Information_Security_Policy.docx:paragraph 8 |
| QN-ACCESS-001-Q02 | List every authentication path into the in-scope environment that is NOT gov | EV-IAM-001 | NO — OPEN | NOT_ESTABLISHED | No recognized claim; evaluation not implemented |
| QN-ACCESS-001-Q03 | How frequently are user access reviews performed, and does that match the ca | EV-ACCESS-001 | YES | NOT_ESTABLISHED | No recognized supporting claim |
| QN-ACCESS-001-Q04 | Which identity populations are included in the access review: employees, con | EV-ACCESS-001 | YES | NOT_ESTABLISHED | No recognized supporting claim |
| QN-ACCESS-001-Q05 | When an access review flags an entitlement for removal, how is the removal t | EV-ACCESS-001 | YES | NOT_ESTABLISHED | No recognized supporting claim |
| QN-ACCESS-001-Q06 | What is your committed timeframe for revoking system access after an employe | EV-ACCESS-001 | YES | NOT_ESTABLISHED | No recognized supporting claim |
| QN-ACCESS-001-Q07 | Before system credentials are issued, what record is created showing who app | EV-ACCESS-002 | NO — OPEN | NOT_ESTABLISHED | No recognized claim; evaluation not implemented |
| QN-ACCESS-001-Q08 | Is administrative or production-data privilege held on a standing basis, or  | EV-ACCESS-003 | YES | CLARIFICATION_REQUIRED | No recognized supporting claim |
| QN-ACCESS-001-Q09 | Which storage holding protected information is encrypted at rest, and who ca | EV-CRYPTO-001 | YES | PARTIALLY_ESTABLISHED | Encryption_and_Key_Management_Policy.docx:paragraph 4 |
| QN-ACCESS-001-Q10 | Are any accounts shared between individuals, or used generically, such that  | EV-ACCESS-003 | NO — OPEN | NOT_ESTABLISHED | No recognized claim; evaluation not implemented |
| QN-ACCESS-001-Q11 | How do you demonstrate that a security-relevant configuration, such as the a | EV-CONFIG-001 | NO — OPEN | NOT_ESTABLISHED | No recognized claim; evaluation not implemented |
| QN-NETSEC-001-Q01 | Which administrative or management interfaces in your environment are reacha | EV-NETSEC-001 | NO — OPEN | NOT_ESTABLISHED | No recognized claim; evaluation not implemented |
| QN-NETSEC-001-Q02 | Is there an approved baseline for your boundary rules, and how would you lea | EV-NETSEC-001, EV-CONFIG-001 | NO — OPEN | NOT_ESTABLISHED | No recognized claim; evaluation not implemented |
| QN-NETSEC-001-Q03 | When a boundary rule is opened temporarily for troubleshooting or a migratio | EV-CONFIG-001 | NO — OPEN | NOT_ESTABLISHED | No recognized claim; evaluation not implemented |
| QN-NETSEC-001-Q04 | What is your minimum accepted transport protocol version, and how do you ver | EV-CRYPTO-002 | YES | PARTIALLY_ESTABLISHED | TLS_Validation_Report.pdf:page 1 |
| QN-NETSEC-001-Q05 | By what routes can protected information leave your environment — bulk expor | EV-CRYPTO-002, EV-ENDPOINT-001 | NO — OPEN | NOT_ESTABLISHED | No recognized claim; evaluation not implemented |
| QN-NETSEC-001-Q06 | On which asset classes is protective software deployed, what does coverage m | EV-ENDPOINT-001, EV-ENDPOINT-002 | NO — OPEN | NOT_ESTABLISHED | No recognized claim; evaluation not implemented |
| QN-OPS-001-Q01 | How would you learn that a security-relevant configuration had changed, and  | EV-CONFIG-001 | NO — OPEN | NOT_ESTABLISHED | No recognized claim; evaluation not implemented |
| QN-OPS-001-Q02 | Which components send security logs to a central store, what is that coverag | EV-LOG-001 | NO — OPEN | NOT_ESTABLISHED | No recognized claim; evaluation not implemented |
| QN-OPS-001-Q03 | When an alert fires, who looks at it, within what timeframe, and what record | EV-MONITOR-001 | NO — OPEN | NOT_ESTABLISHED | No recognized claim; evaluation not implemented |
| QN-OPS-001-Q04 | What written criteria determine that a security event is an incident, who ma | EV-INCIDENT-001 | NO — OPEN | NOT_ESTABLISHED | No recognized claim; evaluation not implemented |
| QN-OPS-001-Q05 | When was your incident response plan last exercised, what did the exercise r | EV-INCIDENT-002 | NO — OPEN | NOT_ESTABLISHED | No recognized claim; evaluation not implemented |
| QN-OPS-001-Q06 | After an incident is closed, what triggers a root-cause review, and where do | EV-INCIDENT-001 | NO — OPEN | NOT_ESTABLISHED | No recognized claim; evaluation not implemented |
| QN-OPS-001-Q07 | What defines the scope of your vulnerability scanning, and what happens when | EV-VULN-001 | NO — OPEN | NOT_ESTABLISHED | No recognized claim; evaluation not implemented |
| QN-PHYSEC-001-Q01 | Which facilities do you operate yourself where protected information assets  | EV-PHYSEC-001, EV-PHYSEC-002 | NO — OPEN | NOT_ESTABLISHED | No recognized claim; evaluation not implemented |
| QN-PHYSEC-001-Q02 | When someone leaves or changes role, what triggers removal of their physical | EV-PHYSEC-001 | NO — OPEN | NOT_ESTABLISHED | No recognized claim; evaluation not implemented |
| QN-PHYSEC-001-Q03 | How often is the physical access roster reviewed, who reviews it, and what h | EV-PHYSEC-001 | NO — OPEN | NOT_ESTABLISHED | No recognized claim; evaluation not implemented |
| QN-PHYSEC-001-Q04 | When a device or storage medium holding protected information leaves your co | EV-ASSET-001 | NO — OPEN | NOT_ESTABLISHED | No recognized claim; evaluation not implemented |
| QN-PHYSEC-001-Q05 | Where you rely on cryptographic erasure or on a cloud provider's deletion co | EV-ASSET-001, EV-CRYPTO-001 | NO — OPEN | NOT_ESTABLISHED | No recognized claim; evaluation not implemented |
