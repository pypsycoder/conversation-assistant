"""E1-fixed normalization/routing invariants (offline, synthetic)."""
import copy
import unittest

from backend import clinical_event_properties_e1_fixed as fixed
from backend import clinical_event_properties_v1 as core

SOURCE = {"id": "s", "version": 1, "stages": [{"id": 1, "title": "", "turns": [
    {"id": "t01", "role": "doctor", "text": "Что беспокоит?"},
    {"id": "t02", "role": "patient", "text": "Плохо сплю. Ещё тревожно."}]}]}


def ev(sid="t02"):
    return [{"turn_id": sid, "quote": "Плохо сплю. Ещё тревожно."}]


def event(id, kind, parent=None):
    return {"id": id, "kind": kind, "holder": "patient", "label": id, "episode": "unmarked",
            "parent_state_id": parent, "evidence": ev()}


def prop(id, event_id, sections):
    return {"id": id, "event_id": event_id, "kind": "presence", "condition": "unmarked",
            "value": {"type": "literal", "text": "есть", "ref_event_id": None}, "text": id,
            "sections": sections, "certainty": "asserted", "approximate": False,
            "polarity": "affirmed", "evidence": ev()}


def patch(events, props):
    return {"events": events, "properties": props, "revisions": [], "unresolved": []}


class E1FixedTests(unittest.TestCase):
    def test_substate_parent_is_nulled_and_patch_now_accepted(self):
        raw = patch([event("s1", "state"), event("s2", "state", parent="s1")], [prop("p1", "s2", ["C"])])
        self.assertFalse(core.apply_patch(core.empty_registry(), raw, SOURCE, "t02")["accepted"])
        out = fixed.apply_patch(core.empty_registry(), raw, SOURCE, "t02")
        self.assertTrue(out["accepted"])
        self.assertEqual(out["normalization_log"][0]["dropped_parent_state_id"], "s1")

    def test_episode_parent_and_all_text_untouched_and_input_not_mutated(self):
        raw = patch([event("s1", "state"), event("e1", "episode", parent="s1")], [prop("p1", "e1", ["AM"])])
        before = copy.deepcopy(raw)
        normalized, log = fixed.normalize_patch(raw)
        self.assertEqual(raw, before)
        self.assertEqual(normalized, before)
        self.assertEqual(log, [])

    def test_other_core_errors_still_reject(self):
        raw = patch([event("e1", "episode", parent="missing")], [])
        self.assertFalse(fixed.apply_patch(core.empty_registry(), raw, SOURCE, "t02")["accepted"])

    def test_routing_only_at_projection_C_implies_AM(self):
        raw = patch([event("s1", "state")], [prop("c_only", "s1", ["C"]), prop("av", "s1", ["AV"]), prop("am", "s1", ["AM"])])
        reg = fixed.apply_patch(core.empty_registry(), raw, SOURCE, "t02")["registry"]
        self.assertEqual([p["sections"] for p in reg["properties"]], [["C"], ["AV"], ["AM"]])
        ids = lambda sec: [r["property_id"] for r in fixed.project(reg)["evidence"][sec]]
        self.assertEqual(ids("complaints"), ["c_only"])
        self.assertEqual(ids("illness_history"), ["c_only", "am"])
        self.assertEqual(ids("life_history"), ["av"])
        self.assertEqual(core.project(reg)["evidence"]["illness_history"][0]["property_id"], "am")


if __name__ == "__main__":
    unittest.main()
