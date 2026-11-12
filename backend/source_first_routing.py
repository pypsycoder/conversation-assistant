"""Route cited assertions in the source-first nightly experiment."""
from backend.three_sections import EVIDENCE, SCHEMA, TITLES

SECTION_BY_KIND = {
    "current_difficulty": "complaints",
    "general_course": "illness_history",
    "symptom_course": "illness_history",
    "other_illness": "illness_history",
    "biography": "life_history",
}

SOURCE_FIRST_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "assertions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "evidence": EVIDENCE,
                    "text": {"type": "string", "minLength": 1},
                    "kind": {"type": "string", "enum": list(SECTION_BY_KIND)},
                },
                "required": ["evidence", "text", "kind"],
            },
        },
        "gaps": SCHEMA["properties"]["gaps"],
    },
    "required": ["assertions", "gaps"],
}


def route_assertions(inventory):
    """Preserve the model's text and citations while assigning sections."""
    sections = {name: [] for name in TITLES}
    for assertion in inventory["assertions"]:
        section = SECTION_BY_KIND[assertion["kind"]]
        sections[section].append({"text": assertion["text"], "evidence": assertion["evidence"]})
    return {"sections": sections, "gaps": inventory["gaps"]}
