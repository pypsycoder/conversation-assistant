"""Immutable events, versioned properties and ID-addressed late corrections.

Model text and evidence remain model-owned. The reducer certifies only schema,
literal provenance, available memory and update addresses, never clinical truth.
One property version owns its text in every requested output section.
"""
import copy
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "contracts/clinical-event-properties-v1.schema.json"
SECTION_MAP = {"C": "complaints", "AV": "life_history", "AM": "illness_history"}
PROPERTY_KINDS = ("presence", "onset", "presence_by", "first_noticed", "worsening_onset",
    "occurrence_time", "duration", "frequency", "quantity", "severity", "within_day",
    "context", "place", "course", "functioning", "capability", "background", "belief",
    "knowledge", "result", "first_event", "other")


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def empty_registry():
    return {"events": [], "properties": [], "revisions": [], "unresolved": [], "applied_turn_ids": [],
            "source_id": None, "source_sha256": None}


def _schema():
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _registry_schema():
    schema = _schema()
    schema["properties"]["applied_turn_ids"] = {"type": "array", "items": {"type": "string", "minLength": 1}, "uniqueItems": True}
    for name in ("source_id", "source_sha256"):
        schema["properties"][name] = {"type": ["string", "null"]}
    schema["required"].extend(("applied_turn_ids", "source_id", "source_sha256"))
    return schema


def _turns(source):
    turns = [turn for stage in source["stages"] for turn in stage["turns"]]
    _require(all(isinstance(t, dict) and isinstance(t.get("id"), str) and t["id"].strip()
        and t.get("role") in ("doctor", "patient") and isinstance(t.get("text"), str)
        and t["text"].strip() for t in turns), "Source needs nonblank doctor/patient turns")
    _require(len({t["id"] for t in turns}) == len(turns), "Source turn IDs must be unique")
    return turns


def _records(registry):
    return [row for collection in ("events", "properties", "revisions", "unresolved") for row in registry[collection]]


def _literal_evidence(rows, by_source):
    for row in rows:
        _require(row["evidence"], "Evidence is required")
        seen = set()
        for evidence in row["evidence"]:
            sid, quote = evidence["turn_id"], evidence["quote"]
            _require(sid in by_source and quote.strip() and quote in by_source[sid]["text"], "Evidence must be a literal known source quote")
            _require((sid, quote) not in seen, "Duplicate evidence quote")
            seen.add((sid, quote))


def _check_links(registry):
    events = {e["id"]: e for e in registry["events"]}
    props = {p["id"]: p for p in registry["properties"]}
    ids = [e["id"] for e in registry["events"]] + [p["id"] for p in registry["properties"]]
    _require(len(ids) == len(set(ids)), "Event/property IDs must be globally unique across history")
    for event in events.values():
        for key in ("id", "holder", "label", "episode"):
            _require(event[key].strip(), "Blank event field")
        if event["kind"] == "episode":
            parent = events.get(event["parent_state_id"])
            _require(parent is not None and parent["kind"] == "state", "Episode needs an existing parent state")
            _require(parent["holder"] == event["holder"], "Episode holder differs from parent state")
        else:
            _require(event["parent_state_id"] is None, "State/background parent must be null")
    for prop in props.values():
        _require(prop["event_id"] in events, "Property event does not exist")
        _require(prop["id"].strip() and prop["condition"].strip() and prop["text"].strip(), "Blank property field")
        value = prop["value"]
        if prop["kind"] == "first_event":
            target = events.get(value["ref_event_id"])
            owner = events[prop["event_id"]]
            _require(value["type"] == "event_ref" and value["text"] == "", "first_event requires an event reference, not cached date text")
            _require(owner["kind"] == "state" and target is not None and target["kind"] == "episode",
                     "first_event must select an episode of a state")
            _require(target["parent_state_id"] == owner["id"] and target["holder"] == owner["holder"],
                     "first_event reference changes holder or parent state")
        else:
            _require(value["type"] == "literal" and value["ref_event_id"] is None and value["text"].strip(),
                     "Non-reference property requires a nonblank literal value")
    old_ids = [r["old_property_id"] for r in registry["revisions"]]
    _require(len(old_ids) == len(set(old_ids)), "A property may be retired once; address its active successor")
    graph = {}
    for rev in registry["revisions"]:
        old, new = props.get(rev["old_property_id"]), props.get(rev["new_property_id"])
        _require(old is not None and new is not None and old["id"] != new["id"], "Revision endpoints must be distinct existing properties")
        _require(all(old[k] == new[k] for k in ("event_id", "kind", "condition")), "Revision cannot change event, kind or condition")
        _require(set(old["sections"]) == set(new["sections"]), "Value revision cannot change section routing")
        graph[old["id"]] = new["id"]
    for start in graph:
        node, seen = start, set()
        while node in graph:
            _require(node not in seen, "Revision graph must be acyclic")
            seen.add(node)
            node = graph[node]
    return events, props


