"""E1-fixed: two code-policy changes around the unchanged sealed reducer.

1. Structural normalization before core.apply_patch: a state/background event
   always has parent_state_id=None. The model often writes a sub-state under its
   parent state; the core rejected the whole patch for this field alone.
   Episodes, holders, labels, links and all clinical text stay untouched.
2. Section routing at projection time only: every active property routed by the
   model to C is also printed in AM (the approved C->AM repetition contract).
   The stored registry and the memory sent to the model keep model-owned sections.

Nothing here certifies clinical truth. core.apply_patch still decides acceptance.
"""
import copy

from backend import clinical_event_properties_v1 as core

VERSION = "clinical-event-properties-e1-fixed-v1"


def normalize_patch(patch):
    """Return (normalized_copy, log). The input patch is never modified."""
    result = copy.deepcopy(patch)
    log = []
    for event in result.get("events", []):
        if event.get("kind") != "episode" and event.get("parent_state_id") is not None:
            log.append({"op": "null_non_episode_parent", "event_id": event.get("id"),
                        "kind": event.get("kind"), "dropped_parent_state_id": event["parent_state_id"]})
            event["parent_state_id"] = None
    return result, log


def apply_patch(registry, patch, source, target_turn_id):
    normalized, log = normalize_patch(patch)
    applied = core.apply_patch(registry, normalized, source, target_turn_id)
    applied = dict(applied)
    applied["normalization_log"] = log
    applied["normalized_patch"] = normalized
    return applied


def routed_registry(registry):
    """Copy with C-routed properties also routed to AM (all versions alike)."""
    result = copy.deepcopy(registry)
    for prop in result["properties"]:
        if "C" in prop["sections"] and "AM" not in prop["sections"]:
            prop["sections"] = list(prop["sections"]) + ["AM"]
    return result


def project(registry):
    projection = core.project(routed_registry(registry))
    projection["routing"] = "code: C implies AM at projection; stored sections are model-owned"
    projection["version"] = VERSION
    return projection
