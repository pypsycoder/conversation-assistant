"""Bounded synthetic-only runner; semantic scores require separate adjudication."""
import argparse
import hashlib
import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECTIONS = ("complaints", "illness_history", "life_history")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@contextmanager
def exclusive_lock(path):
    """OS lock is released even after process death; do not delete the inode."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        stream.seek(0, 2)
        if not stream.tell():
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def score(gold, result, review):
    """One judgment per output row, many atomic gold facts may match one row.

    A complete match asserts preservation of meaning including attributes. IDs
    are assigned by an external reviewer, never by the model under evaluation.
    Unsupported atomic assertions must be counted even inside otherwise valid rows.
    """
    expected = {f["id"]: f for f in gold["facts"]}
    rows = {f"{section}:{i}": (section, row)
            for section in SECTIONS for i, row in enumerate(result["sections"][section])}
    judgments = review["rows"]
    if len({j["row_id"] for j in judgments}) != len(judgments):
        raise ValueError("Duplicate reviewed row")
    if {j["row_id"] for j in judgments} != set(rows):
        raise ValueError("Every output row must be reviewed exactly once")
    matched, placements, unique_predictions = set(), set(), set()
    unsupported = duplicates = polarity = temporal = source = 0
    for j in judgments:
        ids = j["complete_fact_ids"]
        if len(set(ids)) != len(ids) or not set(ids) <= set(expected):
            raise ValueError("Invalid gold mapping")
        metadata = j.get("nonclinical_metadata", False)
        if metadata and (ids or j.get("partial_fact_ids") or j["unsupported_atoms"]):
            raise ValueError("Metadata cannot also be a clinical assertion")
        if not ids and j["unsupported_atoms"] < 1 and not j.get("partial_fact_ids") and not metadata:
            raise ValueError("Unmatched output needs an unsupported or partial judgment")
        for key in ("unsupported_atoms", "polarity_errors", "temporal_errors", "source_errors"):
            if type(j[key]) is not int or j[key] < 0:
                raise ValueError("Counts must be nonnegative integers")
        section = rows[j["row_id"]][0]
        for fid in ids:
            pair = (fid, section)
            duplicates += pair in placements
            placements.add(pair)
            matched.add(fid)
            unique_predictions.add(fid)
        partial = j.get("partial_fact_ids", [])
        if not set(partial) <= set(expected) or set(partial) & set(ids):
            raise ValueError("Invalid partial mapping")
        unique_predictions.update(partial)
        unsupported += j["unsupported_atoms"]
        polarity += j["polarity_errors"]
        temporal += j["temporal_errors"]
        source += j["source_errors"]
    tp, fn = len(matched), len(expected) - len(matched)
    fp = len(unique_predictions - matched) + unsupported
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / len(expected) if expected else None
    f1 = 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None
    required = {(fid, section) for fid, fact in expected.items() for section in fact["required_sections"]}
    allowed = {(fid, section) for fid, fact in expected.items() for section in fact.get("allowed_sections", fact["required_sections"])}
    return {"gold_facts": len(expected), "output_rows": len(rows), "tp": tp, "fp": fp, "fn": fn,
            "precision": precision, "recall": recall, "f1": f1,
            "required_placements": len(required), "covered_placements": len(placements & required),
            "correct_placements": len(placements & allowed), "predicted_placements": len(placements),
            "unsupported_atoms": unsupported, "duplicate_placements": duplicates,
            "polarity_errors": polarity, "temporal_errors": temporal, "source_errors": source,
            "reviewer": review["reviewer"], "physician_reviewed": review.get("physician_reviewed", False)}


def run(args):
    from backend.gigachat import GigaChatClient
    from backend.three_sections import SCHEMA, SYSTEM_V2, provenance_errors, link_sources
    if not 1 <= args.iterations <= 10:
        raise ValueError("iterations must be 1..10")
    corpus = args.corpus.resolve()
    manifest = read(corpus / "manifest.json")
    if manifest.get("synthetic") is not True:
        raise ValueError("Only explicitly synthetic corpora are permitted")
    cases = [c for c in manifest["cases"] if c["split"] == args.split]
    if not cases or args.split == "final":
        raise ValueError("Final set is reserved for a separate frozen evaluation")
    prompt = args.prompt.read_text(encoding="utf-8") if args.prompt else SYSTEM_V2
    tracked = [Path(__file__), ROOT / "backend/gigachat.py", ROOT / "backend/three_sections.py",
               corpus / "manifest.json"]
    if args.prompt:
        tracked.append(args.prompt)
    for case in cases:
        tracked += [corpus / case["source"], corpus / case["gold"]]
    hashes = {str(p.resolve()): digest(p) for p in tracked}
    with exclusive_lock(ROOT / "data/nightly/research.lock"):
        args.output.mkdir(parents=True, exist_ok=False)
        save(args.output / "freeze.json", {"files": hashes, "system_prompt": prompt,
             "split": args.split, "case_ids": [c["id"] for c in cases],
             "iterations": args.iterations, "max_calls": args.max_calls,
             "max_tokens": args.max_tokens, "max_seconds": args.max_seconds,
             "created_at": datetime.now(timezone.utc).isoformat()})
        began = time.monotonic()
        calls = tokens = 0
        model_revision = None
        summary = {"status": "running", "calls": 0, "tokens": 0,
                   "semantic_metrics": None, "cost_rub": None, "cost_note": "Tariff not configured",
                   "experiment": "direct-v2 reference; not the accepted incremental S baseline", "cases": []}
        def verify():
            if any(digest(Path(p)) != h for p, h in hashes.items()):
                raise RuntimeError("Frozen input changed")
        try:
            client = None
            if args.live:
                client = GigaChatClient(use_system_proxy=not args.direct)
                summary["provider"] = client.models()
            for iteration in range(1, args.iterations + 1):
                for case in cases:
                    verify()
                    if (calls >= args.max_calls or tokens >= args.max_tokens
                            or time.monotonic() - began >= args.max_seconds):
                        raise RuntimeError("Session budget reached")
                    # Reserve conservative token ceiling before dispatch. Timeout remains 120s.
                    source = read(corpus / case["source"])
                    data = {"segments": source["segments"]}
                    reserve = len(json.dumps(data, ensure_ascii=False).encode("utf-8")) + len(prompt.encode("utf-8")) + 3000
                    if tokens + reserve > args.max_tokens:
                        raise RuntimeError("Insufficient token reserve")
                    folder = args.output / f"iteration-{iteration:02}" / case["id"]
                    save(folder / "attempt.json", {"receipt": "pending" if args.live else "offline",
                         "source_sha256": digest(corpus / case["source"])})
                    if not args.live:
                        summary["cases"].append({"id": case["id"], "offline": True})
                        continue
                    calls += 1
                    answer = client.generate_structured(prompt, data, SCHEMA, max_tokens=3000)
                    save(folder / "response.json", answer)
                    usage = answer["response"].get("usage", {})
                    if type(usage.get("total_tokens")) is not int:
                        raise RuntimeError("Missing usage; stop before further spending")
                    tokens += usage["total_tokens"]
                    revision = answer["response"].get("model")
                    if not revision or (model_revision and revision != model_revision):
                        raise RuntimeError("Missing or changed model revision")
                    model_revision = revision
                    if answer["validation_errors"] or answer["parsed"] is None:
                        raise RuntimeError("Invalid completion; no automatic retry")
                    errors = provenance_errors(answer["parsed"], source)
                    save(folder / "provenance-errors.json", errors)
                    if errors:
                        raise RuntimeError("Invalid evidence; no automatic repair")
                    save(folder / "linked-result.json", link_sources(answer["parsed"], source))
                    template = {"reviewer": "TODO", "physician_reviewed": False,
                                "response_sha256": digest(folder / "response.json"),
                                "gold_sha256": digest(corpus / case["gold"]), "rows": []}
                    for section in SECTIONS:
                        for i, row in enumerate(answer["parsed"]["sections"][section]):
                            template["rows"].append({"row_id": f"{section}:{i}", "text": row["text"],
                                "complete_fact_ids": [], "partial_fact_ids": [], "unsupported_atoms": 0,
                                "polarity_errors": 0, "temporal_errors": 0, "source_errors": 0, "reason": "TODO"})
                    save(folder / "review-template.json", template)
                    summary["cases"].append({"id": case["id"], "iteration": iteration,
                         "seconds": answer["seconds"], "usage": usage, "model": revision})
                    time.sleep(2)
            verify()
            summary["status"] = "awaiting_independent_review" if args.live else "offline_smoke_only"
        except Exception as error:
            summary["status"] = "stopped"
            # Never serialize a provider exception: it could contain sensitive headers.
            summary["error_type"] = type(error).__name__
            summary["receipt_note"] = "Inspect attempt/response pairs; never retry a pending receipt automatically"
        finally:
            summary.update(calls=calls, tokens=tokens, seconds=time.monotonic() - began)
            save(args.output / "summary.json", summary)
        print(json.dumps(summary, ensure_ascii=False))
        return 1 if summary["status"] == "stopped" else 0


def main():
    parser = argparse.ArgumentParser(__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    runner = sub.add_parser("run")
    runner.add_argument("--corpus", type=Path, default=ROOT / "examples/nightly-v1")
    runner.add_argument("--output", type=Path, required=True)
    runner.add_argument("--split", choices=["diagnostic", "validation", "final"], default="diagnostic")
    runner.add_argument("--iterations", type=int, default=1)
    runner.add_argument("--max-calls", type=int, default=6)
    runner.add_argument("--max-tokens", type=int, default=100000)
    runner.add_argument("--max-seconds", type=int, default=900)
    runner.add_argument("--prompt", type=Path)
    runner.add_argument("--live", action="store_true")
    runner.add_argument("--direct", action="store_true")
    evaluate = sub.add_parser("score")
    for name in ("gold", "response", "review", "output"):
        evaluate.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    if args.command == "run":
        return run(args)
    review = read(args.review)
    if review["reviewer"] == "TODO" or any(j.get("reason") == "TODO" for j in review["rows"]):
        raise ValueError("Review is incomplete")
    if review["response_sha256"] != digest(args.response) or review["gold_sha256"] != digest(args.gold):
        raise ValueError("Review does not match frozen response/gold")
    metrics = score(read(args.gold), read(args.response)["parsed"], review)
    save(args.output, metrics)
    print(json.dumps(metrics, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
