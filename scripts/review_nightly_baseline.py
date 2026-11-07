"""Codex judgments on all 18 rows, not a GigaChat self-score or physician review."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.nightly_research import read, save, score

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "data/nightly/2026-11-08-baseline-direct/iteration-01"
if not RUN.exists():
    RUN = ROOT / "reports/evidence/2026-11-08/baseline/iteration-01"
MAPPINGS = {
    "d01": [["f1"], ["f2"], ["f3"], ["f1"], ["f2"], ["f4"]],
    "d02": [["f4"], ["f1"], ["f2"], ["f3"], ["f4"], []],
    "d03": [["f1"], ["f1"], ["f2"], ["f4"], ["f3"], []],
}
for cid, mapping in MAPPINGS.items():
    review = read(RUN / cid / "review-template.json")
    review["reviewer"] = "Codex; agent author of rubric; not blind; not a physician"
    for i, (row, ids) in enumerate(zip(review["rows"], mapping, strict=True)):
        row["complete_fact_ids"] = ids
        row["reason"] = "Сопоставлено с исходной репликой и полным критерием gold; смысл и атрибуты сохранены."
        if cid == "d01" and i == 1:
            row["reason"] = "Отрицание передано верно, но недопустимо помещено в жалобы; ошибка маршрута, не полярности."
        if cid == "d02" and i == 5:
            row["nonclinical_metadata"] = True
            row["reason"] = "Верная метаинформация о не обсуждавшихся областях; не клинический факт и не отрицание болезней. Место для неё — gaps."
        if cid == "d03" and i == 5:
            row["unsupported_atoms"] = 1
            row["reason"] = "Из упоминания жены модель вывела юридическое семейное положение; отдельного прямого утверждения о браке нет. Строгая рубрика запрещает такой вывод."
    output = ROOT / "data/nightly/recomputed-baseline" / cid
    save(output / "review-codex.json", review)
    gold = read(ROOT / f"examples/nightly-v1/{cid}.gold.json")
    result = read(RUN / cid / "response.json")["parsed"]
    metrics = score(gold, result, review)
    save(output / "metrics.json", metrics)
    print(cid, metrics)
