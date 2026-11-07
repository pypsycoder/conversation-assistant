"""E1-repair: deterministic structural repairs around the unchanged sealed reducer.

Builds on E1-fixed (non-episode parent nulled, C->AM at projection). The r1
online run showed that whole windows were still lost to structural slips that
carry no clinical meaning. Repairs here touch only IDs, addresses and kinds;
clinical text, values, polarity, certainty, sections and evidence quotes are
never edited or invented. Every repair is logged.

1. ID collisions: an event that reuses a property ID (or any existing ID) gets a
   fresh ID; event references inside the patch follow it.
2. Episode parents: an episode under another episode moves to that episode's
   state ancestor; an episode without an existing state parent becomes a state.
3. first_event: an episode/background owner moves to the target episode's parent
   state; an impossible reference is demoted to a literal "other" property.
   A literal value of any other kind loses a stray ref_event_id.
4. Revisions: a replacement on another event but the same kind/condition/sections
   is re-addressed to the retired property's event; any other mismatch keeps the
   new property and drops only the revision link.
5. Salvage, only if core still rejects: records citing an earlier unapplied
   patient turn of the window (a rejected window) are applied for that turn
   first; then the largest greedy subset that core accepts for the target.
   Dropped records are listed, not silently lost.

core.apply_patch / core.validate_patch still decide acceptance of every record.
Nothing here certifies clinical truth.
"""
import copy

from backend import clinical_event_properties_v1 as core
from backend import clinical_event_properties_e1_fixed as fixed

VERSION = "clinical-event-properties-e1-repair-v1"
COLLECTIONS = ("events", "properties", "revisions", "unresolved")


def _fresh(base, taken):
    n = 1
    while f"{base}_x{n}" in taken:
        n += 1
    taken.add(f"{base}_x{n}")
    return f"{base}_x{n}"


def _repoint(patch, old, new):
    for event in patch["events"]:
        if event.get("parent_state_id") == old:
            event["parent_state_id"] = new
    for prop in patch["properties"]:
        if prop.get("event_id") == old:
            prop["event_id"] = new
        if isinstance(prop.get("value"), dict) and prop["value"].get("ref_event_id") == old:
            prop["value"]["ref_event_id"] = new


def _repair_ids(registry, patch, log):
    old = {r["id"] for kind in ("events", "properties") for r in registry[kind]}
    old_events = {e["id"]: e for e in registry["events"]}
    kept = []
    for event in patch["events"]:
        prior = old_events.get(event["id"])
        if prior is not None and all(prior[k] == event[k] for k in ("kind", "holder", "label", "parent_state_id")):
            # A verbatim re-declaration of a known event: references keep meaning it.
            log.append({"op": "drop_redeclared_existing_event", "event_id": event["id"]})
            continue
        kept.append(event)
    patch["events"] = kept
    prop_ids = [p["id"] for p in patch["properties"]]
    taken = old | {r["id"] for kind in ("events", "properties") for r in patch[kind]}
    seen = set()
    for event in patch["events"]:
        if event["id"] in old or event["id"] in prop_ids or event["id"] in seen:
            new = _fresh(event["id"], taken)
            log.append({"op": "rename_colliding_event_id", "from": event["id"], "to": new})
            # Event references always mean events, so the rename is unambiguous
            # for the first declaration; later duplicates keep their own copy.
            if event["id"] not in seen:
                _repoint(patch, event["id"], new)
            event["id"] = new
        seen.add(event["id"])
    seen = set()
    for prop in patch["properties"]:
        if prop["id"] in old or prop["id"] in seen:
            new = _fresh(prop["id"], taken)
            log.append({"op": "rename_colliding_property_id", "from": prop["id"], "to": new})
            for rev in patch["revisions"]:
                if rev.get("new_property_id") == prop["id"]:
                    rev["new_property_id"] = new
            prop["id"] = new
        seen.add(prop["id"])


def _repair_episodes(registry, patch, log):
    events = {e["id"]: e for e in registry["events"]}
    events.update({e["id"]: e for e in patch["events"]})
    for event in patch["events"]:
        if event["kind"] != "episode":
            continue
        parent, hops = events.get(event["parent_state_id"]), 0
        while parent is not None and parent["kind"] == "episode" and hops < 10:
            parent, hops = events.get(parent["parent_state_id"]), hops + 1
        if parent is not None and parent["kind"] == "state" and parent["holder"] == event["holder"]:
            if parent["id"] != event["parent_state_id"]:
                log.append({"op": "lift_episode_to_state_ancestor", "event_id": event["id"],
                            "from": event["parent_state_id"], "to": parent["id"]})
                event["parent_state_id"] = parent["id"]
        else:
            log.append({"op": "orphan_episode_to_state", "event_id": event["id"],
                        "dropped_parent_state_id": event["parent_state_id"]})
            event["kind"], event["parent_state_id"] = "state", None


def _repair_first_event(registry, patch, log):
    events = {e["id"]: e for e in registry["events"]}
    events.update({e["id"]: e for e in patch["events"]})
    for prop in patch["properties"]:
        if prop["kind"] != "first_event":
            value = prop.get("value") or {}
            if value.get("type") == "literal" and value.get("ref_event_id") is not None:
                log.append({"op": "literal_value_ref_cleared", "property_id": prop["id"],
                            "dropped_ref_event_id": value["ref_event_id"]})
                value["ref_event_id"] = None
            continue
        value = prop.get("value") or {}
        target = events.get(value.get("ref_event_id"))
        owner = events.get(prop["event_id"])
        if (value.get("type") == "event_ref" and value.get("text") == "" and target is not None
                and target["kind"] == "episode" and target["parent_state_id"] in events
                and events[target["parent_state_id"]]["holder"] == target["holder"]):
            if owner is None or owner["id"] != target["parent_state_id"]:
                log.append({"op": "first_event_owner_to_target_parent", "property_id": prop["id"],
                            "from": prop["event_id"], "to": target["parent_state_id"]})
                prop["event_id"] = target["parent_state_id"]
            continue
        log.append({"op": "first_event_demoted_to_literal_other", "property_id": prop["id"],
                    "dropped_value": copy.deepcopy(value)})
        prop["kind"] = "other"
        prop["value"] = {"type": "literal", "text": prop["text"], "ref_event_id": None}


