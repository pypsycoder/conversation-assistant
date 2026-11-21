"""Reproduce the independent synthetic offline expectations for history restoration."""
import argparse
import copy
from pathlib import Path
from backend.nightly_research import read, save, score, SECTIONS
from backend.history_course_repair import repair_history_course, repair_adjectival_history
from backend.complaint_quote_repair import repair_complaints
from backend.three_sections import provenance_errors
from scripts.evaluate_complaint_quote_repair import materialize, section_metrics


def evaluate(case, repair=repair_history_course):
    source, gold = case["source"], case["gold"]
    direct, _ = materialize(case["direct"]["sections"], case["direct"]["gaps"])
    control, control_review = materialize(case["control"]["sections"], case["control"]["gaps"])
    expected, expected_review = materialize(case["expected"]["sections"], case["expected"]["gaps"])
    assert repair_complaints(direct, source)[0] == control, case["id"]
    snapshot = copy.deepcopy((control, source))
    restored, changes, abstentions = repair(control, source)
    after, complaint_changes = repair_complaints(restored, source)
    assert after == expected, case["id"]
    assert (control, source) == snapshot, case["id"]
    assert not provenance_errors(after, source), case["id"]
    assert after["sections"]["life_history"] == control["sections"]["life_history"], case["id"]
    assert after["gaps"] == control["gaps"], case["id"]
    again, second_changes, _ = repair(after, source)
    assert again == after and not second_changes, case["id"]
    assert repair_complaints(again, source) == (after, []), case["id"]
    before_score, after_score = score(gold, control, control_review), score(gold, after, expected_review)
    assert after_score["tp"] >= before_score["tp"] and after_score["fn"] <= before_score["fn"], case["id"]
    assert after_score["covered_placements"] >= before_score["covered_placements"], case["id"]
    for key in ("unsupported_atoms", "temporal_errors", "source_errors", "polarity_errors", "duplicate_placements"):
        assert after_score[key] <= before_score[key], (case["id"], key)
    return dict(id=case["id"], focus=case["focus"], changes=changes, complaint_changes=complaint_changes,
                abstentions=abstentions, control=dict(metrics=before_score, sections=section_metrics(gold, control_review)),
                candidate=dict(metrics=after_score, sections=section_metrics(gold, expected_review)))


def main():
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument("--fixtures", type=Path, default=Path("examples/history-course-repair-v1/offline.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--adjectival", action="store_true")
    args=parser.parse_args()
    fixtures=read(args.fixtures)
    assert fixtures["synthetic"] is True
    repair=repair_adjectival_history if args.adjectival else repair_history_course
    cases=[evaluate(c, repair=repair) for c in fixtures["cases"]]
    keys=("tp","fp","fn","gold_facts","covered_placements","required_placements","unsupported_atoms",
          "temporal_errors","source_errors","polarity_errors","duplicate_placements")
    totals={side:{k:sum(c[side]["metrics"][k] for c in cases) for k in keys} for side in ("control","candidate")}
    save(args.output,dict(sample_size=len(cases),totals=totals,cases=cases))
    print(totals)


if __name__ == "__main__":
    main()
