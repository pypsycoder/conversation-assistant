import copy
import json
import unittest
from backend.s_direct_comparison import as_s_source, windows, s_request, apply_s_output, selected_cases
from backend.nightly_research import ROOT, read
from backend import clinical_event_properties_v1 as core
from tests.test_clinical_event_properties_source_v1 import SOURCE, first, wire


class AdapterTests(unittest.TestCase):
    def test_validation_is_separate_and_reserved_final_is_blocked(self):
        self.assertEqual(selected_cases("validation"), ("v01", "v02"))
        self.assertEqual(selected_cases("diagnostic"), ("d01", "d02", "d03"))
        count = 2 + sum(len(windows(as_s_source(read(ROOT / f"examples/nightly-v1/{c}.source.json"))))
                        for c in selected_cases("validation"))
        self.assertEqual(count, 7)
        with self.assertRaises(ValueError):
            selected_cases("final")

    def test_same_text_ids_roles_and_no_future_exposure(self):
        source = read(ROOT / "examples/nightly-v1/d01.source.json")
        converted = as_s_source(source)
        turns = converted["stages"][0]["turns"]
        self.assertEqual(turns, [{k: t[k] for k in ("id", "role", "text")} for t in source["segments"]])
        for i, window in enumerate(windows(converted)):
            self.assertLessEqual(len(window["context_turns"]), 5)
            target = window["target_turn"]["id"]
            pos = next(i for i, t in enumerate(turns) if t["id"] == target)
            self.assertEqual(window["context_turns"], turns[max(0, pos-5):pos])
            payload = s_request(window, core.empty_registry())
            self.assertEqual(json.loads(payload["messages"][1]["content"])["target_turn"]["id"], target)

    def test_existing_S_patch_path_retains_reporter_and_rejects_unknown_evidence(self):
        patch, reporters = first()
        patch["events"] = patch["events"][:1]
        patch["properties"] = patch["properties"][:2]
        raw = wire(patch, reporters)
        source = copy.deepcopy(SOURCE)
        window = {"context_turns": source["stages"][0]["turns"][:1],
                  "target_turn": source["stages"][0]["turns"][1]}
        applied, sidecar = apply_s_output(raw, core.empty_registry(), {}, source, window)
        self.assertTrue(applied["accepted"])
        self.assertEqual(sidecar["p2"], "жена")
        raw["properties"][0]["evidence"] = [{"turn_id": "future"}]
        with self.assertRaises(ValueError):
            apply_s_output(raw, core.empty_registry(), {}, source, window)

    def test_real_or_ambiguous_roles_are_not_silently_accepted(self):
        with self.assertRaises(ValueError):
            as_s_source({"synthetic": False})


if __name__ == "__main__":
    unittest.main()