def _validate_registry(registry, source=None):
    Draft202012Validator(_registry_schema()).validate(registry)
    _check_links(registry)
    if source is not None:
        _require(isinstance(source.get("id"), str) and source["id"].strip(), "Source ID is required")
        if registry["source_id"] is not None:
            _require(registry["source_id"] == source["id"] and registry["source_sha256"] == digest(source),
                     "Registry source identity or immutable source hash changed")
        turns = _turns(source)
        by_source = {t["id"]: t for t in turns}
        order = {t["id"]: i for i, t in enumerate(turns)}
        _literal_evidence(_records(registry), by_source)
        applied = registry["applied_turn_ids"]
        _require(all(sid in by_source and by_source[sid]["role"] == "patient" for sid in applied), "Applied targets must be existing patient turns")
        _require([order[sid] for sid in applied] == sorted(order[sid] for sid in applied), "Applied turns must be chronological")
        _require(not _records(registry) or applied, "Nonempty registry needs applied-turn provenance")
        _require(not applied or registry["source_id"] is not None, "Nonempty registry needs immutable source binding")
        if applied:
            _require(all(order[e["turn_id"]] <= order[applied[-1]] for r in _records(registry) for e in r["evidence"]),
                     "Registry contains evidence after its last applied target")


def active_properties(registry):
    retired = {r["old_property_id"] for r in registry["revisions"]}
    return [copy.deepcopy(p) for p in registry["properties"] if p["id"] not in retired]


def _issues(registry):
    slots = defaultdict(list)
    for prop in active_properties(registry):
        slots[(prop["event_id"], prop["kind"], prop["condition"])].append(prop)
    result = []
    for (event, kind, condition), props in slots.items():
        if len(props) > 1:
            identical = len({digest({k: p[k] for k in ("value", "certainty", "approximate", "polarity")}) for p in props}) == 1
            result.append({"kind": "duplicate_active_slot" if identical else "conflicting_active_slot",
                "event_id": event, "property_kind": kind, "condition": condition,
                "property_ids": [p["id"] for p in props], "auto_resolved": False,
                "reason": "Several active values share an addressed slot; an explicit revision is required. No semantic deduplication or last-write-wins."})
    return result


def memory_view(registry):
    """Only immutable events and active properties/evidence, never old paragraphs."""
    _validate_registry(registry)
    return {"events": copy.deepcopy(registry["events"]), "properties": active_properties(registry),
            "issues": _issues(registry)}


def validate_patch(registry, patch, source, target_turn_id):
    _validate_registry(registry, source)
    Draft202012Validator(_schema()).validate(patch)
    turns = _turns(source)
    by_source = {t["id"]: t for t in turns}
    order = {t["id"]: i for i, t in enumerate(turns)}
    _require(target_turn_id in by_source and by_source[target_turn_id]["role"] == "patient", "Target must be a patient turn")
    if registry["applied_turn_ids"]:
        _require(order[target_turn_id] > order[registry["applied_turn_ids"][-1]], "Target must follow all accepted registry turns")
    index = order[target_turn_id]
    visible_ids = {t["id"] for t in turns[max(0, index - 5):index + 1]}
    memory = memory_view(registry)
    known_quotes = {(e["turn_id"], e["quote"]) for kind in ("events", "properties")
                    for row in memory[kind] for e in row["evidence"]}
    records = _records({**patch, "applied_turn_ids": []})
    _literal_evidence(records, by_source)
    for record in records:
        _require(any(e["turn_id"] == target_turn_id for e in record["evidence"]), "Every new event/property/revision/unresolved needs current patient evidence")
        for evidence in record["evidence"]:
            sid, quote = evidence["turn_id"], evidence["quote"]
            _require(order[sid] <= index, "Future evidence is forbidden")
            _require(sid in visible_ids or (sid, quote) in known_quotes, "Past evidence is unavailable outside context5 and exact active-memory quotes")
    for row in patch["unresolved"]:
        _require(row["text"].strip() and row["reason"].strip(), "Unresolved text and reason must be nonblank")
    old_ids = {r["id"] for kind in ("events", "properties") for r in registry[kind]}
    new_ids = [r["id"] for kind in ("events", "properties") for r in patch[kind]]
    _require(len(new_ids) == len(set(new_ids)) and not old_ids.intersection(new_ids), "New IDs collide with immutable history or each other")
    active = {p["id"] for p in active_properties(registry)}
    added = {p["id"] for p in patch["properties"]}
    for revision in patch["revisions"]:
        _require(revision["old_property_id"] in active, "Revision must address an active prior property")
        _require(revision["new_property_id"] in added, "Replacement must be a new property in the same patch")
    combined = {key: copy.deepcopy(registry[key] + patch[key]) for key in ("events", "properties", "revisions", "unresolved")}
    combined["applied_turn_ids"] = registry["applied_turn_ids"] + [target_turn_id]
    combined["source_id"], combined["source_sha256"] = source["id"], digest(source)
    _validate_registry(combined, source)
    return copy.deepcopy(patch)


