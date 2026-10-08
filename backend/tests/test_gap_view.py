#!/usr/bin/env python3
"""Gap presentation: grouping by document, customer labels, priority, no bare dash, CSV/print export."""
import csv
import io
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from documents import AreaResult  # noqa: E402
from evidence.gap_view import (NO_GUIDANCE, build_gap_view, gaps_csv, guidance_for,  # noqa: E402
                               render_groups, render_request_page)
from evidence.report import GAP_KIND_LABELS  # noqa: E402

VERDICT = re.compile(r"\b(compliant|non-compliant|pass(?:ed)?|fail(?:ed|ure)?|certified|audit opinion)\b", re.I)
DOC = "User Access Review Record"


def area(qid, status, missing=(), needed=(DOC,), area_name="Access"):
    return AreaResult("QN-X", qid, area_name, f"Question {qid}?", status, f"why {qid}",
                      missing_facts=list(missing), evidence_needed=list(needed))


def test_groups_by_document_listing_every_affected_question():
    v = build_gap_view([area("Q1", "NOT_ESTABLISHED", needed=(DOC, "IdP Export")),
                        area("Q2", "NOT_ESTABLISHED"), area("Q3", "ESTABLISHED")])
    docs = {g["document"]: g for g in v["groups"]}
    assert [q["question_id"] for q in docs[DOC]["questions"]] == ["Q1", "Q2"]
    assert [q["question_id"] for q in docs["IdP Export"]["questions"]] == ["Q1"]
    assert "Q3" not in {q["question_id"] for g in v["groups"] for q in g["questions"]}


def test_four_distinct_customer_labels_and_no_verdict_words():
    v = build_gap_view(
        [area("Q1", "NOT_ESTABLISHED", needed=("A",)), area("Q2", "PARTIALLY_ESTABLISHED", ["x"], needed=("B",)),
         area("Q3", "CONFLICT", ["resolve conflict: mfa"], needed=("C",))],
        [dict(filename="scan.pdf", status="UNREADABLE_SCAN_NEEDS_OCR", detail="no text", remediation="")])
    labels = {g["document"]: g["kind_label"] for g in v["groups"]}
    assert labels == {"A": "Evidence missing", "B": "Provided but insufficient", "C": "Conflicting",
                      "scan.pdf": "Unreadable file"}
    assert len(set(GAP_KIND_LABELS.values())) == len(GAP_KIND_LABELS)
    assert not any(VERDICT.search(x) for x in GAP_KIND_LABELS.values())


def test_priority_conflicts_then_most_questions_then_partial_then_unreadable():
    v = build_gap_view(
        [area("Q1", "PARTIALLY_ESTABLISHED", ["m"], needed=("Partial doc",)),
         area("Q2", "PARTIALLY_ESTABLISHED", ["m"], needed=("Partial doc",)),
         area("Q3", "NOT_ESTABLISHED", needed=("Small missing",)),
         area("Q4", "NOT_ESTABLISHED", needed=("Big missing",)), area("Q5", "NOT_ESTABLISHED", needed=("Big missing",)),
         area("Q6", "CONFLICT", ["resolve conflict: x"], needed=("Conflict doc",))],
        [dict(filename="bad.xlsx", status="CORRUPT", detail="corrupt", remediation="Re-export.")])
    assert [g["document"] for g in v["groups"]] == ["Conflict doc", "Big missing", "Small missing",
                                                     "Partial doc", "bad.xlsx"]
    assert [g["priority"] for g in v["groups"]] == [1, 2, 3, 4, 5]


def test_guidance_comes_from_knowledge_or_says_none():
    assert guidance_for("Definitely Not A Real Document") == NO_GUIDANCE
    real = guidance_for(DOC)
    assert real != NO_GUIDANCE and real.strip()
    v = build_gap_view([area("Q1", "NOT_ESTABLISHED", needed=("Not In Knowledge",))])
    assert v["groups"][0]["guidance"] == NO_GUIDANCE


def test_never_renders_a_dash_as_a_missing_item():
    v = build_gap_view([area("Q1", "NOT_ESTABLISHED", missing=["—", " "], needed=()),
                        area("Q2", "CLARIFICATION_REQUIRED", missing=["—"])])
    for g in v["groups"]:
        assert g["needs"] and all(n.strip() not in ("", "—") for n in g["needs"])
    assert "&mdash;" not in render_groups(v) and "—" not in render_groups(v) + gaps_csv(v)
    assert "<td>&mdash;</td>" not in render_request_page(v, "V", "id")
    for rows in v["areas"].values():
        for r in rows:
            assert r["missing"] and all(m.strip() not in ("", "—") for m in r["missing"])


def test_csv_is_consolidated_one_row_per_document_and_safe():
    v = build_gap_view([area("Q1", "NOT_ESTABLISHED", needed=("=cmd()",)), area("Q2", "NOT_ESTABLISHED")])
    rows = list(csv.reader(io.StringIO(gaps_csv(v))))
    assert rows[0][1] == "Requested document" and len(rows) == 3
    assert rows[1][1].startswith("'=") and rows[2][3] == "Q2"
    assert rows[2][2] == "Evidence missing"


def test_routes_render_group_strip_csv_and_print_page():
    import test_cp014_ui_acceptance as ui
    aid = ui.make_assessment()
    st, text, _, _ = ui.call("GET", f"/doc-results/{aid}")
    assert st == 200 and "Gaps to close" in text and "gv-strip" in text and "By control area" in text
    st, page, _, _ = ui.call("GET", f"/gaps/{aid}")
    assert st == 200 and "Evidence request" in page and "&mdash;</td>" not in page
    st, body, _, hdr = ui.call("GET", f"/gaps-csv/{aid}")
    assert st == 200 and hdr[b"content-type"].startswith(b"text/csv") and body.startswith("Priority,")


def test_guidance_is_matched_to_the_requested_document_not_first_remediation_in_file_order():
    termination = "termination and revocation"
    provisioning = "direct administrative provisioning"
    for doc in ("Multi-Factor Authentication Enforcement Configuration",
                "Configuration Change History and Drift Record",
                "Endpoint and Workload Protection Coverage Report"):
        text = guidance_for(doc).lower()
        assert termination not in text and provisioning not in text and "removable media" not in text, doc
    assert "access review" not in guidance_for("Configuration Change History and Drift Record").lower()
    assert "termination and revocation" not in guidance_for("User Access Review Record").lower()
