"""Experimental synthetic-only distinction between present symptoms and onset now."""
import copy
import re
from backend.complaint_quote_repair import complete_quote, sentence_text
from backend.three_sections import provenance_errors

# Explicit pairs, never a generic replacement of arbitrary onset narratives.
PRESENCE_NOUNS = {
    "сейчас сильно болит голова": "сильной головной боли",
    "сейчас сильно болит горло": "сильной боли в горле",
    "сейчас сильно болит живот": "сильной боли в животе",
    "сейчас сильно тошнит": "сильной тошноты",
    "сейчас сильно дрожат руки": "сильной дрожи рук",
}
# Any patient onset reference, even dated/unknown, conservatively prevents editing.
# This avoids deleting a real onset conveyed in a different utterance.
SOURCE_VETO = re.compile(
    r"\b(?:начал\w*|появ\w*|впервые|только что|минут\w*|"
    r"нет|ошиб\w*|уточню|поправлю|вернее|кажется|возможно|наверное)\b",
    re.IGNORECASE,
)

def repair_presence_onset(result, source):
    """Rewrite only a whole invented onset-now row, leaving all other data untouched."""
    if source.get("synthetic") is not True:
        raise ValueError("Only explicitly synthetic dialogues are supported")
    index = {s["id"]: s for s in source["segments"]}
    if len(index) != len(source["segments"]) or provenance_errors(result, source):
        raise ValueError("Input citations must pass provenance validation")
    edited = copy.deepcopy(result)
    changes, abstentions = [], []
    veto = any(SOURCE_VETO.search(s["text"]) for s in source["segments"] if s["role"] == "patient")
    for i, row in enumerate(edited["sections"]["illness_history"]):
        normalized = sentence_text(row["text"])
        if not normalized.startswith("появление ") or not normalized.endswith(" сейчас"):
            continue
        if veto:
            abstentions.append(dict(history_index=i, reason="onset_or_uncertainty_or_correction_in_source"))
            continue
        if len(row["evidence"]) != 1:
            abstentions.append(dict(history_index=i, reason="multiple_citations"))
            continue
        evidence = row["evidence"][0]
        segment = index[evidence["segment_id"]]
        quote = evidence["quote"]
        noun = PRESENCE_NOUNS.get(sentence_text(quote))
        if (segment["role"] != "patient" or not noun
                or normalized != "появление " + noun + " сейчас"
                or not complete_quote(quote, segment["text"], allow_after_improvement=False)):
            abstentions.append(dict(history_index=i, reason="not_exact_bounded_presence_pair"))
            continue
        replacement = dict(text=quote[0].upper() + quote[1:].removesuffix(".") + ".",
                           evidence=copy.deepcopy(row["evidence"]))
        if any(other["text"] == replacement["text"] for j, other in
               enumerate(edited["sections"]["illness_history"]) if j != i):
            abstentions.append(dict(history_index=i, reason="possible_duplicate"))
            continue
        changes.append(dict(action="replace", history_index=i, original=copy.deepcopy(row),
                            replacement=copy.deepcopy(replacement)))
        edited["sections"]["illness_history"][i] = replacement
    if provenance_errors(edited, source):
        raise RuntimeError("Edited citations failed provenance validation")
    return edited, changes, abstentions