def project(registry):
    _validate_registry(registry)
    active = active_properties(registry)
    evidence = {s: [] for s in SECTION_MAP.values()}
    for prop in active:
        for code in prop["sections"]:
            evidence[SECTION_MAP[code]].append({"text": prop["text"], "property_id": prop["id"],
                "event_id": prop["event_id"], "kind": prop["kind"], "condition": prop["condition"],
                "source_turn_ids": list(dict.fromkeys(e["turn_id"] for e in prop["evidence"])),
                "evidence_quotes": copy.deepcopy(prop["evidence"]), "semantic_support_certified": False})
    return {"sections": {section: " ".join(row["text"] for row in rows) for section, rows in evidence.items()},
        "evidence": evidence, "active_property_ids": [p["id"] for p in active],
        "retired_property_ids": [r["old_property_id"] for r in registry["revisions"]],
        "unresolved": copy.deepcopy(registry["unresolved"]), "issues": _issues(registry),
        "one_property_version_for_all_sections": True, "semantic_support_certified": False,
        "no_semantic_deduplication_or_implicit_revision": True}


def apply_patch(registry, patch, source, target_turn_id):
    """Apply an atomic structurally valid patch; quarantine invalid raw responses."""
    before_hash = digest(registry)
    try:
        validated = validate_patch(registry, patch, source, target_turn_id)
    except Exception as exc:
        return {"accepted": False, "registry": copy.deepcopy(registry), "projection": project(registry),
            "event_log": [], "errors": [{"type": type(exc).__name__, "reason": str(exc)}],
            "quarantined_patch": copy.deepcopy(patch), "prior_registry_unchanged": True,
            "registry_before_sha256": before_hash, "registry_after_sha256": before_hash,
            "new_provider_api_calls": 0, "semantic_support_certified": False}
    merged = {key: copy.deepcopy(registry[key] + validated[key]) for key in ("events", "properties", "revisions", "unresolved")}
    merged["applied_turn_ids"] = registry["applied_turn_ids"] + [target_turn_id]
    merged["source_id"], merged["source_sha256"] = source["id"], digest(source)
    log = []
    for kind in ("events", "properties"):
        for row in validated[kind]:
            log.append({"kind": {"events": "add_event", "properties": "add_property"}[kind],
                "id": row["id"], "record": copy.deepcopy(row), "record_sha256": digest(row)})
    props = {p["id"]: p for p in merged["properties"]}
    for revision in validated["revisions"]:
        old, new = props[revision["old_property_id"]], props[revision["new_property_id"]]
        log.append({"kind": "replace_property", **copy.deepcopy(revision),
            "old_property": copy.deepcopy(old), "new_property": copy.deepcopy(new),
            "old_property_sha256": digest(old), "new_property_sha256": digest(new),
            "unchanged_address": {k: old[k] for k in ("event_id", "kind", "condition")},
            "unchanged_sections": copy.deepcopy(old["sections"]),
            "other_events_and_property_versions_unchanged": True})
    return {"accepted": True, "registry": merged, "projection": project(merged), "event_log": log,
        "errors": [], "quarantined_patch": None, "prior_registry_unchanged": True,
        "registry_before_sha256": before_hash, "registry_after_sha256": digest(merged),
        "new_provider_api_calls": 0, "semantic_support_certified": False}
