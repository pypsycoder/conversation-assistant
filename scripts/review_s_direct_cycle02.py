"""Codex's explicit semantic judgments, criterion unions + exhaustive row review."""
import argparse
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.nightly_research import read, save, digest, SECTIONS
from backend.paired_clinical_review import evaluate


def criterion(fid, refs, complete, present=None, reason="Смысл и обязательные атрибуты переданы совокупностью указанных строк."):
    return {"id": fid, "status": "full", "rows": refs, "complete_sections": complete,
            "present_sections": present if present is not None else complete, "reason": reason}


def refs(section, *indices):
    return [f"{section}:{i}" for i in indices]


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    C, A, L = SECTIONS
    judgments = {
      ("d01", "direct"): [
        criterion("f1", refs(C, 0), [C], reason="Засыпание через два часа передано в жалобах; в анамнезе болезни этого содержания нет."),
        criterion("f2", refs(A, 1), [A]), criterion("f3", refs(A, 0), [A]), criterion("f4", refs(L, 0), [L])],
      ("d01", "s"): [
        criterion("f1", refs(C, 0, 1)+refs(A, 0, 1), [C,A]),
        criterion("f2", refs(C, 2)+refs(A, 2), [C,A], reason="Отрицание верно, но в complaints размещено вопреки рубрике."),
        criterion("f3", refs(C, 3, 4)+refs(A, 3, 4), [C,A], reason="Уточнённые дата и длительность сохранены, старые три недели сняты."),
        criterion("f4", refs(L, 0, 1), [L])],
      ("d02", "direct"): [
        criterion("f1", refs(A, 0), [A]), criterion("f2", refs(A, 1), [A]), criterion("f3", refs(A, 2), [A]),
        criterion("f4", refs(C, 0, 1), [C], reason="Тревога каждый вечер передана в жалобах, но отсутствует в анамнезе болезни.")],
      ("d02", "s"): [
        criterion("f1", refs(A, 0, 1, 2, 3, 4), [A], reason="Курс, доза, режим, год и отсутствие эффекта распределены по свойствам одного события; учитываются вместе."),
        criterion("f2", refs(A, 5, 6, 7, 8, 9, 10), [A]), criterion("f3", refs(A, 11), [A]),
        criterion("f4", refs(C, 0, 1, 2, 3, 4)+refs(A, 12, 13, 14, 15, 16), [C,A])],
      ("d03", "direct"): [
        criterion("f1", refs(C, 0)+refs(A, 0), [C,A]), criterion("f2", refs(A, 1), [A]),
        criterion("f3", refs(L, 0), [L]), criterion("f4", refs(C, 1)+refs(A, 2), [C,A])],
      ("d03", "s"): [
        criterion("f1", refs(C, 0, 1)+refs(A, 0, 1), [C,A]), criterion("f2", refs(A, 2), [A]),
        criterion("f3", refs(L, 0, 1), [L]), criterion("f4", refs(C, 2, 3)+refs(A, 3, 4), [C,A],
          reason="Наблюдение жены и собственная неуверенность пациента сохранены отдельными связанными свойствами.")]
    }
    all_metrics = []
    for (case, arm), criteria in judgments.items():
        path = args.run / case / arm / "result.json"
        result = read(path)
        gold_path = ROOT / f"examples/nightly-v1/{case}.gold.json"
        row_reviews = [{"id": f"{s}:{i}", "text": r["text"], "support": "supported", "inventions": [],
            "reason": "Явно подтверждено исходной репликой; для свойств S учитывается связь с событием и соседними свойствами."}
             for s in SECTIONS for i, r in enumerate(result["sections"][s])]
        inventions, duplicates = [], []
        if (case, arm) == ("d02", "direct"):
            row = next(r for r in row_reviews if r["id"] == "life_history:0")
            row.update(support="metadata", reason="Возраст действительно не указан; это метаинформация, не придуманное значение возраста.")
            duplicates = [{"rows": refs(C, 0, 1), "reason": "Вечерняя тревога повторена в одном разделе; вторая строка добавляет метаоговорку, но не второй симптом."}]
        if (case, arm) == ("d03", "direct"):
            row = next(r for r in row_reviews if r["id"] == "life_history:1")
            row.update(support="unsupported", inventions=["marital_status"],
                reason="Упоминание жены не является прямым сообщением юридического семейного положения; строгая общая рубрика запрещает такой вывод.")
            inventions = [{"id": "marital_status", "text": "Женат.", "reason": row["reason"]}]
        if (case, arm) == ("d02", "s"):
            duplicates = [{"rows": refs(C, 1, 2), "reason": "Две отдельные строки одинаково сообщают частоту каждый вечер."},
                          {"rows": refs(A, 13, 14), "reason": "Та же частота дважды в анамнезе болезни."}]
        review = {"reviewer": "Codex; rubric and adapter author; not blind; not a physician",
            "result_sha256": digest(path), "gold_sha256": digest(gold_path),
            "criteria": criteria, "rows": row_reviews, "inventions": inventions, "duplicates": duplicates,
            "source_errors": [], "temporal_errors": [], "polarity_errors": [],
            "limits": "Only three sections; gaps/unresolved are not independently gold-scored."}
        metrics = evaluate(read(gold_path), result, review)
        save(args.output / case / arm / "review.json", review)
        save(args.output / case / arm / "metrics.json", metrics)
        all_metrics.append({"case": case, "arm": arm, **metrics})
    aggregate = {}
    for arm in ("direct", "s"):
        items = [m for m in all_metrics if m["arm"] == arm]
        fields = ("gold_criteria", "tp", "fp", "fn", "unsupported_unique", "unsupported_rows", "required_placements",
            "complete_required_placements", "allowed_present_placements", "present_placements", "output_rows",
            "duplicate_groups", "duplicate_extra_rows")
        total = {k: sum(m[k] for m in items) for k in fields}
        tp, fp, fn = (total[k] for k in ("tp", "fp", "fn"))
        total.update(strict_precision=tp/(tp+fp), recall=tp/(tp+fn), strict_f1=2*tp/(2*tp+fp+fn),
                     wrong_placements=[{"case": m["case"], "pairs": m["wrong_placements"]}
                                       for m in items if m["wrong_placements"]])
        aggregate[arm] = total
    save(args.output / "aggregate.json", aggregate)
    print(__import__("json").dumps(aggregate, ensure_ascii=False))


if __name__ == "__main__":
    main()
