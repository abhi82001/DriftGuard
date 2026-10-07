# CP015 Performance Report

Controlled local deterministic benchmark; semantic provider unavailable and therefore not executed. These timings are not network-provider benchmarks.

| Files | Parsed | Errors | Ingestion s | Structured QA s | Assessment s | Reconciliation s | Total s |
|---:|---:|---:|---:|---:|---:|---:|---:|
|10|10|0|0.0001|0.0000|0.0107|0.0001|0.0108|
|25|25|0|0.0003|0.0000|0.0066|0.0000|0.0069|
|50|50|0|0.0002|0.0000|0.0122|0.0000|0.0124|
|100|100|0|0.0003|0.0000|0.0250|0.0000|0.0253|

All requested internal benchmark files were parsed; there was no silent truncation. The public browser/API upload boundary intentionally remains 25 files per request for resource control. Raw machine-readable measurements are in `artifacts/cp015_performance.json`.
