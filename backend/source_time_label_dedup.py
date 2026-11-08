"""Conservative print-only suppression of a redundant literal time-label row."""
import copy
import re
from backend import clinical_event_properties_source_print_v3 as base

VERSION = "source-time-label-dedup-v1"
KINDS = {"frequency", "within_day", "occurrence_time"}
LABEL = r"(?:частота|время суток|время возникновения)"


def label_only(prop):
    value = prop["value"]
    if (prop["kind"] not in KINDS or prop["polarity"] != "affirmed"
            or value["type"] != "literal" or not value["text"].strip()):
        return False
    return bool(re.fullmatch(LABEL + r"\s*[:—–-]?\s*" + re.escape(value["text"].strip()) + r"[.]?",
                             prop["text"].strip(), re.IGNORECASE))


def same_grounding(a, b, sidecar):
    keys = ("event_id", "condition", "value", "certainty", "polarity", "approximate", "evidence")
    return (all(a[k] == b[k] for k in keys)
            and sidecar.get(a["id"]) == sidecar.get(b["id"]))


def project(registry, sidecar):
    projection = base.project(registry, sidecar)
    props = {p["id"]: p for p in registry["properties"]}
    log = []
    for section, rows in projection["evidence"].items():
        kept = []
        for row in rows:
            prop = props[row["property_id"]]
            owner = None
            if label_only(prop):
                for other in rows:
                    candidate = props[other["property_id"]]
                    if (candidate["id"] != prop["id"] and candidate["kind"] in KINDS
                            and not label_only(candidate) and same_grounding(prop, candidate, sidecar)
                            and not re.search(r"\b(?:не|нет|никогда)\b", candidate["text"], re.IGNORECASE)
                            and prop["value"]["text"].casefold() in candidate["text"].casefold()):
                        owner = other
                        break
            if owner is None:
                kept.append(row)
            else:
                owner.setdefault("merged_property_ids", []).append(prop["id"])
                log.append({"section": section, "kept_property_id": owner["property_id"],
                            "suppressed_row": copy.deepcopy(row), "rule": "same_grounding_and_label_only"})
        projection["evidence"][section] = kept
        projection["sections"][section] = " ".join(r["text"] for r in kept)
    projection["suppressed_duplicate_rows"] = log
    projection["version"] = VERSION
    return projection
