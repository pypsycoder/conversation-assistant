"""Base S: reported_by sidecar, R1 for short answers, «(со слов: …)» at print (offline, synthetic)."""
import copy
import unittest

from jsonschema import ValidationError

from backend import clinical_event_properties_e1_events as events
from backend import clinical_event_properties_source_v1 as S
from backend import clinical_event_properties_v1 as core

SOURCE = {"id": "s", "version": 1, "stages": [{"id": 1, "title": "", "turns": [
    {"id": "t01", "role": "doctor", "text": "Что беспокоит?"},
    {"id": "t02", "role": "patient", "text": "Плохо сплю. Жена говорит, что я кричу во сне."},
    {"id": "t03", "role": "doctor", "text": "Сколько выпиваете?"},
    {"id": "t04", "role": "patient", "text": "Грамм сто пятьдесят коньяка почти каждый вечер."},
    {"id": "t05", "role": "doctor", "text": "Правильно ли я понял: вы пьёте коньяк, чтобы уснуть. Так?"},
    {"id": "t06", "role": "patient", "text": "Да, так."},
    {"id": "t07", "role": "doctor", "text": "Хотите добавить?"},
    {"id": "t08", "role": "patient", "text": "Коньяка — не сто пятьдесят, а скорее двести, если честно."}]}]}
TEXT = {t["id"]: t["text"] for t in SOURCE["stages"][0]["turns"]}


def ev(turn):
    return [{"turn_id": turn, "quote": TEXT[turn]}]


def event(id, turn, kind="state"):
    return {"id": id, "kind": kind, "holder": "patient", "label": id, "episode": "unmarked",
            "parent_state_id": None, "evidence": ev(turn)}


def prop(id, event_id, turn, text, kind="presence", sections=("AM",)):
    return {"id": id, "event_id": event_id, "kind": kind, "condition": "unmarked",
            "value": {"type": "literal", "text": "есть", "ref_event_id": None}, "text": text,
            "sections": list(sections), "certainty": "asserted", "approximate": False,
            "polarity": "affirmed", "evidence": ev(turn)}


def patch(evs=(), props=(), revisions=()):
    return {"events": list(evs), "properties": list(props), "revisions": list(revisions), "unresolved": []}


def wire(core_patch, sources):
    """Core patch -> wire output with reported_by and ID-only evidence."""
    raw = copy.deepcopy(core_patch)
    for row in [*raw["events"], *raw["properties"], *raw["revisions"]]:
        row["evidence"] = [{"turn_id": e["turn_id"]} for e in row["evidence"]]
    for p in raw["properties"]:
        ordered = {k: v for k, v in p.items() if k != "evidence"}
        ordered["reported_by"] = sources[p["id"]]
        ordered["evidence"] = p["evidence"]
        p.clear()
        p.update(ordered)
    return raw


def first():
    p = patch([event("s1", "t02"), event("b1", "t04", "background")],
              [prop("p1", "s1", "t02", "Плохо спит", sections=("C", "AM")),
               prop("p2", "s1", "t02", "Кричит во сне"),
               prop("p3", "b1", "t04", "Около 150 г коньяка почти каждый вечер", kind="quantity", sections=("AV",))])
    return p, {"p1": "пациент", "p2": "жена", "p3": "пациент"}


def registry_after_first():
    p, found = first()
    a1 = S.apply_patch(core.empty_registry(), {}, patch([p["events"][0]], p["properties"][:2]), SOURCE, "t02",
                       {k: found[k] for k in ("p1", "p2")})
    assert a1[0]["accepted"], a1[0]["errors"]
    a2 = S.apply_patch(a1[0]["registry"], a1[1], patch([p["events"][1]], [p["properties"][2]]), SOURCE, "t04", {"p3": "пациент"})
    assert a2[0]["accepted"], a2[0]["errors"]
    return a2[0]["registry"], a2[1]


def revision(turn, text="Около 200 г коньяка почти каждый вечер"):
    return patch([], [prop("p9", "b1", turn, text, kind="quantity", sections=("AV",))],
                 [{"old_property_id": "p3", "new_property_id": "p9", "evidence": ev(turn)}])


def active(reg):
    return [p["id"] for p in core.active_properties(reg)]