def _repair_revisions(registry, patch, log):
    active = {p["id"]: p for p in core.active_properties(registry)}
    new_props = {p["id"]: p for p in patch["properties"]}
    kept = []
    for rev in patch["revisions"]:
        old, new = active.get(rev["old_property_id"]), new_props.get(rev["new_property_id"])
        if old is None or new is None:
            kept.append(rev)  # core reports these; salvage may drop them
            continue
        same_slot = old["kind"] == new["kind"] and old["condition"] == new["condition"]
        same_sections = set(old["sections"]) == set(new["sections"])
        if same_slot and same_sections and old["event_id"] != new["event_id"]:
            log.append({"op": "revision_readdressed_to_retired_event", "property_id": new["id"],
                        "from": new["event_id"], "to": old["event_id"]})
            new["event_id"] = old["event_id"]
        elif not (same_slot and same_sections):
            log.append({"op": "revision_link_dropped_address_mismatch", "revision": copy.deepcopy(rev),
                        "kept_new_property_id": new["id"]})
            continue
        kept.append(rev)
    patch["revisions"] = kept


def repair_patch(registry, patch):
    """Return (repaired_copy, log). Inputs are never modified."""
    result, log = fixed.normalize_patch(patch)
    for key in COLLECTIONS:
        result.setdefault(key, [])
    _repair_ids(registry, result, log)
    _repair_episodes(registry, result, log)
    _repair_first_event(registry, result, log)
    _repair_revisions(registry, result, log)
    return result, log


def _items(patch):
    return [(key, row) for key in COLLECTIONS for row in patch[key]]


def _valid(registry, patch, source, target):
    try:
        core.validate_patch(registry, patch, source, target)
        return True
    except Exception:
        return False


def _greedy(registry, items, source, target):
    """Largest prefix-greedy subset that core accepts. Two passes for ordering."""
    chosen = {key: [] for key in COLLECTIONS}
    rest = list(items)
    for _ in range(2):
        left = []
        for key, row in rest:
            trial = {k: v + ([row] if k == key else []) for k, v in chosen.items()}
            if _valid(registry, trial, source, target):
                chosen = trial
            else:
                left.append((key, row))
        rest = left
    return chosen, rest


def _cites(row, turn):
    return any(e["turn_id"] == turn for e in row["evidence"])


def _recovery_turn(registry, rows, source, target):
    """Latest earlier patient turn cited by rows lacking target evidence, if still unapplied."""
    turns = [t for st in source["stages"] for t in st["turns"]]
    order = {t["id"]: i for i, t in enumerate(turns)}
    role = {t["id"]: t["role"] for t in turns}
    last = order[registry["applied_turn_ids"][-1]] if registry["applied_turn_ids"] else -1
    cited = {e["turn_id"] for row in rows for e in row["evidence"]
             if e["turn_id"] in order and role[e["turn_id"]] == "patient"
             and last < order[e["turn_id"]] < order[target]}
    return max(cited, key=order.get) if cited else None


def apply_patch(registry, patch, source, target_turn_id):
    repaired, log = repair_patch(registry, patch)
    applied = dict(core.apply_patch(registry, repaired, source, target_turn_id))
    applied.update(normalization_log=log, normalized_patch=repaired, salvage=None)
    if applied["accepted"]:
        return applied
    first_errors = applied["errors"]
    items = _items(repaired)
    current = registry
    steps = []
    stale = [(k, r) for k, r in items if not _cites(r, target_turn_id)]
    turn = _recovery_turn(registry, [r for _, r in stale], source, target_turn_id) if stale else None
    if turn is not None:
        part, _ = _greedy(current, stale, source, turn)
        if any(part.values()):
            result = core.apply_patch(current, part, source, turn)
            if result["accepted"]:
                current = result["registry"]
                steps.append({"target_turn_id": turn, "recovered_from_unapplied_turn": True,
                              "counts": {k: len(v) for k, v in part.items()}})
                used = {id(r) for v in part.values() for r in v}
                items = [(k, r) for k, r in items if id(r) not in used]
    part, dropped = _greedy(current, items, source, target_turn_id)
    if any(part.values()):
        result = core.apply_patch(current, part, source, target_turn_id)
        if result["accepted"]:
            current = result["registry"]
            steps.append({"target_turn_id": target_turn_id, "recovered_from_unapplied_turn": False,
                          "counts": {k: len(v) for k, v in part.items()}})
    else:
        dropped = items
    if not steps:
        return applied
    salvage = {"first_core_errors": first_errors, "steps": steps,
               "dropped": [{"collection": k, "id": r.get("id") or r.get("new_property_id"),
                            "record": copy.deepcopy(r)} for k, r in dropped]}
    return {"accepted": True, "registry": current, "projection": core.project(current),
            "errors": [], "normalization_log": log, "normalized_patch": repaired, "salvage": salvage,
            "partial": bool(dropped), "semantic_support_certified": False}


def project(registry):
    projection = fixed.project(registry)
    projection["version"] = VERSION
    return projection
