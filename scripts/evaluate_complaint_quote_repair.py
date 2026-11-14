"""Replay the frozen synthetic complaint repair study without API calls."""

import argparse
import copy
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.complaint_quote_repair import repair_complaints
from backend.nightly_research import SECTIONS, read, save, score
from backend.three_sections import provenance_errors

CASES = ROOT / "examples/complaint-quote-repair-v1/cases.json"
METRICS = (
    "tp", "fp", "fn", "unsupported_atoms", "covered_placements",
    "required_placements", "correct_placements", "predicted_placements",
    "duplicate_placements", "polarity_errors", "temporal_errors", "source_errors",
)
PRESERVED = (
    "tp", "fp", "fn", "unsupported_atoms", "covered_placements", "required_placements",
    "duplicate_placements", "polarity_errors", "temporal_errors", "source_errors",
)


def materialize(sections, gaps):
    result = {"sections": {}, "gaps": gaps}
    review = {"reviewer": "Codex", "physician_reviewed": False, "rows": []}
    for section, rows in sections.items():
        result["sections"][section] = []
        for index, row in enumerate(rows):
            result["sections"][section].append({"text": row["text"], "evidence": row["evidence"]})
            review["rows"].append({
                "row_id": f"{section}:{index}",
                "complete_fact_ids": row["complete"],
                "partial_fact_ids": row["partial"],
                "unsupported_atoms": 0,
                "polarity_errors": 0,
                "temporal_errors": row.get("temporal_errors", 0),
                "source_errors": 0,
            })
    return result, review


def section_metrics(gold, review):
    facts = {fact["id"]: fact for fact in gold["facts"]}
    sections = {}
    for section in SECTIONS:
        required = {fact_id for fact_id, fact in facts.items() if section in fact["required_sections"]}
        predicted = {fact_id for row in review["rows"] if row["row_id"].startswith(section + ":")
                     for fact_id in row["complete_fact_ids"]}
        allowed = {fact_id for fact_id, fact in facts.items() if section in fact["allowed_sections"]}
        sections[section] = {"required": len(required), "covered": len(required & predicted),
                             "disallowed": len(predicted - allowed)}
    return sections


def evaluate_case(case):
    baseline = case["baseline"]
    gold, source = case["gold"], case["source"]
    before, before_review = materialize(baseline["sections"], baseline["gaps"])
    expected_sections = {**baseline["sections"], "complaints": case["expected_complaints"]}
    expected, after_review = materialize(expected_sections, baseline["gaps"])
    snapshot = copy.deepcopy((before, source))
    after, changes = repair_complaints(before, source)
    assert (before, source) == snapshot, case["id"]
    assert after == expected, case["id"]
    assert not provenance_errors(after, source), case["id"]
    assert repair_complaints(after, source) == (after, []), case["id"]
    for section in ("illness_history", "life_history"):
        assert after["sections"][section] == before["sections"][section], case["id"]
    assert after["gaps"] == before["gaps"], case["id"]

    before_score = score(gold, before, before_review)
    after_score = score(gold, after, after_review)
    assert all(before_score[key] == after_score[key] for key in PRESERVED), case["id"]
    return {"id": case["id"], "focus": case["focus"], "changes": changes,
            "before": {key: before_score[key] for key in METRICS},
            "after": {key: after_score[key] for key in METRICS},
            "sections_before": section_metrics(gold, before_review),
            "sections_after": section_metrics(gold, after_review)}


def summarize(cases):
    summary = {}
    for side in ("before", "after"):
        summary[side] = {key: sum(case[side][key] for case in cases) for key in METRICS}
        summary[side]["sections"] = {
            section: {key: sum(case[f"sections_{side}"][section][key] for case in cases)
                      for key in ("required", "covered", "disallowed")}
            for section in SECTIONS
        }
    return summary


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--fixtures", type=Path, default=CASES)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    started = time.perf_counter()
    fixtures = read(args.fixtures)
    canonical = json.dumps(fixtures, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    checksum = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    cases = [evaluate_case(case) for case in fixtures]
    totals = summarize(cases)
    for case in cases:
        before = case["sections_before"]["complaints"]["disallowed"]
        after = case["sections_after"]["complaints"]["disallowed"]
        assert after <= before, case["id"]
    save(args.output, {"synthetic": True, "model_calls": 0, "model_tokens": 0,
                       "fixtures_canonical_sha256": checksum, "evaluation_seconds": time.perf_counter() - started,
                       "cases": cases, "totals": totals})


if __name__ == "__main__":
    main()
