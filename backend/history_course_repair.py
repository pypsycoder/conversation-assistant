"""Experimental synthetic-only restoration of bounded general-course quotations."""
import argparse
import copy
import re
from collections import Counter
from pathlib import Path

from backend.complaint_quote_repair import (
    TIME, DAY, TIME_OF_DAY, GENERAL_COURSE, LITERAL_WORSENING, CURRENT_SYMPTOM, EARLIER_IMPROVEMENT,
    CLAUSE_SEPARATOR, complete_quote, sentence_text, repair_complaints,
)
from backend.nightly_research import read, save
from backend.three_sections import provenance_errors

# Whole general-course rows only; no symptom, treatment, condition or uncertainty.
COURSE_TIME = rf"(?:(?:{DAY} )?{TIME_OF_DAY}|{TIME}|позавчера)"
CONDITIONAL_CURRENT = re.compile(
    CURRENT_SYMPTOM.pattern.removesuffix(r"\.?") + r", если (?:встаю|наклоняюсь)\.?",
    re.IGNORECASE,
)
GENERAL_ROWS = [
    GENERAL_COURSE,
    LITERAL_WORSENING,
    re.compile(rf"{TIME} (?:общее )?(?:самочувствие|состояние) "
               r"(?:(?:снова|опять) )?(?:хуже|ухудшилось)", re.IGNORECASE),
    re.compile(rf"{TIME} общее ухудшение(?: состояния)?", re.IGNORECASE),
    re.compile(rf"ухудшение началось {COURSE_TIME}", re.IGNORECASE),
    re.compile(rf"{COURSE_TIME} (?:мне )?(?:(?:снова|опять) )?стало хуже", re.IGNORECASE),
]


def only_course(text):
    return any(pattern.fullmatch(sentence_text(text)) for pattern in GENERAL_ROWS)


def source_candidates(source):
    candidates = []
    # A later correction can retract an earlier quote without repeating its grammar.
    correction = re.compile(r"\b(?:нет\b|ошибся|ошиблась|уточню|поправлю|вернее|то есть|"
                            r"неправильно сказал|неправильно сказала)", re.IGNORECASE)
    if any(correction.search(s["text"]) for s in source["segments"] if s["role"] == "patient"):
        return candidates
    for segment in source["segments"]:
        if segment["role"] != "patient":
            continue
        text = segment["text"]
        for kind, pattern in (("state", GENERAL_COURSE), ("transition", LITERAL_WORSENING)):
            for match in re.finditer(rf"(?:{pattern.pattern})\.?", text, re.IGNORECASE):
                quote = match.group()
                # An explicit first-person subject is needed before adding a fact.
                if " мне " not in " " + quote.casefold() + " " or text.count(quote) != 1:
                    continue
                complete = complete_quote(quote, text, allow_after_improvement=kind == "state")
                if not complete and kind == "state" and not quote.endswith("."):
                    # A condition is allowed only after an explicit coordinator and current symptom.
                    tail = text[match.end():]
                    sep = CLAUSE_SEPARATOR.match(tail)
                    suffix = re.split(r"(?<=[.!?])\s+", tail[sep.end():], maxsplit=1)[0] if sep else ""
                    plain = bool(sep and CURRENT_SYMPTOM.fullmatch(suffix))
                    conditional = bool(re.match(r", (?:а|и) ", tail, re.IGNORECASE)
                                       and CONDITIONAL_CURRENT.fullmatch(suffix))
                    complete = bool((plain or conditional)
                                    and complete_quote(quote, text[:match.end()]))
                if not complete:
                    continue
                prefix = quote.casefold().split(" мне ", 1)[0]
                candidates.append(dict(segment_id=segment["id"], quote=quote,
                                       start=match.start(), end=match.end(), key=(kind, prefix)))
    return candidates


def overlaps(candidate, evidence, source_index):
    if evidence["segment_id"] != candidate["segment_id"]:
        return False
    text = source_index[candidate["segment_id"]]["text"]
    return any(m.start() < candidate["end"] and candidate["start"] < m.end()
               for m in re.finditer(re.escape(evidence["quote"]), text))



def exact_course_evidence(candidate, evidence, source_index):
    """Allow only the original course or its preceding contrast after explicit improvement."""
    if evidence["segment_id"] != candidate["segment_id"]:
        return False
    quote = evidence["quote"].removesuffix(".")
    course = candidate["quote"].removesuffix(".")
    if quote == course:
        return True
    if quote[:2].casefold() != "а " or quote[2:] != course:
        return False
    text = source_index[candidate["segment_id"]]["text"]
    start = candidate["start"] - 2
    if start < 0 or text[start:start + len(quote)] != quote:
        return False
    before = text[:start].rstrip()
    earlier = re.split(r"[.!?]", before + " а")[-1].strip()
    return EARLIER_IMPROVEMENT.fullmatch(earlier) is not None

def repair_history_course(result, source):
    """Replace a whole bounded course row or insert a missing literal course."""
    if source.get("synthetic") is not True:
        raise ValueError("Only explicitly synthetic dialogues are supported")
    index = {s["id"]: s for s in source["segments"]}
    if len(index) != len(source["segments"]) or provenance_errors(result, source):
        raise ValueError("Input citations must pass provenance validation")
    edited = copy.deepcopy(result)
    history = edited["sections"]["illness_history"]
    candidates = source_candidates(source)
    repeated = Counter(c["key"] for c in candidates)
    changes, abstentions = [], []
    for candidate in candidates:
        reference = dict(segment_id=candidate["segment_id"], quote=candidate["quote"])
        reason = None
        if repeated[candidate["key"]] > 1:
            reason = "repeated_source_course"
        touched = [i for i, row in enumerate(history)
                   if any(overlaps(candidate, e, index) for e in row["evidence"])]
        canonical = dict(text=candidate["quote"][0].upper() + candidate["quote"][1:].removesuffix(".") + ".",
                         evidence=[reference])
        if reason is None and len(touched) == 1:
            i = touched[0]
            row = history[i]
            exact = (len(row["evidence"]) == 1
                     and exact_course_evidence(candidate, row["evidence"][0], index))
            if sentence_text(row["text"]) == sentence_text(canonical["text"]) and exact:
                continue
            if not exact or not only_course(row["text"]):
                reason = "mixed_or_unrecognized_history_row"
            else:
                changes.append(dict(action="replace", history_index=i, original=copy.deepcopy(row), replacement=canonical))
                history[i] = canonical
        elif reason is None and not touched:
            if any(only_course(row["text"]) and candidate["key"][1] in sentence_text(row["text"]) for row in history):
                reason = "possible_course_already_elsewhere"
            else:
                changes.append(dict(action="insert", history_index=len(history), original=None, replacement=canonical))
                history.append(canonical)
        elif reason is None:
            reason = "multiple_history_rows"
        if reason:
            abstentions.append(dict(reason=reason, evidence=reference, history_indices=touched))
    if provenance_errors(edited, source):
        raise RuntimeError("Edited citations failed provenance validation")
    return edited, changes, abstentions


def main():
    parser = argparse.ArgumentParser(__doc__)
    for name in ("source", "result", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--complaints", action="store_true", help="Apply existing bounded complaint repair afterwards")
    args = parser.parse_args()
    source = read(args.source)
    result, changes, abstentions = repair_history_course(read(args.result), source)
    complaint_changes = []
    if args.complaints:
        result, complaint_changes = repair_complaints(result, source)
    save(args.output, dict(result=result, history_changes=changes, complaint_changes=complaint_changes,
                           abstentions=abstentions))


if __name__ == "__main__":
    main()
