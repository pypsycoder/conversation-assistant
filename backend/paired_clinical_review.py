"""Score explicit criterion-level and per-row judgments, never infer semantic matches."""
from backend.nightly_research import SECTIONS


def evaluate(gold, result, review):
    facts = {f["id"]: f for f in gold["facts"]}
    rows = {f"{s}:{i}" for s in SECTIONS for i, _ in enumerate(result["sections"][s])}
    judgments = review["criteria"]
    if len({j["id"] for j in judgments}) != len(judgments) or {j["id"] for j in judgments} != set(facts):
        raise ValueError("Every criterion must be judged once")
    row_reviews = review["rows"]
    if len({j["id"] for j in row_reviews}) != len(row_reviews) or {j["id"] for j in row_reviews} != rows:
        raise ValueError("Every output row must be reviewed once")
    invention_ids = {j["id"] for j in review["inventions"]}
    if len(invention_ids) != len(review["inventions"]):
        raise ValueError("Duplicate invention ID")
    referenced = set()
    for j in row_reviews:
        if j["support"] not in ("supported", "mixed", "unsupported", "metadata") or not j["reason"].strip():
            raise ValueError("Invalid row judgment")
        if not set(j["inventions"]) <= invention_ids:
            raise ValueError("Unknown invented claim")
        if j["support"] in ("unsupported", "mixed") and not j["inventions"]:
            raise ValueError("Unsupported rows require a specific invented claim")
        referenced.update(j["inventions"])
    if referenced != invention_ids:
        raise ValueError("Every invention must refer to output rows")
    for group in review.get("duplicates", []):
        if len(set(group["rows"])) < 2 or not set(group["rows"]) <= rows:
            raise ValueError("Duplicate groups need existing output rows")
        if len({r.split(":")[0] for r in group["rows"]}) != 1:
            raise ValueError("Cross-section repetition is not an intra-section duplicate")
    counts = {s: 0 for s in ("full", "partial", "missing", "distorted")}
    covered, predicted = set(), set()
    for j in judgments:
        if j["status"] not in counts or not j["reason"].strip() or not set(j["rows"]) <= rows:
            raise ValueError("Invalid criterion judgment")
        if not set(j["complete_sections"]) <= set(j["present_sections"]) <= set(SECTIONS):
            raise ValueError("Invalid section judgment")
        if j["status"] != "missing" and not j["rows"]:
            raise ValueError("Nonmissing criterion needs referenced output")
        counts[j["status"]] += 1
        covered.update((j["id"], s) for s in j["complete_sections"])
        predicted.update((j["id"], s) for s in j["present_sections"])
    required = {(fid, s) for fid, f in facts.items() for s in f["required_sections"]}
    allowed = {(fid, s) for fid, f in facts.items() for s in f.get("allowed_sections", f["required_sections"])}
    tp, fn = counts["full"], len(facts)-counts["full"]
    fp = counts["partial"] + counts["distorted"] + len(invention_ids)
    return {"gold_criteria": len(facts), "statuses": counts, "tp": tp, "fp": fp, "fn": fn,
            "strict_precision": tp/(tp+fp) if tp+fp else None, "recall": tp/len(facts) if facts else None,
            "strict_f1": 2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None,
            "unsupported_unique": len(invention_ids), "unsupported_rows": sum(bool(j["inventions"]) for j in row_reviews),
            "required_placements": len(required), "complete_required_placements": len(covered & required),
            "allowed_present_placements": len(predicted & allowed), "present_placements": len(predicted),
            "wrong_placements": sorted([list(p) for p in predicted-allowed]), "output_rows": len(rows),
            "duplicate_groups": len(review.get("duplicates", [])),
            "duplicate_extra_rows": sum(len(set(g["rows"]))-1 for g in review.get("duplicates", [])),
            "reviewer": review["reviewer"], "physician_reviewed": False}
