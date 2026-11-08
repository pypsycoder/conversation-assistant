"""Frozen paired direct-v2 / accepted S comparison on explicit synthetic input."""
import argparse
import copy
import json
import time
from pathlib import Path
from backend.nightly_research import ROOT, SECTIONS, read, save, digest, exclusive_lock
from backend.gigachat import GigaChatClient
from backend import clinical_event_properties_v1 as core
from backend import clinical_event_properties_source_v1 as S
from backend import clinical_event_properties_source_print_v3 as printer
from backend import clinical_event_evidence_ids_v1 as wire
from backend.three_sections import SYSTEM_V2, SCHEMA, provenance_errors


def as_s_source(source):
    if source.get("synthetic") is not True:
        raise ValueError("Explicit synthetic source required")
    turns = [{k: s[k] for k in ("id", "role", "text")} for s in source["segments"]]
    if len({t["id"] for t in turns}) != len(turns):
        raise ValueError("Duplicate source IDs")
    if any(t["role"] not in ("doctor", "patient") for t in turns):
        raise ValueError("Only explicit doctor/patient roles are supported")
    return {"id": source["id"], "version": source["text_revision"], "synthetic": True,
            "stages": [{"id": 1, "title": "", "turns": turns}]}


def windows(source):
    turns = source["stages"][0]["turns"]
    return [{"context_turns": copy.deepcopy(turns[max(0, i-5):i]), "target_turn": copy.deepcopy(t)}
            for i, t in enumerate(turns) if t["role"] == "patient"]


def s_request(window, registry):
    return {"model": "GigaChat-3-Ultra", "temperature": 0.001, "max_tokens": 5000, "stream": False,
        "messages": [{"role": "system", "content": S.PROMPT.read_text(encoding="utf-8").strip()},
                     {"role": "user", "content": json.dumps({**copy.deepcopy(window),
                        "registry": core.memory_view(registry)}, ensure_ascii=False)}],
        "response_format": {"type": "json_schema", "schema": read(S.SCHEMA), "strict": True}}


def allowed_evidence(window, registry):
    memory = core.memory_view(registry)
    ids = {t["id"] for t in [*window["context_turns"], window["target_turn"]]}
    ids.update(e["turn_id"] for kind in ("events", "properties")
               for record in memory[kind] for e in record["evidence"])
    return ids


def apply_s_output(raw, registry, sidecar, source, window):
    stripped, found = S.split_reported_by(raw)
    patch = wire.materialize_patch(stripped, source, allowed_turn_ids=allowed_evidence(window, registry))
    applied, new_sidecar = S.apply_patch(registry, sidecar, patch, source,
                                        window["target_turn"]["id"], found)
    return applied, new_sidecar


def section_rows(projection):
    return {"sections": {s: [{"text": row["text"], "evidence": copy.deepcopy(row["evidence_quotes"]),
              "property_id": row["property_id"], "reported_by": row.get("reported_by")}
             for row in projection["evidence"][s]] for s in SECTIONS},
            "gaps": copy.deepcopy(projection["unresolved"])}


