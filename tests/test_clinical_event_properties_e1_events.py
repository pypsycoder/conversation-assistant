"""E1-events: code declares events that properties reference but the model omitted."""
import copy
import unittest

from backend import clinical_event_properties_e1_events as events
from backend import clinical_event_properties_v1 as core
from tests.test_clinical_event_properties_e1_repair import SOURCE, base, patch, prop


class E1EventsTests(unittest.TestCase):
    def test_undeclared_current_event_is_created_and_window_accepted(self):
        raw = patch([], [prop("t06_p1", "t06_e1", turn="t06", text="Спит семь часов", sections=("C",)),
                         prop("t06_p2", "t06_e1", kind="severity", turn="t06", text="Засыпает быстро", sections=("C",))])
        self.assertFalse(core.apply_patch(base(), raw, SOURCE, "t06")["accepted"])
        out = events.apply_patch(base(), raw, SOURCE, "t06")
        self.assertTrue(out["accepted"], out["errors"])
        created = [e for e in out["registry"]["events"] if e["id"] == "t06_e1"][0]
        self.assertEqual((created["kind"], created["holder"], created["label"], created["parent_state_id"]),
                         ("state", "patient", "Спит семь часов", None))
        self.assertEqual(created["evidence"], [{"turn_id": "t06", "quote": "Нет, два месяца назад."}])
        self.assertEqual(out["normalization_log"][0]["op"], "code_declared_missing_event")
        self.assertIsNone(out["salvage"])

    def test_life_history_only_properties_get_background_event(self):
        raw = patch([], [prop("t06_p1", "t05_e1", turn="t06", sections=("AV",))])
        declared, _ = events.declare_missing_events(base(), raw)
        self.assertEqual(declared["events"][0]["kind"], "background")

    def test_existing_events_are_not_redeclared_and_texts_untouched(self):
        raw = patch([], [prop("t06_p1", "s1", turn="t06")])
        declared, log = events.declare_missing_events(base(), raw)
        self.assertEqual((declared, log), (raw, []))
        raw2 = patch([], [prop("t06_p1", "t06_e9", turn="t06", text="x")])
        before = copy.deepcopy(raw2)
        declared2, _ = events.declare_missing_events(base(), raw2)
        self.assertEqual(raw2, before)
        self.assertEqual(declared2["properties"], raw2["properties"])


if __name__ == "__main__":
    unittest.main()
