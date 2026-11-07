"""Offline cycle 01: compare printers; never calls a model or rewrites prior runs."""
import argparse
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.nightly_research import read, save, digest, exclusive_lock
from backend import clinical_event_properties_source_print_v2 as control
from backend import clinical_event_properties_source_print_v3 as candidate

LOCAL_RUNS = ROOT / "data/clinical-base-source-r1-2026-10-26/online/arm-s/runs"


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--replay-local", action="store_true",
                        help="Replay the nine previously documented synthetic S registries, local only")
    args = parser.parse_args()
    fixture = ROOT / "examples/source-boundaries-v1.json"
    corpus = read(fixture)
    if corpus["synthetic"] is not True:
        raise ValueError("Explicit synthetic rubric required")
    files = [fixture, Path(__file__), ROOT / "docs/research/cycle-01-source-boundaries-plan.md",
             ROOT / "tests/test_source_print_v3.py"]
    files += [ROOT / "backend" / (name + ".py") for name in (
        "clinical_event_properties_source_print_v2", "clinical_event_properties_source_print_v3",
        "clinical_event_properties_source_v1", "clinical_event_properties_e1_events",
        "clinical_event_properties_e1_repair", "clinical_event_properties_e1_fixed",
        "clinical_event_properties_v1")]
    registries = []
    if args.replay_local:
        # Provenance: the three agent-authored dialogues approved in the old S report.
        # Their historical JSON lacks a synthetic flag; do not rewrite it or accept arbitrary paths.
        for run in ("r1", "r2", "r3"):
            for case in ("case-11", "case-12", "case-13"):
                registry = LOCAL_RUNS / run / "registries" / (case + ".json")
                sidecar = LOCAL_RUNS / run / "sidecars" / (case + ".json")
                files.extend((registry, sidecar))
                registries.append((run, case, registry, sidecar))
    hashes = {p.relative_to(ROOT).as_posix(): digest(p) for p in files}
    with exclusive_lock(ROOT / "data/nightly/research.lock"):
        args.output.mkdir(parents=True, exist_ok=False)
        save(args.output / "freeze.json", {"files_sha256": hashes, "api_calls": 0,
             "scope": "source marker correctness, not extraction F1", "physician_reviewed": False})
        judgments = []
        for case in corpus["cases"]:
            a, b = control.mark(case["text"], case["reported_by"]), candidate.mark(case["text"], case["reported_by"])
            judgments.append({**case, "control": {"text": a[0], "added": a[1]},
                "candidate": {"text": b[0], "added": b[1]},
                "control_correct": a[1] == case["expected_added"],
                "candidate_correct": b[1] == case["expected_added"]})
        save(args.output / "rubric-results.json", judgments)
        replays, changes = [], []
        for run, case, reg_path, side_path in registries:
            registry, sidecar = read(reg_path), read(side_path)
            before = copy.deepcopy((registry, sidecar))
            a, b = control.project(registry, sidecar), candidate.project(registry, sidecar)
            if before != (registry, sidecar):
                raise RuntimeError("Projection mutated its input")
            row_count = 0
            for section, rows in a["evidence"].items():
                for old, new in zip(rows, b["evidence"][section], strict=True):
                    if {k: v for k, v in old.items() if k != "text"} != {k: v for k, v in new.items() if k != "text"}:
                        raise RuntimeError("Non-text fields changed")
                    row_count += 1
                    if old["text"] != new["text"]:
                        changes.append({"run": run, "case": case, "section": section,
                            "property_id": old["property_id"], "old": old["text"], "new": new["text"]})
            replays.append({"run": run, "case": case, "rows": row_count})
        save(args.output / "replay-changes.json", changes)
        if any(digest(ROOT / path) != sha for path, sha in hashes.items()):
            raise RuntimeError("Frozen files changed")
        splits = {}
        for split in ("diagnostic", "validation"):
            subset = [c for c in judgments if c["split"] == split]
            splits[split] = {"n": len(subset), "control_correct": sum(c["control_correct"] for c in subset),
                "candidate_correct": sum(c["candidate_correct"] for c in subset)}
        summary = {"splits": splits, "api_calls": 0, "tokens": 0, "model_cost": 0,
            "replay_units": len(replays), "replay_rows": sum(r["rows"] for r in replays),
            "changed_replay_rows": len(changes), "inputs_unchanged": True,
            "non_text_fields_unchanged": True, "replays": replays,
            "decision": "pending_manual_review_of_changes", "physician_reviewed": False}
        save(args.output / "summary.json", summary)
        print(json.dumps(summary, ensure_ascii=False))
        if changes:
            print(json.dumps(changes, ensure_ascii=False))


if __name__ == "__main__":
    main()
