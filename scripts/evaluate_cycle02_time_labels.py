"""Offline continuation from fixed paired outputs; all suppressed rows stay logged."""
import argparse
import copy
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.nightly_research import read, save, digest, exclusive_lock, SECTIONS
from backend import source_time_label_dedup as candidate
from backend.s_direct_comparison import section_rows
from backend.paired_clinical_review import evaluate


def main():
    parser = argparse.ArgumentParser(__doc__)
    for name in ("run", "reviews", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    files = [Path(__file__), Path(candidate.__file__), ROOT / "docs/research/cycle-02-followup-time-duplicates-plan.md"]
    for case in ("d01", "d02", "d03"):
        files += [args.run / case / "s" / n for n in ("registry.json", "sidecar.json", "result.json")]
        files += [args.reviews / case / "s/review.json", ROOT / f"examples/nightly-v1/{case}.gold.json"]
    hashes = {str(p): digest(p) for p in files}
    with exclusive_lock(ROOT / "data/nightly/research.lock"):
        args.output.mkdir(parents=True, exist_ok=False)
        save(args.output / "freeze.json", {"files_sha256": hashes, "api_calls": 0})
        metrics, suppressed = [], []
        for case in ("d01", "d02", "d03"):
            registry, sidecar = (read(args.run / case / "s" / n) for n in ("registry.json", "sidecar.json"))
            before = copy.deepcopy((registry, sidecar))
            previous = read(args.run / case / "s/result.json")
            projection = candidate.project(registry, sidecar)
            if (registry, sidecar) != before:
                raise RuntimeError("Input mutation")
            result = section_rows(projection)
            review = read(args.reviews / case / "s/review.json")
            if review["result_sha256"] != digest(args.run / case / "s/result.json"):
                raise ValueError("Review not bound to baseline")
            remap, own = {}, {}
            for section in SECTIONS:
                new_ids = {row["property_id"]: f"{section}:{i}" for i, row in enumerate(result["sections"][section])}
                for row in projection["evidence"][section]:
                    for pid in row.get("merged_property_ids", []):
                        new_ids[pid] = new_ids[row["property_id"]]
                for i, row in enumerate(previous["sections"][section]):
                    oldid = f"{section}:{i}"
                    remap[oldid] = new_ids[row["property_id"]]
                    if row["property_id"] in {r["property_id"] for r in result["sections"][section]}:
                        own[remap[oldid]] = oldid
                        newrow = result["sections"][section][int(remap[oldid].split(":")[1])]
                        if row != newrow:
                            raise RuntimeError("Kept row changed")
            lookup = {r["id"]: r for r in review["rows"]}
            review["rows"] = [{**lookup[oldid], "id": newid} for newid, oldid in own.items()]
            for j in review["criteria"]:
                j["rows"] = list(dict.fromkeys(remap[r] for r in j["rows"]))
            duplicates = []
            for group in review["duplicates"]:
                ids = list(dict.fromkeys(remap[r] for r in group["rows"]))
                if len(ids) > 1:
                    duplicates.append({**group, "rows": ids})
            review["duplicates"] = duplicates
            review["offline_note"] = "Judgments transferred only after kept-row equality and exact-grounding checks; suppression log reviewed by Codex."
            target = args.output / case
            save(target / "result.json", result)
            review["result_sha256"] = digest(target / "result.json")
            save(target / "review.json", review)
            save(target / "projection.json", projection)
            metric = evaluate(read(ROOT / f"examples/nightly-v1/{case}.gold.json"), result, review)
            save(target / "metrics.json", metric)
            metrics.append({"case": case, **metric})
            suppressed.extend({"case": case, **r} for r in projection["suppressed_duplicate_rows"])
        if any(digest(Path(p)) != sha for p, sha in hashes.items()):
            raise RuntimeError("Frozen input changed")
        summary = {"api_calls": 0, "suppressed_rows": suppressed, "suppressed_count": len(suppressed),
            "tp": sum(m["tp"] for m in metrics), "fp": sum(m["fp"] for m in metrics),
            "complete_required_placements": sum(m["complete_required_placements"] for m in metrics),
            "duplicate_groups": sum(m["duplicate_groups"] for m in metrics),
            "output_rows": sum(m["output_rows"] for m in metrics), "inputs_unchanged": True,
            "kept_rows_unchanged": True, "decision": "candidate_only_not_default"}
        save(args.output / "summary.json", summary)
        print(__import__("json").dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
