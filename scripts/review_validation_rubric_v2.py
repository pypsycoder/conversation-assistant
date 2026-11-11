"""Rescore the saved cycle-03 outputs under the November 11 section decisions."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.nightly_research import SECTIONS, read, save
from backend.paired_clinical_review import evaluate
from scripts.review_validation_cycle03 import judgment, refs

PACKET = ROOT / "docs/clinical-review/2026-11-08"
CYCLE = ROOT / "reports/evidence/cycle-03"
DECISIONS = {
    "R1": "allowed_but_not_required",
    "R2": "exclude_from_complaints",
    "R3": "life_history_required",
}
COMPLAINTS, ILLNESS, LIFE = SECTIONS


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def lf_bytes(path):
    return path.read_bytes().replace(b"\r\n", b"\n")


def verify_source_packet():
    manifest = read(PACKET / "input-manifest.json")
    form = read(PACKET / "review-template.json")
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if sha256(canonical) != form["input_manifest_sha256"]:
        raise ValueError("The completed form must refer to the original packet")
    received = {question["id"]: question["decision"] for question in form["questions"]}
    if form["status"] != "decisions_received" or received != DECISIONS:
        raise ValueError("This scorer implements the recorded November 11 decisions")
    for name, expected in manifest["files_sha256"].items():
        if sha256(lf_bytes(ROOT / name)) != expected:
            raise ValueError(f"Saved source changed: {name}")


def v01_criteria(arm, old):
    if arm == "direct":
        symptom = timing = duration = refs(COMPLAINTS, 0) + refs(ILLNESS, 0)
        cause = refs(ILLNESS, 0)
        cause_sections = [ILLNESS]
    else:
        duration = refs(COMPLAINTS, 0) + refs(ILLNESS, 0)
        timing = refs(COMPLAINTS, 1) + refs(ILLNESS, 1)
        symptom = duration + timing
        cause = refs(COMPLAINTS, 2) + refs(ILLNESS, 2)
        cause_sections = [COMPLAINTS, ILLNESS]
    return [
        old["criteria"][0],
        judgment("f2_nausea", symptom, [COMPLAINTS, ILLNESS]),
        judgment("f2_morning", timing, [COMPLAINTS, ILLNESS]),
        judgment("f2_duration", duration, [COMPLAINTS, ILLNESS]),
        judgment("f2_cause_unknown", cause, cause_sections,
                 reason="По R1 причина обязательна в анамнезе заболевания и допустима в жалобах."),
    ]


def v02_criteria(arm, old, result):
    phases = []
    for index, phase in enumerate(("february", "march", "current")):
        rows = refs(ILLNESS, index)
        complete = [ILLNESS]
        present = [ILLNESS]
        if arm == "s":
            rows += refs(COMPLAINTS, index)
            complete = present = [COMPLAINTS, ILLNESS]
        elif phase == "current":
            rows += refs(COMPLAINTS, 0)
            present = [COMPLAINTS, ILLNESS]
        phases.append(judgment("f1_" + phase, rows, complete, present,
                               reason="Фаза сохранена в анамнезе заболевания. R2 исключает текущее общее ухудшение из жалоб. Прошлые фазы относятся к анамнезу заболевания."))
    if arm == "direct":
        gap = result["gaps"][0]
        if gap["topic"] != "psychiatric_family_history_father" or gap["status"] != "patient_does_not_know":
            raise ValueError("The saved father's history gap changed")
        unknown = judgment("f3_father_unknown", [], [], status="missing",
                           reason="Неизвестность сохранена в gaps:0. R3 требует явно указать её в анамнезе жизни.")
        contact_index = 1
    else:
        unknown = judgment("f3_father_unknown", refs(LIFE, 1), [LIFE],
                           reason="Неизвестность явно записана в анамнезе жизни.")
        contact_index = 2
    return phases + [old["criteria"][1], unknown, judgment("f3_no_contact", refs(LIFE, contact_index), [LIFE])]


def review_case(case, arm):
    result_path = CYCLE / "paired" / case / arm / "result.json"
    gold_path = ROOT / f"examples/nightly-v2/{case}.gold.json"
    result = read(result_path)
    gold = read(gold_path)
    original_review_path = CYCLE / "reviews" / case / arm / "review.json"
    review = read(original_review_path)
    # The original reviewer hashed the Windows files. Accept the same bytes
    # with either checkout line ending when verifying that earlier binding.
    result_lf = lf_bytes(result_path)
    if review["result_sha256"] not in {sha256(result_lf), sha256(result_lf.replace(b"\n", b"\r\n"))}:
        raise ValueError(f"Original review does not bind to {case}/{arm}")
    expected_rows = {f"{section}:{i}": row["text"]
                     for section in SECTIONS for i, row in enumerate(result["sections"][section])}
    if {row["id"]: row["text"] for row in review["rows"]} != expected_rows:
        raise ValueError(f"Original row judgments differ from {case}/{arm}")

    criteria = v01_criteria(arm, review) if case == "v01" else v02_criteria(arm, review, result)
    review.update(
        reviewer="Codex. Section decisions R1–R3 provided by the user.",
        rubric_version=2,
        source_review_sha256=sha256(lf_bytes(original_review_path)),
        result_sha256=sha256(result_lf),
        gold_sha256=sha256(lf_bytes(gold_path)),
        digest_method="sha256 of UTF-8 file bytes with CRLF normalized to LF",
        criteria=criteria,
        placement_notes=[
            {"rows": refs(COMPLAINTS, 0) if arm == "direct" else refs(COMPLAINTS, 2),
             "classification": "R2_excluded_from_complaints",
             "reason": "По R2 текущее общее ухудшение в жалобы не включается."}
        ] if case == "v02" else [],
        limits="Retrospective scoring of saved outputs. The user decided R1–R3. Codex assessed model outputs.",
    )
    if case == "v02" and arm == "direct":
        review["outside_sections"] = [{
            "criterion": "f3_father_unknown",
            "location": "gaps:0",
            "meaning": "Болезни отца неизвестны.",
        }]
    if case == "v02" and arm == "s":
        review["placement_notes"].append({
            "rows": refs(COMPLAINTS, 0, 1),
            "classification": "historical_phases_in_current_complaints",
            "reason": "Февральская и мартовская фазы относятся к анамнезу заболевания.",
        })
    return review, evaluate(gold, result, review)


def aggregate(metrics):
    summed = ("gold_criteria", "tp", "fp", "fn", "required_placements",
              "complete_required_placements", "present_placements", "allowed_present_placements",
              "unsupported_unique", "output_rows", "duplicate_groups")
    total = {key: sum(m[key] for m in metrics.values()) for key in summed}
    tp, fp, fn = total["tp"], total["fp"], total["fn"]
    total["strict_precision"] = tp / (tp + fp)
    total["recall"] = tp / (tp + fn)
    total["strict_f1"] = 2 * tp / (2 * tp + fp + fn)
    total["wrong_placements"] = [
        {"case": case, "pairs": m["wrong_placements"]}
        for case, m in metrics.items() if m["wrong_placements"]
    ]
    return total


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    verify_source_packet()
    cases = ("v01", "v02")
    arms = ("direct", "s")
    scored = {(case, arm): review_case(case, arm) for case in cases for arm in arms}
    totals = {arm: aggregate({case: scored[case, arm][1] for case in cases}) for arm in arms}
    args.output.mkdir(parents=True, exist_ok=False)
    for (case, arm), (review, metrics) in scored.items():
        save(args.output / case / arm / "review.json", review)
        save(args.output / case / arm / "metrics.json", metrics)
    save(args.output / "aggregate.json", totals)
    print(json.dumps(totals, ensure_ascii=False))


if __name__ == "__main__":
    main()
