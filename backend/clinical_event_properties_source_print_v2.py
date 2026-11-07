"""Print v2 for base S: Russian role names and a stricter «source already named» check.

v1 (backend/clinical_event_properties_source_v1.py, frozen with the online runs)
had two print defects found in report.md of clinical-base-source-r1-2026-10-26:

1. The model sometimes writes reported_by in English (wife, mother, sister,
   neighbor_opposite…); v1 printed «(со слов: wife)». v2 translates a closed list
   of role words; an English value outside the list prints «(со слов другого
   человека)» rather than an English word. «patient» stays the patient.
2. v1 took any word with the reporter's stem as the source being named, so
   «Раздражается на мужа» suppressed «(со слов: муж)». v2 counts the source as
   named only in a reporting phrase: «по словам/со слов/по мнению/по наблюдению/
   по оценке <X>», «<X> говорит/сказал/считает/отмечает/…» within five words,
   or «<X>:» at the start of a clause.

Registry, sidecar and R1 are unchanged; only the printed text differs.
"""
import re

from backend import clinical_event_properties_e1_events as events
from backend import clinical_event_properties_source_v1 as v1

VERSION = "clinical-event-properties-source-print-v2"
ROLES = {"wife": "жена", "husband": "муж", "spouse": "супруг(а)", "mother": "мать", "mom": "мама", "father": "отец",
         "dad": "папа", "sister": "сестра", "brother": "брат", "son": "сын", "daughter": "дочь", "aunt": "тётя",
         "uncle": "дядя", "grandmother": "бабушка", "grandfather": "дедушка", "relatives": "родственники",
         "neighbor": "сосед", "neighbour": "сосед", "neighbor_opposite": "соседка напротив", "colleague": "коллега",
         "colleagues": "коллеги", "friend": "друг", "boss": "начальник", "doctor": "врач", "neurologist": "невролог",
         "cardiologist": "кардиолог", "therapist": "терапевт", "pediatrician": "педиатр",
         "gynecologist": "гинеколог", "endocrinologist": "эндокринолог", "investigator": "следователь"}
ALIASES = {"мама": ("мат",), "мать": ("мам",), "папа": ("отц", "отец"), "отец": ("отц", "пап"),
           "супруг": ("муж", "жен"), "супруга": ("жен",)}
LEAD = re.compile(r"^(словам|слов|мнению|наблюдению|оценке|данным)$")
VERB = re.compile(r"^(говор|сказа|счита|отмеча|отметил|сообща|сообщи|замеча|заметил|оценива|полага|совету|посовет|"
                  r"настаива|настоял|утвержда|рассказ|указ|увер|жалу|призна|видит|видел)")


def role(reported_by):
    """Russian role for printing; None for the patient."""
    if v1.is_patient(reported_by):
        return None
    value = reported_by.strip()
    if not re.search(r"[A-Za-z]", value):
        return value
    return ROLES.get(value.casefold().replace(" ", "_").replace("-", "_"))


def names_source(text, name):
    """True when the text names `name` as the one who reported, not merely mentions it."""
    words_of_name = [r for r in re.findall(r"[^\W_]+", name.casefold()) if r not in v1.STOP]
    stems = [v1._stem(r) for r in words_of_name] + [a for r in words_of_name for a in ALIASES.get(r, ())]
    lowered = (text or "").casefold()
    words = re.findall(r"[^\W_]+", lowered)
    for i, word in enumerate(words):
        if not any(word.startswith(s) for s in stems):
            continue
        if any(LEAD.match(w) for w in words[max(0, i - 2):i]):
            return True
        if any(VERB.match(w) for w in words[i + 1:i + 6]):
            return True
    return any(re.search(r"(^|[.;—-]\s*)" + re.escape(s) + r"[^\W_]*\s*:", lowered) for s in stems)


def mark(text, reported_by):
    if v1.is_patient(reported_by):
        return text, False
    name = role(reported_by)
    if name is None:
        return text.rstrip() + " (со слов другого человека)", True
    if names_source(text, name):
        return text, False
    return text.rstrip() + f" (со слов: {name})", True


def project(registry, sidecar):
    """E1-events projection with print-v2 marks; sections are rebuilt from rows."""
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