def run(output, live=False):
    corpus = ROOT / "examples/nightly-v1"
    cases = ("d01", "d02", "d03")
    files = [Path(__file__), ROOT / "backend/gigachat.py", ROOT / "backend/three_sections.py",
             ROOT / "backend/nightly_research.py", S.PROMPT, S.SCHEMA,
             ROOT / "contracts/clinical-event-properties-evidence-ids-v1.schema.json",
             ROOT / "contracts/clinical-event-properties-v1.schema.json",
             ROOT / "docs/research/cycle-02-s-vs-direct-plan.md"]
    files += [ROOT / "backend" / (n + ".py") for n in (
        "clinical_event_properties_v1", "clinical_event_properties_source_v1",
        "clinical_event_properties_source_print_v2", "clinical_event_properties_source_print_v3",
        "clinical_event_properties_e1_events", "clinical_event_properties_e1_fixed",
        "clinical_event_properties_e1_repair", "clinical_event_evidence_ids_v1")]
    files += [corpus / (case + suffix) for case in cases for suffix in (".source.json", ".gold.json")]
    hashes = {p.relative_to(ROOT).as_posix(): digest(p) for p in files}
    sources = {case: read(corpus / (case + ".source.json")) for case in cases}
    converted = {case: as_s_source(source) for case, source in sources.items()}
    jobs = [(case, arm) for i, case in enumerate(cases)
            for arm in (("direct", "s") if i % 2 == 0 else ("s", "direct"))]
    with exclusive_lock(ROOT / "data/nightly/research.lock"):
        output.mkdir(parents=True, exist_ok=False)
        save(output / "freeze.json", {"files_sha256": hashes, "cases": list(cases), "jobs": jobs,
             "model": "GigaChat-3-Ultra", "temperature": 0.001, "max_tokens": 5000,
             "max_calls": 15, "max_total_tokens": 300000, "max_seconds": 1200,
             "gold_sent": False, "mode": "live" if live else "offline_smoke"})
        began = time.monotonic()
        calls = tokens = 0
        revision = None
        summary = {"mode": "live" if live else "offline_smoke", "cases": [], "cost_rub": None}
        client = None

        def verify():
            if any(digest(ROOT / p) != sha for p, sha in hashes.items()):
                raise RuntimeError("Frozen input changed")

        def generate(folder, request):
            nonlocal calls, tokens, revision
            verify()
            if len(json.dumps(request, ensure_ascii=False).encode("utf-8")) > 200000:
                raise RuntimeError("Oversized request, no truncation")
            reserve = len(json.dumps(request, ensure_ascii=False).encode("utf-8")) + 5000
            if calls >= 15 or tokens + reserve > 300000 or time.monotonic() - began > 1200:
                raise RuntimeError("Session budget reached")
            save(folder / "attempt.json", {"ordinal": calls+1, "receipt": "pending", "token_reserve": reserve})
            save(folder / "request.json", request)
            calls += 1
            answer = client.generate_structured(request["messages"][0]["content"],
                json.loads(request["messages"][1]["content"]), request["response_format"]["schema"],
                max_tokens=5000, temperature=0.001)
            save(folder / "response.json", answer)
            if answer["request"] != request:
                raise RuntimeError("Actual request differs from frozen builder")
            raw = answer["response"]
            usage = raw.get("usage", {})
            if (type(usage.get("total_tokens")) is not int
                    or usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0) != usage["total_tokens"]):
                raise RuntimeError("Unknown or inconsistent usage")
            tokens += usage["total_tokens"]
            if not raw.get("model") or (revision and revision != raw["model"]):
                raise RuntimeError("Missing or changed model revision")
            revision = raw["model"]
            time.sleep(2)
            return answer

        try:
            if live:
                client = GigaChatClient(use_system_proxy=False)
                summary["provider"] = client.models()
                if client.model != "GigaChat-3-Ultra":
                    raise RuntimeError("Configured model differs from plan")
            for case, arm in jobs:
                verify()
                folder = output / case / arm
                start = time.monotonic()
                if not live:
                    save(folder / "input.json", sources[case] if arm == "direct" else converted[case])
                    summary["cases"].append({"case": case, "arm": arm, "offline_only": True})
                    continue
                first_call, first_tokens = calls, tokens
                errors = []
                api_seconds = 0
                if arm == "direct":
                    request = {"model": "GigaChat-3-Ultra", "temperature": 0.001, "max_tokens": 5000,
                        "stream": False, "messages": [{"role": "system", "content": SYSTEM_V2},
                            {"role": "user", "content": json.dumps({"segments": sources[case]["segments"]}, ensure_ascii=False)}],
                        "response_format": {"type": "json_schema", "schema": SCHEMA, "strict": True}}
                    answer = generate(folder / "completion", request)
                    api_seconds += answer["seconds"]
                    errors = list(answer["validation_errors"])
                    result = answer["parsed"]
                    if result is not None and not errors:
                        errors += provenance_errors(result, sources[case])
                    if result is None or errors:
                        # Retain rejected raw output; delivered result is empty, no best-case selection.
                        result = {"sections": {s: [] for s in SECTIONS}, "gaps": []}
                else:
                    registry, sidecar = core.empty_registry(), {}
                    for window in windows(converted[case]):
                        target = window["target_turn"]["id"]
                        step = folder / target
                        save(step / "registry-before.json", registry)
                        answer = generate(step, s_request(window, registry))
                        api_seconds += answer["seconds"]
                        applied = None
                        step_errors = list(answer["validation_errors"])
                        if not step_errors and answer["parsed"] is not None:
                            try:
                                applied, updated = apply_s_output(answer["parsed"], registry, sidecar, converted[case], window)
                                if applied["accepted"]:
                                    registry, sidecar = applied["registry"], updated
                                else:
                                    step_errors += applied["errors"]
                            except (ValueError, KeyError, TypeError) as exc:
                                step_errors.append({"type": type(exc).__name__, "reason": str(exc)})
                        save(step / "application.json", {"errors": step_errors, "applied": applied})
                        if step_errors:
                            errors.append({"target": target, "errors": step_errors})
                    projection = printer.project(registry, sidecar)
                    save(folder / "registry.json", registry)
                    save(folder / "sidecar.json", sidecar)
                    save(folder / "projection.json", projection)
                    result = section_rows(projection)
                save(folder / "result.json", result)
                save(folder / "technical-errors.json", errors)
                item = {"case": case, "arm": arm, "calls": calls-first_call, "tokens": tokens-first_tokens,
                    "api_seconds": api_seconds, "seconds": time.monotonic()-start,
                    "technical_errors": len(errors), "rows": {s: len(result["sections"][s]) for s in SECTIONS}}
                summary["cases"].append(item)
                print(json.dumps(item, ensure_ascii=False), flush=True)
            verify()
            summary["status"] = "awaiting_review" if live else "offline_smoke_only"
        except Exception as exc:
            summary["status"], summary["error_type"] = "stopped", type(exc).__name__
            # Transport exception strings never serialized. Pending receipt is not retried.
        finally:
            summary.update(calls=calls, tokens=tokens, seconds=time.monotonic()-began, returned_model=revision)
            save(output / "summary.json", summary)
        print(json.dumps(summary, ensure_ascii=False), flush=True)
        return 1 if summary["status"] == "stopped" else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    raise SystemExit(run(args.output, args.live))