class SourceTests(unittest.TestCase):
    def test_wire_field_is_validated_and_stripped(self):
        p, found = first()
        raw = wire(patch([p["events"][0]], p["properties"][:2]), found)
        stripped, got = S.split_reported_by(raw)
        self.assertEqual(got, {"p1": "пациент", "p2": "жена"})
        self.assertNotIn("reported_by", stripped["properties"][0])
        self.assertIn("reported_by", raw["properties"][0])          # input untouched
        del raw["properties"][1]["reported_by"]
        with self.assertRaises(ValidationError):
            S.split_reported_by(raw)

    def test_registry_is_exactly_e1_events_and_sidecar_keeps_sources(self):
        reg, sidecar = registry_after_first()
        p, _ = first()
        plain = events.apply_patch(core.empty_registry(), patch([p["events"][0]], p["properties"][:2]), SOURCE, "t02")
        plain = events.apply_patch(plain["registry"], patch([p["events"][1]], [p["properties"][2]]), SOURCE, "t04")
        self.assertEqual(reg, plain["registry"])
        self.assertEqual(sidecar, {"p1": "пациент", "p2": "жена", "p3": "пациент"})

    def test_revision_on_long_answer_retires_old_and_new_keeps_its_own_source(self):
        reg, sidecar = registry_after_first()
        applied, side2 = S.apply_patch(reg, sidecar, revision("t08"), SOURCE, "t08", {"p9": "пациент"})
        self.assertTrue(applied["accepted"], applied["errors"])
        self.assertEqual(applied["r1_log"], [])
        self.assertNotIn("p3", active(applied["registry"]))
        self.assertEqual((side2["p3"], side2["p9"]), ("пациент", "пациент"))

    def test_r1_short_answer_without_its_words_adds_instead_of_replacing(self):
        reg, sidecar = registry_after_first()
        applied, _ = S.apply_patch(reg, sidecar, revision("t06", "Пьёт коньяк для сна"), SOURCE, "t06", {"p9": "пациент"})
        self.assertTrue(applied["accepted"], applied["errors"])
        self.assertEqual([r["op"] for r in applied["r1_log"]], ["r1_revision_added_only"])
        self.assertTrue({"p3", "p9"} <= set(active(applied["registry"])))
        off, _ = S.apply_patch(reg, sidecar, revision("t06", "Пьёт коньяк для сна"), SOURCE, "t06", {"p9": "пациент"}, r1=False)
        self.assertNotIn("p3", active(off["registry"]))

    def test_r1_threshold(self):
        self.assertTrue(S.r1_blocks("Пьёт коньяк для сна", "Да, так."))
        self.assertFalse(S.r1_blocks("Возраст 29 лет", "Двадцать девять, 29."))
        self.assertFalse(S.r1_blocks("Около 200 г", TEXT["t08"]))

    def test_colliding_id_rename_carries_the_source(self):
        reg, sidecar = registry_after_first()
        clash = patch([], [prop("p2", "s1", "t08", "Просыпается в поту")])
        applied, side2 = S.apply_patch(reg, sidecar, clash, SOURCE, "t08", {"p2": "сын"})
        self.assertTrue(applied["accepted"], applied["errors"])
        renamed = [e["to"] for e in applied["normalization_log"] if e["op"] == "rename_colliding_property_id"]
        self.assertEqual(len(renamed), 1)
        self.assertEqual((side2["p2"], side2[renamed[0]]), ("жена", "сын"))

    def test_print_appends_source_only_when_text_lacks_it(self):
        self.assertEqual(S.mark("Кричит во сне", "жена"), ("Кричит во сне (со слов: жена)", True))
        self.assertEqual(S.mark("По словам жены, кричит во сне", "жена"), ("По словам жены, кричит во сне", False))
        self.assertEqual(S.mark("Со слов кардиолога, сердце здорово", "кардиолог"), ("Со слов кардиолога, сердце здорово", False))
        self.assertEqual(S.mark("Плохо спит", "Пациент"), ("Плохо спит", False))
        self.assertEqual(S.mark("Плохо спит", None), ("Плохо спит", False))
        reg, sidecar = registry_after_first()
        projection = S.project(reg, sidecar)
        self.assertIn("Кричит во сне (со слов: жена)", projection["sections"]["illness_history"])
        self.assertEqual(projection["source_marks_added"], [{"section": "illness_history", "property_id": "p2", "reported_by": "жена"}])
        self.assertEqual(S.project(reg, {})["sections"], events.project(reg)["sections"])


if __name__ == "__main__":
    unittest.main()
