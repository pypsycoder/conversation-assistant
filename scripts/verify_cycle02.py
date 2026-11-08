"""Recompute judgments and replay all S receipts from the published synthetic evidence."""
import argparse
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.nightly_research import read, digest
from backend.paired_clinical_review import evaluate
from backend.s_direct_comparison import as_s_source, windows, s_request, apply_s_output, section_rows
from backend import clinical_event_properties_v1 as core
from backend import clinical_event_properties_source_print_v3 as printer


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--evidence", type=Path, default=ROOT / "reports/evidence/cycle-02")
    args = parser.parse_args()
    count = 0
    cases = read(args.evidence / "paired/freeze.json")["cases"]
    if not cases or not set(cases) <= {"d01", "d02", "d03", "v01", "v02"}:
        raise ValueError("Only the declared synthetic cases are supported")
    for case in cases:
        gold_path = ROOT / f"examples/nightly-v1/{case}.gold.json"
        source = as_s_source(read(ROOT / f"examples/nightly-v1/{case}.source.json"))
        for arm in ("direct", "s"):
            folder = args.evidence / "paired" / case / arm
            result_path = folder / "result.json"
            reviews = args.evidence / "reviews" / case / arm
            review = read(reviews / "review.json")
            if review["result_sha256"] != digest(result_path) or review["gold_sha256"] != digest(gold_path):
                raise ValueError("Review binding changed")
            expected = read(reviews / "metrics.json")
            if evaluate(read(gold_path), read(result_path), review) != expected:
                raise ValueError("Metric mismatch")
        registry, sidecar = core.empty_registry(), {}
        for window in windows(source):
            target = window["target_turn"]["id"]
            receipt = read(args.evidence / "paired" / case / "s" / target / "response.json")
            if receipt["request"] != s_request(window, registry):
                raise ValueError("S dynamic request does not match replayed registry")
            if receipt["validation_errors"]:
                raise ValueError("This verifier expects the fully accepted original run")
            applied, sidecar = apply_s_output(receipt["parsed"], registry, sidecar, source, window)
            if not applied["accepted"]:
                raise ValueError("Previously accepted patch rejected")
            registry = applied["registry"]
            count += 1
        if section_rows(printer.project(registry, sidecar)) != read(args.evidence / "paired" / case / "s/result.json"):
            raise ValueError("Final S output differs from physical receipt replay")
        if registry != read(args.evidence / "paired" / case / "s/registry.json"):
            raise ValueError("Final registry differs")
    print(json.dumps({"criterion_reviews_verified": 2*len(cases), "s_requests_replayed": count, "api_calls": 0}))


if __name__ == "__main__":
    main()
