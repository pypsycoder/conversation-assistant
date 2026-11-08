import copy
import unittest
import json
from pathlib import Path
from backend.source_time_label_dedup import label_only, same_grounding, project
from backend.clinical_event_properties_source_print_v3 import project as old_project
from tests.test_clinical_event_properties_source_v1 import registry_after_first


class LabelDedupTests(unittest.TestCase):
    def test_real_s_regression_keeps_registry_and_logs_both_suppressed_placements(self):
        folder = Path(__file__).resolve().parents[1] / "reports/evidence/cycle-02/paired/d02/s"
        registry = json.loads((folder / "registry.json").read_text(encoding="utf-8"))
        sidecar = json.loads((folder / "sidecar.json").read_text(encoding="utf-8"))
        before = copy.deepcopy((registry, sidecar))
        old, new = old_project(registry, sidecar), project(registry, sidecar)
        removed = new["suppressed_duplicate_rows"]
        self.assertEqual(len(removed), 2)
        self.assertEqual({r["section"] for r in removed}, {"complaints", "illness_history"})
        for section in old["evidence"]:
            previous = {r["property_id"]: r for r in old["evidence"][section]}
            for row in new["evidence"][section]:
                self.assertEqual(row["text"], previous[row["property_id"]]["text"])
        self.assertEqual((registry, sidecar), before)

    def properties(self):
        a = {"id": "a", "event_id": "e", "condition": "now", "kind": "within_day",
             "value": {"type": "literal", "text": "каждый вечер", "ref_event_id": None},
             "text": "Тревога возникает каждый вечер", "certainty": "asserted", "polarity": "affirmed",
             "approximate": False, "evidence": [{"turn_id": "s2", "quote": "Тревожно каждый вечер"}]}
        b = {**copy.deepcopy(a), "id": "b", "kind": "frequency", "text": "Частота — каждый вечер"}
        return a, b

    def test_additional_meaning_in_label_prevents_suppression(self):
        a, b = self.properties()
        self.assertTrue(label_only(b))
        self.assertFalse(label_only(a))
        for text in ("Частота — каждый вечер после работы", "Частота — не каждый вечер", "Частота — каждый вечер, мешает вождению"):
            self.assertFalse(label_only({**b, "text": text}))

    def test_different_time_source_event_or_modality_cannot_be_merged(self):
        a, b = self.properties()
        sidecar = {"a": "пациент", "b": "пациент"}
        self.assertTrue(same_grounding(a, b, sidecar))
        for field, value in (("event_id", "other"), ("condition", "past"), ("certainty", "uncertain"),
                             ("polarity", "negated"), ("approximate", True), ("evidence", [])):
            self.assertFalse(same_grounding(a, {**b, field: value}, sidecar))
        self.assertFalse(same_grounding(a, b, {"a": "мать", "b": "пациент"}))

    def test_unrelated_properties_and_input_are_preserved(self):
        reg, sidecar = registry_after_first()
        before = copy.deepcopy((reg, sidecar))
        old, new = old_project(reg, sidecar), project(reg, sidecar)
        self.assertEqual(old["sections"], new["sections"])
        self.assertEqual((reg, sidecar), before)


if __name__ == "__main__":
    unittest.main()
