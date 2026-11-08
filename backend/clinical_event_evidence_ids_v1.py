"""Strict ID-only wire evidence to deterministic full-turn core evidence.

The adapter adds only literal source quotes. Selection of a source ID is model
output, not a certification that the selected turn supports a clinical claim.
Availability, current-patient evidence and revision rules remain core guards.
"""
import copy
import json
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "contracts/clinical-event-properties-evidence-ids-v1.schema.json"


def materialize_patch(raw, source, allowed_turn_ids=None):
    """Return a new core patch, with full verbatim turns for selected IDs only.

    Unexpected model quote fields are rejected, not ignored or repaired. No
    decisions, text, values, routing, property links or IDs are normalized.
    """
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(raw)
    turns = [turn for stage in source["stages"] for turn in stage["turns"]]
    if not all(isinstance(turn, dict) and isinstance(turn.get("id"), str)
               and turn["id"].strip() and isinstance(turn.get("text"), str)
               and turn["text"].strip() for turn in turns):
        raise ValueError("Source requires nonblank IDs and original turn texts")
    if len({turn["id"] for turn in turns}) != len(turns):
        raise ValueError("Duplicate source turn IDs")
    by_id = {turn["id"]: turn["text"] for turn in turns}
    selected = [evidence["turn_id"] for collection in ("events", "properties", "revisions", "unresolved")
                for row in raw[collection] for evidence in row["evidence"]]
    if any(sid not in by_id for sid in selected):
        raise ValueError("Unknown evidence source ID")
    if allowed_turn_ids is not None:
        if not isinstance(allowed_turn_ids, (set, frozenset, list, tuple)) or not all(
                isinstance(sid, str) and sid.strip() for sid in allowed_turn_ids):
            raise ValueError("Allowed source IDs must be an explicit collection of nonblank strings")
        allowed = set(allowed_turn_ids)
        if not allowed <= set(by_id):
            raise ValueError("Allowed source IDs include an unknown source turn")
        if not set(selected) <= allowed:
            raise ValueError("Evidence source ID is outside context and registry memory")
    result = copy.deepcopy(raw)
    for collection in ("events", "properties", "revisions", "unresolved"):
        for row in result[collection]:
            for evidence in row["evidence"]:
                sid = evidence["turn_id"]
                evidence["quote"] = by_id[sid]
    return result
