"""Offline schema and cross-reference validation. Does not interpret Russian speech."""
import json
import math
from datetime import datetime
from pathlib import Path
from jsonschema import Draft202012Validator
from .formatting import section_text

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "contracts/session.schema.json").read_text(encoding="utf-8"))
MAPPING = json.loads((ROOT / "contracts/psydraft-allowlist.json").read_text(encoding="utf-8"))
Draft202012Validator.check_schema(SCHEMA)
VALIDATOR = Draft202012Validator(SCHEMA)
SECTION_ORDER = ["complaints", "anamnesis", "life_history", "mental_status", "diagnosis", "recommendations", "prescriptions"]
ACTIVE = {"proposed", "accepted", "edited"}


def loads(text):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key: " + key)
            result[key] = value
        return result
    return json.loads(text, object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Non-finite JSON number: " + value)))


def value_errors(target, value):
    rule = MAPPING["fields"].get(target)
    if not rule:
        return ["target is outside mapping allowlist"]
    if rule["type"] == "string":
        return [] if isinstance(value, str) and value.strip() else ["empty or non-text field value"]
    if rule["type"] == "array":
        valid = isinstance(value, list) and bool(value) and all(isinstance(v, str) and v in rule["options"] for v in value)
        if valid:
            valid = len(value) == len(set(value))
        return [] if valid else ["invalid checkbox values"]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return ["expected finite number"]
    if not rule["minimum"] <= value <= rule["maximum"]:
        return ["number outside form bounds"]
    steps = (value - rule["minimum"]) / rule["step"]
    return [] if math.isclose(steps, round(steps), abs_tol=1e-8) else ["number violates form step"]


def validate_session(session):
    errors = []
    def fail(path, message):
        errors.append({"path": path, "message": message})
    def finite(value, path="$"):
        if isinstance(value, float) and not math.isfinite(value):
            fail(path, "non-finite number")
        elif isinstance(value, dict):
            for key, item in value.items():
                finite(item, path + "." + key)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                finite(item, f"{path}[{index}]")
    finite(session)
    for error in VALIDATOR.iter_errors(session):
        fail("$." + ".".join(map(str, error.absolute_path)), error.message)
    if errors:
        return errors
    def index(collection):
        result = {}
        for item in session[collection]:
            if item["id"] in result:
                fail(collection, "duplicate id: " + item["id"])
            result[item["id"]] = item
        return result
    speakers = index("speakers")
    segments = index("segments")
    facts = index("facts")
    proposals = index("proposals")
    index("review_events")
    index("capture_gaps")
    versions = {}
    for segment in session["segment_history"] + session["segments"]:
        key = (segment["id"], segment["revision"])
        if key in versions:
            fail("segments", "duplicate segment version")
        versions[key] = segment
        if segment["speaker_id"] not in speakers:
            fail(segment["id"], "unknown speaker")
        if segment["end"] <= segment["start"]:
            fail(segment["id"], "end must be after start")
    for previous in session["segment_history"]:
        latest = segments.get(previous["id"])
        if not latest or previous["revision"] >= latest["revision"]:
            fail(previous["id"], "history must precede current segment revision")
    for gap in session["capture_gaps"]:
        if gap["end"] <= gap["start"]:
            fail(gap["id"], "invalid capture gap interval")
    for fact in facts.values():
        path = fact["id"]
        support = [e for e in fact["evidence"] if e["kind"] == "support"]
        if not support:
            fail(path, "fact needs support evidence, not only question/context")
        for evidence in fact["evidence"]:
            segment = versions.get((evidence["segment_id"], evidence["revision"]))
            if not segment:
                fail(path, "unknown segment version")
                continue
            if evidence["quote"] not in segment["text"]:
                fail(path, "quote is not verbatim in referenced version")
            if not segment["start"] <= evidence["start"] < evidence["end"] <= segment["end"]:
                fail(path, "evidence interval outside segment")
            if fact["review_status"] in ACTIVE:
                if segments.get(segment["id"], {}).get("revision") != evidence["revision"] or segment["status"] != "stable":
                    fail(path, "active fact needs current stable evidence")
                speaker = speakers.get(segment["speaker_id"], {})
                if evidence["kind"] == "support" and (speaker.get("role") != fact["source_role"] or not speaker.get("role_confirmed")):
                    fail(path, "support role differs or is not confirmed")
                if any(segment["start"] < g["end"] and g["start"] < segment["end"] for g in session["capture_gaps"]):
                    fail(path, "active fact crosses a capture gap")
        if fact["type"] in {"complaint", "symptom"} and fact["source_role"] == "doctor":
            fail(path, "doctor questions/statements cannot be patient complaints")
        if fact["type"] in {"doctor_observation", "doctor_statement"} and fact["source_role"] != "doctor":
            fail(path, "doctor observation/statement needs doctor source")
        for identifier in fact.get("supersedes_fact_ids", []):
            previous = facts.get(identifier)
            if not previous or identifier == fact["id"]:
                fail(path, "invalid superseded fact reference")
            elif not fact.get("conflict_group_id") or previous.get("conflict_group_id") != fact["conflict_group_id"]:
                fail(path, "correction must share conflict group")
        if "duration" in fact and fact["duration"]["source_text"] not in " ".join(e["quote"] for e in support):
            fail(path, "duration source text missing from support")
    # A correction graph must be acyclic; contradictory statements can coexist.
    def visit(identifier, ancestors):
        if identifier in ancestors:
            fail(identifier, "correction reference cycle")
            return
        for previous in facts.get(identifier, {}).get("supersedes_fact_ids", []):
            visit(previous, ancestors | {identifier})
    for identifier in facts:
        visit(identifier, set())
    latest_reviews = {}
    latest_edits = {}
    previous_time = None
    for event in session["review_events"]:
        try:
            event_time = datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00"))
            if event_time.tzinfo is None or (previous_time and event_time < previous_time):
                fail(event["id"], "review timestamps need timezone and chronological order")
            previous_time = event_time
        except ValueError:
            fail(event["id"], "invalid review timestamp")
        obj = (facts if event["object_type"] == "fact" else proposals).get(event["object_id"])
        if not obj or event["revision"] > obj["revision"]:
            fail(event["id"], "unknown review object/revision")
        else:
            latest_reviews[(event["object_type"], event["object_id"], event["revision"])] = event
            if event["action"] == "edit":
                latest_edits[(event["object_type"], event["object_id"], event["revision"])] = event
        if event["action"] == "edit" and "value" not in event:
            fail(event["id"], "edit event needs clinician value")
    for kind, objects in [("fact", facts), ("proposal", proposals)]:
        for obj in objects.values():
            expected_action = {"accepted": "accept", "edited": "edit", "rejected": "reject"}.get(obj["review_status"])
            event = latest_reviews.get((kind, obj["id"], obj["revision"]))
            if expected_action and (not event or event["action"] != expected_action):
                fail(obj["id"], "review status has no matching current review event")
            if obj["review_status"] == "proposed" and event:
                fail(obj["id"], "reviewed object cannot remain proposed at same revision")
            if kind == "proposal" and "clinician_value" in obj:
                edit = latest_edits.get((kind, obj["id"], obj["revision"]))
                if not edit or edit.get("value") != obj["clinician_value"]:
                    fail(obj["id"], "clinician value must match preserved edit event")
            if obj["review_status"] == "edited":
                field = "clinician_value" if kind == "proposal" else "description"
                if field not in obj or not event or obj[field] != event.get("value"):
                    fail(obj["id"], "edited object lost clinician value")
    for proposal in proposals.values():
        for message in value_errors(proposal["target"], proposal["value"]):
            fail(proposal["id"], message)
        if "clinician_value" in proposal:
            for message in value_errors(proposal["target"], proposal["clinician_value"]):
                fail(proposal["id"], "clinician value: " + message)
        linked = []
        for identifier in proposal["fact_ids"]:
            if identifier not in facts:
                fail(proposal["id"], "unknown fact reference")
            else:
                linked.append(facts[identifier])
        if proposal["review_status"] in ACTIVE and not value_errors(proposal["target"], proposal["value"]):
            if any(f["review_status"] not in ACTIVE for f in linked):
                fail(proposal["id"], "active proposal depends on stale/rejected facts")
            if proposal["target"] == "complaints" and any(f["experiencer"] != "patient" or f["source_role"] != "patient" or f["temporality"] != "current" or f["assertion"] not in {"present", "uncertain"} for f in linked):
                fail(proposal["id"], "complaints need current positive/uncertain patient reports")
            if proposal["target"].startswith("sleep"):
                if any(f["experiencer"] != "patient" or f["source_role"] != "patient" or f["temporality"] != "current" or f["assertion"] != "present" for f in linked):
                    fail(proposal["id"], "sleep fields need current patient support")
                if proposal["target"] == "sleep" and "проблемы с засыпанием (>30 минут)" in proposal["value"]:
                    if not any((f.get("sleep_latency_minutes") or 0) > 30 for f in linked):
                        fail(proposal["id"], "sleep threshold >30 minutes lacks quantified support")
                if proposal["target"] == "sleep_hours" and not any(f.get("sleep_hours") == proposal["value"] for f in linked):
                    fail(proposal["id"], "sleep hours not supported by normalized fact")
                if proposal["target"] == "sleep_days" and not any(f.get("duration", {}).get("unit") == "day" and f["duration"]["value"] == proposal["value"] for f in linked):
                    fail(proposal["id"], "sleep days not supported by normalized fact")
    report = session["report"]
    keys = [section["key"] for section in report["sections"]]
    if len(keys) != len(set(keys)) or keys != sorted(keys, key=SECTION_ORDER.index):
        fail("report", "section keys must be unique and in PsyDraft order")
    if set(report["missing_sections"]) != set(SECTION_ORDER) - set(keys):
        fail("report", "missing sections must match actual omissions")
    used = set()
    for section in report["sections"]:
        linked = [proposals[p] for p in section["proposal_ids"] if p in proposals]
        used.update(section["proposal_ids"])
        if len(linked) != len(section["proposal_ids"]):
            fail("report", "unknown proposal reference")
        if any(MAPPING["fields"].get(p["target"], {}).get("section") != section["key"] for p in linked):
            fail("report", "proposal belongs to another section")
        if set(section["fact_ids"]) != {identifier for p in linked for identifier in p["fact_ids"]}:
            fail("report", "section facts differ from supporting proposals")
        if any(p["review_status"] not in ACTIVE for p in linked):
            fail("report", "report contains stale/rejected proposal")
        if all(p["target"] in MAPPING["fields"] for p in linked) and section["text"] != section_text(linked):
            fail("report", "section text differs from supported proposal values")
    unreviewed = {p for p in used if p in proposals and proposals[p]["review_status"] == "proposed"}
    if set(report["unreviewed_proposal_ids"]) != unreviewed:
        fail("report", "unreviewed proposal list is inaccurate")
    if report["status"] == "reviewed" and (session["status"] != "stopped" or unreviewed or errors):
        fail("report", "reviewed report requires stopped capture and valid reviewed sources")
    return errors


def require_valid(session):
    errors = validate_session(session)
    if errors:
        raise ValueError(json.dumps(errors, ensure_ascii=False))
    return session
