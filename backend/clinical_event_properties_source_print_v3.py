"""Candidate print-v3: keep print-v2 attribution checks within sentence boundaries.

Only the optional source marker may change; registry, sidecar, clinical text and
routes remain unchanged. This is not a parser or a clinical-truth validator.
"""
import re
from backend import clinical_event_properties_e1_events as events
from backend import clinical_event_properties_source_v1 as sources
from backend import clinical_event_properties_source_print_v2 as previous

VERSION = "clinical-event-properties-source-print-v3"
BOUNDARY = re.compile(r"[.!?;\n\r]+")


def names_source(text, name):
    return any(previous.names_source(clause, name)
               for clause in BOUNDARY.split(text or "") if clause.strip())


def mark(text, reported_by):
    if sources.is_patient(reported_by):
        return text, False
    name = previous.role(reported_by)
    if name is None:
        return text.rstrip() + " (со слов другого человека)", True
    if names_source(text, name):
        return text, False
    return text.rstrip() + f" (со слов: {name})", True


def project(registry, sidecar):
    projection = events.project(registry)
    marked = []
    for section, rows in projection["evidence"].items():
        for row in rows:
            row["reported_by"] = sidecar.get(row["property_id"])
            row["text"], added = mark(row["text"], row["reported_by"])
            if added:
                marked.append({"section": section, "property_id": row["property_id"],
                               "reported_by": row["reported_by"]})
        projection["sections"][section] = " ".join(row["text"] for row in rows)
    projection["source_marks_added"] = marked
    projection["version"] = VERSION
    return projection
