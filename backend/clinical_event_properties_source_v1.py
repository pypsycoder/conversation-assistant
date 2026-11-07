"""Base S: the «кто сообщил» field (reported_by) and R1 for short answers over E1-events.

Plan: docs/benchmarks/clinical-base-source-r1-2026-10-26/plan.md.

reported_by is separate from holder: holder is whom the statement is about,
reported_by is who told it («пациент», «жена», «кардиолог»…). The extraction
schema version with the field is used only on the wire. Before the evidence
adapter and the unchanged core, code strips the field and keeps it in a sidecar
by property ID; the core registry never sees it. A revision's new property keeps
its own source, the old one keeps its own. Colliding IDs renamed by E1-repair are
followed through its normalization log.

R1: a model revision made on a short answer (≤ 4 words, e.g. «Да, так.») that
holds none of the new value's words does not retire the old property. The
revision link is removed before the core; the new value is added next to the old
one and the case is logged. Longer answers are not checked.

Printing: when reported_by is not the patient and the row text does not already
name that person, code appends «(со слов: жена)». The text itself is not edited.
"""
import copy
import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator

from backend import clinical_event_properties_e1_events as events
from backend import clinical_event_properties_v1 as core

ROOT = Path(__file__).resolve().parents[1]
PROMPT = ROOT / "backend/prompts/clinical-event-properties-reported-by-v1.txt"
SCHEMA = ROOT / "contracts/clinical-event-properties-evidence-ids-reported-by-v1.schema.json"
VERSION = "clinical-event-properties-source-v1"
STOP = {"не", "нет", "и", "в", "на", "с", "по", "к", "о", "от", "до", "за", "из", "у", "а", "но", "при", "что", "как", "это"}
PATIENT = re.compile(r"^\s*(пациент\w*|patient|сам|сама)\s*$", re.IGNORECASE)


def is_patient(reported_by):
    return reported_by is None or bool(PATIENT.match(reported_by))


def split_reported_by(raw):
    """Validate the wire output and return (raw_without_field, {property_id: reported_by})."""
    Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8"))).validate(raw)
    result = copy.deepcopy(raw)
    found = {}
    for prop in result["properties"]:
        found.setdefault(prop["id"], prop.pop("reported_by").strip())
    return result, found


def _grounds(text):
    return {w[:4] for w in re.findall(r"[^\W_]+", (text or "").casefold()) if w.isdigit() or (len(w) > 2 and w not in STOP)}


def r1_blocks(new_text, answer):
    """A revision on a short answer (≤ 4 words) that holds none of the new value's words."""
    if len(re.findall(r"[^\W_]+", answer or "")) > 4:
        return False
    return not (_grounds(new_text) & _grounds(answer))


def apply_r1(patch, answer):
    """Return (patch_copy, log): revision links blocked by R1 are removed, their properties stay."""
    result = copy.deepcopy(patch)
    by_id = {p["id"]: p for p in result.get("properties", [])}
    kept, log = [], []
    for rev in result.get("revisions", []):
        new = by_id.get(rev["new_property_id"])
        if new is not None and r1_blocks(new["text"], answer):
            log.append({"op": "r1_revision_added_only", "old": rev["old_property_id"], "new": rev["new_property_id"],
                        "why": "short answer holds no word of the new value"})
        else:
            kept.append(rev)
    result["revisions"] = kept
    return result, log


def _answer(source, target_turn_id):
    return next(t["text"] for t in core._turns(source) if t["id"] == target_turn_id)


def apply_patch(registry, sidecar, patch, source, target_turn_id, found=None, r1=True):
    """Apply one window. patch is a materialized core patch (no reported_by); found is the window's sidecar part.

    Returns (applied, new_sidecar). The registry part is exactly E1-events on the (R1-filtered) patch.
    """
    log = []
    if r1:
        patch, log = apply_r1(patch, _answer(source, target_turn_id))
    applied = dict(events.apply_patch(registry, patch, source, target_turn_id))
    applied["r1_log"] = log
    new_sidecar = dict(sidecar)
    if applied["accepted"] and found:
        local = dict(found)
        for entry in applied.get("normalization_log") or []:
            if entry.get("op") == "rename_colliding_property_id" and entry["from"] in found:
                local[entry["to"]] = found[entry["from"]]
        for prop in applied["registry"]["properties"]:
            if prop["id"] not in sidecar and prop["id"] in local:
                new_sidecar[prop["id"]] = local[prop["id"]]
    return applied, new_sidecar


def _stem(word):
    return word[:max(3, len(word) - 1)]


def names_source(text, reported_by):
    """True when the row text already mentions the reporter (by stem)."""
    words = re.findall(r"[^\W_]+", (text or "").casefold())
    return any(w.startswith(_stem(r)) for w in words
               for r in re.findall(r"[^\W_]+", reported_by.casefold()) if r not in STOP)


def mark(text, reported_by):
    if is_patient(reported_by) or names_source(text, reported_by):
        return text, False
    return text.rstrip() + f" (со слов: {reported_by.strip()})", True


def project(registry, sidecar):
    """E1-events projection with «(со слов: …)» appended where needed; sections are rebuilt from rows."""
    projection = events.project(registry)
    marked = []
    for section, rows in projection["evidence"].items():
        for row in rows:
            row["reported_by"] = sidecar.get(row["property_id"])
            row["text"], added = mark(row["text"], row["reported_by"])
            if added:
                marked.append({"section": section, "property_id": row["property_id"], "reported_by": row["reported_by"]})
        projection["sections"][section] = " ".join(row["text"] for row in rows)
    projection["source_marks_added"] = marked
    projection["version"] = VERSION
    return projection
