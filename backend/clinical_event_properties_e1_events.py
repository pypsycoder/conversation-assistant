"""E1-events: code creates events that the model referenced but never declared.

Each window extracts one patient answer. When a property points to an event ID
that is neither in the patch nor in the registry, the model still told us what
the property is about; only the container is missing. Instead of rejecting the
whole window (E1-repair r1-r3, E1-compact, E1-dedup lost sleep, alcohol, age and
medication this way), code declares that event:

  id      the ID the model used
  holder  "patient"
  kind    "background" if every property on it is routed only to AV, else "state"
  parent  null
  label   text of the first property on it
  evidence  union of those properties' evidence, in order

Property text, values, sections and evidence are never edited. Every created
event is logged. Then E1-repair repairs, salvage and the unchanged reducer run
as before. first_event references (value.ref_event_id) are not used to create
events.
"""
import copy

from backend import clinical_event_properties_e1_repair as repair

VERSION = "clinical-event-properties-e1-events-v1"
project = repair.project


def declare_missing_events(registry, patch):
    """Return (patched_copy, log). Inputs are never modified."""
    result = copy.deepcopy(patch)
    known = {e["id"] for e in registry["events"]} | {e["id"] for e in result.get("events", [])}
    owners = {}
    for prop in result.get("properties", []):
        if prop.get("event_id") not in known:
            owners.setdefault(prop["event_id"], []).append(prop)
    log = []
    for event_id, props in owners.items():
        evidence = []
        for prop in props:
            for item in prop["evidence"]:
                if item not in evidence:
                    evidence.append(copy.deepcopy(item))
        kind = "background" if all(set(p["sections"]) == {"AV"} for p in props) else "state"
        result.setdefault("events", []).append({"id": event_id, "kind": kind, "holder": "patient",
            "label": props[0]["text"], "episode": "unmarked", "parent_state_id": None, "evidence": evidence})
        log.append({"op": "code_declared_missing_event", "event_id": event_id, "kind": kind,
                    "property_ids": [p["id"] for p in props]})
    return result, log


def apply_patch(registry, patch, source, target_turn_id):
    declared, log = declare_missing_events(registry, patch)
    applied = dict(repair.apply_patch(registry, declared, source, target_turn_id))
    applied["normalization_log"] = log + list(applied.get("normalization_log") or [])
    return applied
