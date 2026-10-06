# DriftGuard Evidence Benchmark

This benchmark is a regression/evaluation set for the deterministic evidence vocabulary currently implemented by DriftGuard. It is **not** a claim that all SOC 2 terminology is covered.

Current scope:
- MFA requirements and configuration evidence
- user/access review terminology
- termination/offboarding terminology
- privileged access terminology
- encryption-at-rest terminology
- transport-encryption terminology
- explicit negative/absence language intended to catch false inference
- format parity across TXT, MD, CSV, XLSX, DOCX and text-based PDF

`cases.json` contains 120 annotated language cases: 100 positive targets and 20 negative/adversarial cases. Positive cases specify facts that must be recovered; unlisted extra facts are not treated as false positives because the fixture does not claim exhaustive annotation. Negative cases must produce no material facts.

The automated gate requires:
- target recall >= 98%
- false-inference rate on negative cases = 0%
- the same grounded MFA requirement to survive all six currently supported file formats with provenance

The benchmark must grow as new evidence types are added. Scanned/image-only PDFs, OCR, vendor-specific exports, and evidence types not listed above are outside this benchmark's current measured scope.
