"""E1-repair structural repairs and salvage (offline, synthetic)."""
import copy
import unittest

from backend import clinical_event_properties_e1_repair as repair
from backend import clinical_event_properties_v1 as core

SOURCE = {"id": "s", "version": 1, "stages": [{"id": 1, "title": "", "turns": [
    {"id": "t01", "role": "doctor", "text": "Что беспокоит?"},
    {"id": "t02", "role": "patient", "text": "Плохо сплю. Ещё тревожно."},
    {"id": "t03", "role": "doctor", "text": "Когда началось?"},
    {"id": "t04", "role": "patient", "text": "Месяц назад. Был приступ дома."},
    {"id": "t05", "role": "doctor", "text": "Точно месяц?"},
    {"id": "t06", "role": "patient", "text": "Нет, два месяца назад. Сколько лет — тридцать."}]}]}
QUOTES = {"t02": "Плохо сплю.", "t04": "Месяц назад.", "t06": "Нет, два месяца назад."}


def ev(turn="t02"):
    return [{"turn_id": turn, "quote": QUOTES[turn]}]


def event(id, kind="state", parent=None, turn="t02", label=None):
    return {"id": id, "kind": kind, "holder": "patient", "label": label or id, "episode": "unmarked",
            "parent_state_id": parent, "evidence": ev(turn)}


def prop(id, event_id, kind="presence", sections=("AM",), turn="t02", text=None, value=None):
    return {"id": id, "event_id": event_id, "kind": kind, "condition": "unmarked",
            "value": value or {"type": "literal", "text": "есть", "ref_event_id": None}, "text": text or id,
            "sections": list(sections), "certainty": "asserted", "approximate": False,
            "polarity": "affirmed", "evidence": ev(turn)}


def patch(events=(), props=(), revisions=()):
    return {"events": list(events), "properties": list(props), "revisions": list(revisions), "unresolved": []}


def base(turn="t02"):
    raw = patch([event("s1", turn=turn), event("e1", "episode", parent="s1", turn=turn)],
                [prop("p1", "s1", kind="onset", turn=turn)])
    out = core.apply_patch(core.empty_registry(), raw, SOURCE, turn)
    assert out["accepted"], out["errors"]
    return out["registry"]


def ops(out):
    return [row["op"] for row in out["normalization_log"]]


