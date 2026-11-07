"""Checks for the new provenance path; no clinical-meaning assertions by string match."""
import copy
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from backend.gigachat import GigaChatClient
from backend.three_sections import SCHEMA, SYSTEM, ROOT, provenance_errors, link_sources


class ThreeSectionsTests(unittest.TestCase):
    def setUp(self):
        self.source = {"id": "synthetic-test", "text_revision": 2, "timing_origin": "manual", "segments": [
            {"id": "s1", "role": "doctor", "start": 0, "end": 2, "text": "Плохо спите?"},
            {"id": "s2", "role": "patient", "start": 3, "end": 5, "text": "Да, плохо сплю."}]}
        self.result = {"sections": {"complaints": [{"text": "Плохо спит.", "evidence": [{"segment_id": "s2", "quote": "плохо сплю"}]}],
                                    "illness_history": [], "life_history": []}, "gaps": []}

    def test_links_actual_role_time_revision_without_mutating_model_output(self):
        before = copy.deepcopy(self.result)
        linked = link_sources(self.result, self.source)
        e = linked["result"]["sections"]["complaints"][0]["evidence"][0]
        self.assertEqual((e["text_revision"], e["role"], e["start"], e["end"]), (2, "patient", 3, 5))
        self.assertEqual(self.result, before)

    def test_invented_quote_or_id_is_rejected(self):
        for field, value in [("quote", "сплю семь часов"), ("segment_id", "absent")]:
            candidate = copy.deepcopy(self.result)
            candidate["sections"]["complaints"][0]["evidence"][0][field] = value
            self.assertTrue(provenance_errors(candidate, self.source))
            with self.assertRaises(ValueError):
                link_sources(candidate, self.source)

    def test_doctor_question_alone_is_not_patient_support(self):
        self.result["sections"]["complaints"][0]["evidence"] = [{"segment_id": "s1", "quote": "Плохо спите?"}]
        self.assertTrue(provenance_errors(self.result, self.source))

    def test_unknown_answer_requires_provenance(self):
        self.result["gaps"] = [{"topic": "Вес", "status": "patient_does_not_know", "evidence": []}]
        self.assertTrue(provenance_errors(self.result, self.source))

    def test_new_schema_is_used_and_truncation_not_accepted(self):
        with tempfile.TemporaryDirectory() as folder:
            env = Path(folder) / ".env"
            env.write_text("GIGACHAT_KEY_L1=fake-key", encoding="utf-8")
            client = GigaChatClient(env)
            client.model, client._token, client._expires_at = "GigaChat-3-Ultra", "fake-token", time.time() + 1000
            raw = {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(self.result)}}]}
            with patch.object(client, "_request", return_value=raw):
                output = client.generate_structured(SYSTEM, {"segments": self.source["segments"]}, SCHEMA)
            self.assertEqual(output["validation_errors"], [])
            self.assertEqual(output["request"]["response_format"]["schema"], SCHEMA)
            self.assertNotIn("fake-", json.dumps(output))
            raw["choices"][0]["finish_reason"] = "length"
            with patch.object(client, "_request", return_value=raw):
                output = client.generate_structured(SYSTEM, {}, SCHEMA)
            self.assertIsNone(output["parsed"])
            self.assertTrue(output["validation_errors"])


if __name__ == "__main__":
    unittest.main()
