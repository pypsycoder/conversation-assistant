"""Evaluate three new semantic positives and nine independent abstention boundaries."""
import argparse
import copy
from pathlib import Path
from backend.nightly_research import read, save, score
from backend.presence_onset_repair import repair_presence_onset
from backend.three_sections import provenance_errors
from scripts.evaluate_complaint_quote_repair import materialize, section_metrics

def evaluate(fixtures):
    cases = []
    for case in fixtures["cases"]:
        annotated = case["evaluation_scope"] == "semantic_positive"
        before, review = materialize(case["baseline"]["sections"], case["baseline"]["gaps"]) if annotated else (case["baseline"],None)
        expected, after_review = materialize(case["expected"]["sections"], case["expected"]["gaps"]) if annotated else (case["expected"],None)
        snapshot = copy.deepcopy((before,case["source"]))
        after, changes, abstentions = repair_presence_onset(before,case["source"])
        assert after == expected, case["id"]
        assert (before,case["source"]) == snapshot,case["id"]
        assert not provenance_errors(after,case["source"]),case["id"]
        for key in ["complaints","life_history"]:
            assert after["sections"][key] == before["sections"][key],case["id"]
        assert after["gaps"] == before["gaps"],case["id"]
        assert repair_presence_onset(after,case["source"])[0] == after,case["id"]
        assert not repair_presence_onset(after,case["source"])[1],case["id"]
        item=dict(id=case["id"],focus=case["focus"],scope=case["evaluation_scope"],changes=changes,abstentions=abstentions)
        if annotated:
            item["control"]=dict(metrics=score(case["gold"],before,review),sections=section_metrics(case["gold"],review))
            item["candidate"]=dict(metrics=score(case["gold"],after,after_review),sections=section_metrics(case["gold"],after_review))
            for key in ["tp","covered_placements"]:assert item["candidate"]["metrics"][key]>=item["control"]["metrics"][key]
        else:
            assert not changes and after==before,case["id"]
        cases.append(item)
    positives=[c for c in cases if c["scope"]=="semantic_positive"]
    keys=["tp","fp","fn","gold_facts","covered_placements","required_placements","unsupported_atoms","temporal_errors","source_errors","duplicate_placements","polarity_errors"]
    totals={side:{k:sum(c[side]["metrics"][k] for c in positives) for k in keys} for side in ["control","candidate"]}
    return dict(semantic_positive_count=len(positives),boundary_preservation_count=len(cases)-len(positives),totals=totals,cases=cases)

def main():
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument("--fixtures",type=Path,default=Path("examples/presence-onset-v1/offline.json"))
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    result=evaluate(read(args.fixtures));save(args.output,result)
    print(result["totals"])
if __name__=="__main__":main()