class E1RepairTests(unittest.TestCase):
    def test_event_reusing_property_id_is_renamed_and_references_follow(self):
        raw = patch([event("t06_p1", "background", turn="t06")], [prop("t06_p1", "t06_p1", turn="t06", sections=("AV",))])
        self.assertFalse(core.apply_patch(base(), raw, SOURCE, "t06")["accepted"])
        out = repair.apply_patch(base(), raw, SOURCE, "t06")
        self.assertTrue(out["accepted"])
        self.assertIn("rename_colliding_event_id", ops(out))
        new_prop = [p for p in out["registry"]["properties"] if p["id"] == "t06_p1"][0]
        self.assertEqual(new_prop["event_id"], "t06_p1_x1")
        self.assertEqual(new_prop["text"], "t06_p1")

    def test_verbatim_redeclared_event_is_dropped(self):
        raw = patch([event("s1")], [prop("p2", "s1", turn="t06")])
        out = repair.apply_patch(base(), raw, SOURCE, "t06")
        self.assertTrue(out["accepted"])
        self.assertIn("drop_redeclared_existing_event", ops(out))

    def test_episode_under_episode_lifts_and_orphan_becomes_state(self):
        raw = patch([event("e2", "episode", parent="e1", turn="t06"), event("e3", "episode", parent=None, turn="t06")],
                    [prop("p2", "e2", turn="t06"), prop("p3", "e3", turn="t06")])
        out = repair.apply_patch(base(), raw, SOURCE, "t06")
        self.assertTrue(out["accepted"], out["errors"])
        events = {e["id"]: e for e in out["registry"]["events"]}
        self.assertEqual(events["e2"]["parent_state_id"], "s1")
        self.assertEqual((events["e3"]["kind"], events["e3"]["parent_state_id"]), ("state", None))

    def test_first_event_owner_moves_and_impossible_reference_is_demoted(self):
        ref = lambda target: {"type": "event_ref", "text": "", "ref_event_id": target}
        raw = patch([], [prop("p2", "e1", kind="first_event", turn="t06", value=ref("e1")),
                         prop("p3", "s1", kind="first_event", turn="t06", value=ref("s1"), text="Первый — давно")])
        out = repair.apply_patch(base(), raw, SOURCE, "t06")
        self.assertTrue(out["accepted"], out["errors"])
        props = {p["id"]: p for p in out["registry"]["properties"]}
        self.assertEqual((props["p2"]["event_id"], props["p2"]["kind"]), ("s1", "first_event"))
        self.assertEqual((props["p3"]["kind"], props["p3"]["value"]["text"], props["p3"]["text"]),
                         ("other", "Первый — давно", "Первый — давно"))

    def test_literal_value_loses_stray_reference(self):
        value = {"type": "literal", "text": "после первого", "ref_event_id": "e1"}
        raw = patch([], [prop("p2", "s1", kind="occurrence_time", turn="t06", value=value)])
        self.assertFalse(core.apply_patch(base(), raw, SOURCE, "t06")["accepted"])
        out = repair.apply_patch(base(), raw, SOURCE, "t06")
        self.assertTrue(out["accepted"], out["errors"])
        self.assertEqual(out["registry"]["properties"][-1]["value"], {**value, "ref_event_id": None})

    def test_revision_on_other_event_is_readdressed_and_retires_old_value(self):
        raw = patch([event("s9", turn="t06")], [prop("p2", "s9", kind="onset", turn="t06", text="два месяца")],
                    [{"old_property_id": "p1", "new_property_id": "p2", "evidence": ev("t06")}])
        self.assertFalse(core.apply_patch(base(), raw, SOURCE, "t06")["accepted"])
        out = repair.apply_patch(base(), raw, SOURCE, "t06")
        self.assertTrue(out["accepted"], out["errors"])
        self.assertEqual([p["id"] for p in core.active_properties(out["registry"])], ["p2"])
        self.assertEqual([p["event_id"] for p in out["registry"]["properties"] if p["id"] == "p2"], ["s1"])

    def test_revision_changing_kind_keeps_both_values(self):
        raw = patch([], [prop("p2", "s1", kind="duration", turn="t06")],
                    [{"old_property_id": "p1", "new_property_id": "p2", "evidence": ev("t06")}])
        out = repair.apply_patch(base(), raw, SOURCE, "t06")
        self.assertTrue(out["accepted"], out["errors"])
        self.assertIn("revision_link_dropped_address_mismatch", ops(out))
        self.assertEqual(sorted(p["id"] for p in core.active_properties(out["registry"])), ["p1", "p2"])

    def test_records_from_rejected_window_are_recovered_for_that_turn(self):
        raw = patch([event("s2", turn="t04")], [prop("p2", "s2", turn="t04"), prop("p3", "s1", turn="t06")])
        self.assertFalse(core.apply_patch(base(), raw, SOURCE, "t06")["accepted"])
        out = repair.apply_patch(base(), raw, SOURCE, "t06")
        self.assertTrue(out["accepted"])
        self.assertEqual(out["registry"]["applied_turn_ids"], ["t02", "t04", "t06"])
        self.assertEqual(out["salvage"]["dropped"], [])
        self.assertEqual([s["target_turn_id"] for s in out["salvage"]["steps"]], ["t04", "t06"])

    def test_no_recovery_into_already_applied_turn(self):
        reg = base("t04")
        raw = patch([], [prop("p2", "s1", turn="t02"), prop("p3", "s1", kind="severity", turn="t06")])
        out = repair.apply_patch(reg, raw, SOURCE, "t06")
        self.assertTrue(out["accepted"])
        self.assertTrue(out["partial"])
        self.assertEqual([d["id"] for d in out["salvage"]["dropped"]], ["p2"])
        self.assertEqual(out["registry"]["applied_turn_ids"], ["t04", "t06"])

    def test_greedy_salvage_drops_only_invalid_record(self):
        raw = patch([], [prop("p2", "missing", turn="t06"), prop("p3", "s1", kind="severity", turn="t06")])
        out = repair.apply_patch(base(), raw, SOURCE, "t06")
        self.assertTrue(out["accepted"])
        self.assertEqual([d["id"] for d in out["salvage"]["dropped"]], ["p2"])
        self.assertIn("p3", [p["id"] for p in out["registry"]["properties"]])

    def test_nothing_salvageable_stays_rejected_and_inputs_unmodified(self):
        reg, raw = base(), patch([], [prop("p2", "missing", turn="t06")])
        before = copy.deepcopy((reg, raw))
        out = repair.apply_patch(reg, raw, SOURCE, "t06")
        self.assertFalse(out["accepted"])
        self.assertEqual((reg, raw), before)

    def test_clinical_fields_never_edited(self):
        raw = patch([event("t06_p1", "episode", parent=None, turn="t06")], [prop("t06_p1", "t06_p1", turn="t06")])
        repaired, _ = repair.repair_patch(base(), raw)
        fields = ("text", "value", "sections", "certainty", "approximate", "polarity", "evidence", "condition")
        self.assertEqual([{k: p[k] for k in fields} for p in repaired["properties"]],
                         [{k: p[k] for k in fields} for p in raw["properties"]])
        self.assertEqual([e["evidence"] for e in repaired["events"]], [e["evidence"] for e in raw["events"]])


if __name__ == "__main__":
    unittest.main()
