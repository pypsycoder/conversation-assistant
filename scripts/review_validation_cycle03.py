"""Explicit Codex review of validation outputs, with unchanged cycle-02 scoring."""
import argparse
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.nightly_research import read, save, digest, SECTIONS
from backend.paired_clinical_review import evaluate


def judgment(fid, rows, complete, present=None, status="full", reason="Смысл и обязательные атрибуты сохранены в совокупности указанных строк."):
    return {"id": fid, "status": status, "rows": rows, "complete_sections": complete,
            "present_sections": complete if present is None else present, "reason": reason}


def refs(section, *numbers):
    return [f"{section}:{i}" for i in numbers]


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    C, A, L = SECTIONS
    judgments = {
      ("v01", "direct"): [
        judgment("f1", refs(L, 0), [L]),
        judgment("f2", refs(C, 0)+refs(A, 0), [A], [C,A], reason="Тошнота, утро и 10 дней отражены в обоих разделах; неизвестная причина только в AM. По строгому составному gold C не полон; это не глобальная потеря причины.")],
      ("v01", "s"): [
        judgment("f1", refs(L, 0), [L]),
        judgment("f2", refs(C, 0, 1, 2)+refs(A, 0, 1, 2), [C,A])],
      ("v02", "direct"): [
        judgment("f1", refs(C, 0)+refs(A, 0, 1, 2), [A], [C,A], reason="Хронология полна в AM, год не выдуман. В C только текущее ухудшение: запрещено составным gold, но клинически может быть уместно; требует врачебного решения о рубрике."),
        judgment("f2", refs(L, 0), [L]),
        judgment("f3", refs(L, 1), [], [L], status="partial", reason="В AV есть отсутствие общения с отцом. Неизвестность его болезней сохранена в gaps[0], но не напечатана в трёх разделах; по действующей рубрике критерий частичный, не полностью утраченный во всём JSON.")],
      ("v02", "s"): [
        judgment("f1", refs(C, 0, 1, 2)+refs(A, 0, 1, 2), [C,A], reason="Вся временная последовательность сохранена, год не выдуман. Февраль/март дополнительно напечатаны в жалобах: исторические фазы не являются текущими жалобами."),
        judgment("f2", refs(L, 0), [L]),
        judgment("f3", refs(L, 1, 2), [L])]
    }
    metrics = []
    for (case, arm), criteria in judgments.items():
        result_path = args.run / case / arm / "result.json"
        result = read(result_path)
        gold_path = ROOT / f"examples/nightly-v1/{case}.gold.json"
        rows = [{"id": f"{s}:{i}", "text": r["text"], "support": "supported", "inventions": [],
            "reason": "Прямо поддержано соответствующей исходной репликой; предмет и атрибуты S читаются в связке свойств события."}
             for s in SECTIONS for i, r in enumerate(result["sections"][s])]
        placement_notes = []
        if case == "v02":
            placement_notes.append({"rows": refs(C, 0) if arm == "direct" else refs(C, 2),
                "classification": "rubric_ambiguity", "reason": "Текущее ухудшение в жалобах запрещено gold для составной хронологии, но клиническая ошибочность не установлена."})
            if arm == "s":
                placement_notes.append({"rows": refs(C, 0, 1), "classification": "historical_phases_in_current_complaints",
                    "reason": "Прошлые февральское ухудшение и мартовское улучшение не описывают текущие жалобы."})
        review = {"reviewer": "Codex; rubric and adapter author; not blind; not a physician",
            "result_sha256": digest(result_path), "gold_sha256": digest(gold_path),
            "criteria": criteria, "rows": rows, "inventions": [], "duplicates": [],
            "placement_notes": placement_notes, "source_errors": [], "temporal_errors": [], "polarity_errors": [],
            "outside_sections": [{"criterion": "f3", "location": "gaps:0", "meaning": "Болезни отца неизвестны"}]
                                  if (case, arm) == ("v02", "direct") else [],
            "limits": "Gold is unchanged. Per-section completeness is strict for whole compound criteria; placement notes separate rubric ambiguity from established historical-phase errors."}
        metric = evaluate(read(gold_path), result, review)
        save(args.output / case / arm / "review.json", review)
        save(args.output / case / arm / "metrics.json", metric)
        metrics.append({"case": case, "arm": arm, **metric})
    aggregate = {}
    fields = ("gold_criteria", "tp", "fp", "fn", "unsupported_unique", "unsupported_rows", "required_placements",
        "complete_required_placements", "allowed_present_placements", "present_placements", "output_rows",
        "duplicate_groups", "duplicate_extra_rows")
    for arm in ("direct", "s"):
        items = [m for m in metrics if m["arm"] == arm]
        total = {k: sum(m[k] for m in items) for k in fields}
        tp, fp, fn = (total[k] for k in ("tp", "fp", "fn"))
        total.update(statuses={s: sum(m["statuses"][s] for m in items) for s in ("full","partial","missing","distorted")},
            strict_precision=tp/(tp+fp) if tp+fp else None, recall=tp/(tp+fn), strict_f1=2*tp/(2*tp+fp+fn),
            wrong_placements=[{"case": m["case"], "pairs": m["wrong_placements"]} for m in items if m["wrong_placements"]])
        aggregate[arm] = total
    save(args.output / "aggregate.json", aggregate)
    print(json.dumps(aggregate, ensure_ascii=False))


if __name__ == "__main__":
    main()
