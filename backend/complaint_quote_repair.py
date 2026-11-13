"""Conservative offline repair of literal complaints in synthetic extracts."""

import argparse
import copy
import re
from pathlib import Path

from backend.nightly_research import read, save
from backend.three_sections import provenance_errors

TIME = r"(?:сегодня|вчера|с (?:утра|ночи|вечера)|со вчерашнего (?:утра|вечера))"
GENERAL_COURSE = re.compile(
    rf"(?P<time>{TIME}) (?:мне )?в целом (?P<again>снова )?хуже", re.IGNORECASE
)
DAY = r"(?:сегодня|вчера|позавчера)"
TIME_OF_DAY = r"(?:после (?:завтрака|обеда|ужина)|к (?:утру|вечеру|ночи))"
LITERAL_WORSENING = re.compile(
    rf"(?:(?:{DAY} )?{TIME_OF_DAY}|{TIME}|позавчера) (?:мне )?(?:(?:снова|опять) )?"
    r"(?:стало хуже в целом|стало в целом хуже|в целом стало хуже)"
)
CURRENT_SYMPTOM = re.compile(
    r"сейчас (?:у меня |меня )?(?:сильно |очень )?"
    r"(?:кружится голова|тошнит|звенит в ушах|дрожат руки|"
    r"болит (?:голова|горло|живот|левое ухо|правое ухо))\.?",
    re.IGNORECASE,
)
CLAUSE_SEPARATOR = re.compile(r", (?:и |а )?", re.IGNORECASE)
EARLIER_IMPROVEMENT = re.compile(
    r"(?:в выходные|вчера|позавчера) (?:мне )?было (?:лучше|легче|полегче), а",
    re.IGNORECASE,
)


def sentence_text(text):
    return text.strip().removesuffix(".").casefold()


def complete_quote(quote, text, *, allow_after_improvement=True):
    """Accept a whole sentence and optionally a clause after explicit earlier improvement."""
    matches = list(re.finditer(re.escape(quote), text))
    if len(matches) != 1:
        return False
    match = matches[0]
    before = text[:match.start()].rstrip()
    after = text[match.end():]
    if before and not before.endswith((".", "!", "?")):
        previous_clause = re.split(r"[.!?]", before)[-1].strip()
        if not allow_after_improvement or EARLIER_IMPROVEMENT.fullmatch(previous_clause) is None:
            return False
    if quote.endswith("."):
        return not after or after[0].isspace()
    return not after or (after.startswith(".") and (len(after) == 1 or after[1].isspace()))


def history_match(clause, match, segment, history, *, mixed=False):
    """Require the same utterance and preserve all recognized temporal modifiers."""
    if len(re.findall(re.escape(clause), segment["text"], flags=re.IGNORECASE)) != 1:
        return None
    time = match["time"]
    again = match["again"] or ""
    allowed = {sentence_text(clause), f"{time} общее самочувствие {again}ухудшилось"}
    if mixed:
        allowed.add(f"{time} общее самочувствие {again}хуже")
    if not again:
        allowed.add(f"{time} общее ухудшение состояния")
    for index, row in enumerate(history):
        if len(row["evidence"]) != 1 or sentence_text(row["text"]) not in allowed:
            continue
        evidence = row["evidence"][0]
        if evidence["segment_id"] == segment["id"] and evidence["quote"].removesuffix(".") == clause:
            return index
    return None


def complaint_patch(row, segments, history):
    if len(row["evidence"]) != 1:
        return None
    citation = row["evidence"][0]
    quote = citation["quote"]
    segment = segments[citation["segment_id"]]
    normalized_quote = sentence_text(quote)
    if segment["role"] != "patient" or sentence_text(row["text"]) != normalized_quote:
        return None

    if LITERAL_WORSENING.fullmatch(normalized_quote):
        if complete_quote(quote, segment["text"], allow_after_improvement=False):
            for index, history_row in enumerate(history):
                if history_row == row:
                    return index, None
        return None

    if not complete_quote(quote, segment["text"]):
        return None
    clauses = CLAUSE_SEPARATOR.split(quote, maxsplit=1)
    clause = clauses[0].removesuffix(".")
    course = GENERAL_COURSE.fullmatch(clause.casefold())
    if course is None:
        return None

    replacement = None
    if len(clauses) == 2:
        symptom = clauses[1]
        if CURRENT_SYMPTOM.fullmatch(symptom) is None:
            return None
        replacement = {
            "text": symptom[0].upper() + symptom[1:].removesuffix(".") + ".",
            "evidence": [{"segment_id": segment["id"], "quote": symptom}],
        }

    history_index = history_match(clause, course, segment, history, mixed=replacement is not None)
    if history_index is None:
        return None
    return history_index, replacement


def repair_complaints(result, source):
    """Return an edited copy and the original rows with their history references."""
    if source.get("synthetic") is not True:
        raise ValueError("Only explicitly synthetic dialogues are supported")
    segments = {segment["id"]: segment for segment in source["segments"]}
    if len(segments) != len(source["segments"]) or provenance_errors(result, source):
        raise ValueError("Input citations must pass provenance validation")

    edited = copy.deepcopy(result)
    sections = edited["sections"]
    complaints = []
    changes = []
    for index, row in enumerate(sections["complaints"]):
        patch = complaint_patch(row, segments, sections["illness_history"])
        if patch is None:
            complaints.append(row)
            continue
        history_index, replacement = patch
        changes.append({"complaint_index": index, "illness_history_index": history_index,
                        "original": row, "replacement": replacement})
        if replacement is not None:
            complaints.append(replacement)
    sections["complaints"] = complaints
    if changes and provenance_errors(edited, source):
        raise RuntimeError("Edited citations failed provenance validation")
    return edited, changes


def main():
    parser = argparse.ArgumentParser(__doc__)
    for name in ("source", "result", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    result, changes = repair_complaints(read(args.result), read(args.source))
    save(args.output, {"result": result, "changes": changes})


if __name__ == "__main__":
    main()
