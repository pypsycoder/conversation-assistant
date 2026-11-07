import copy
import json
import unittest
from pathlib import Path
from backend import clinical_event_properties_source_print_v2 as old
from backend import clinical_event_properties_source_print_v3 as candidate
from tests.test_clinical_event_properties_source_v1 import registry_after_first

ROOT = Path(__file__).resolve().parents[1]


class SourceBoundaryTests(unittest.TestCase):
    def test_external_marker_rubric_and_verbatim_text_preservation(self):
        corpus = json.loads((ROOT / "examples/source-boundaries-v1.json").read_text(encoding="utf-8"))
        for case in corpus["cases"]:
            with self.subTest(case=case["id"]):
                text, added = candidate.mark(case["text"], case["reported_by"])
                self.assertEqual(added, case["expected_added"])
                self.assertTrue(text.startswith(case["text"]))
                if not added:
                    self.assertEqual(text, case["text"])

    def test_projection_never_mutates_registry_sidecar_or_row_provenance(self):
        registry, sidecar = registry_after_first()
        before = copy.deepcopy((registry, sidecar))
        control, changed = old.project(registry, sidecar), candidate.project(registry, sidecar)
        self.assertEqual((registry, sidecar), before)
        for section, rows in control["evidence"].items():
            for a, b in zip(rows, changed["evidence"][section], strict=True):
                self.assertEqual({k: v for k, v in a.items() if k != "text"},
                                 {k: v for k, v in b.items() if k != "text"})

if __name__ == "__main__":
    unittest.main()
