import copy
import unittest
from backend.presence_onset_repair import repair_presence_onset
from backend.nightly_research import read
from tests.test_history_course_repair import source, row, result
from scripts.evaluate_presence_onset import evaluate

class PresenceOnsetTests(unittest.TestCase):
    def test_new_semantic_positives_and_negative_boundaries(self):
        report=evaluate(read("examples/presence-onset-v1/offline.json"))
        self.assertEqual(report["semantic_positive_count"],3)
        self.assertEqual(report["boundary_preservation_count"],9)
        self.assertEqual(report["totals"]["control"]["unsupported_atoms"],3)
        self.assertEqual(report["totals"]["candidate"]["unsupported_atoms"],0)

    def test_input_is_immutable_and_second_pass_is_stable(self):
        q="Сейчас сильно болит голова."
        original=result([row("Появление сильной головной боли сейчас.",q)],[row(q)])
        src=source(q); snapshot=copy.deepcopy((original,src))
        after,changes,_=repair_presence_onset(original,src)
        self.assertEqual((original,src),snapshot)
        self.assertEqual(after["sections"]["illness_history"],[row(q)])
        self.assertEqual(after["sections"]["complaints"],original["sections"]["complaints"])
        self.assertTrue(changes)
        self.assertEqual(repair_presence_onset(after,src)[0],after)
        self.assertFalse(repair_presence_onset(after,src)[1])

    def test_other_role_or_multiple_citations_cannot_authorize_repair(self):
        q="Сейчас сильно тошнит."
        original=result([row("Появление сильной тошноты сейчас.",q)])
        for role in ["doctor","relative"]:
            with self.assertRaises(ValueError):repair_presence_onset(original,source(q,role))
        original["sections"]["illness_history"][0]["evidence"]*=2
        self.assertEqual(repair_presence_onset(original,source(q))[0],original)

    def test_repeated_quote_and_mismatching_symptom_do_not_authorize_repair(self):
        q="Сейчас сильно болит живот."
        for text in ["Появление сильной тошноты сейчас.","Впервые появилась сильная боль в животе сейчас."]:
            original=result([row(text,q)])
            self.assertEqual(repair_presence_onset(original,source(q))[0],original)
        original=result([row("Появление сильной боли в животе сейчас.",q)])
        self.assertEqual(repair_presence_onset(original,source(q+" "+q))[0],original)

    def test_real_onset_in_another_utterance_is_preserved(self):
        q="Сейчас сильно тошнит."
        original=result([row("Появление сильной тошноты сейчас.",q)])
        src=source(q)
        src["segments"].append(dict(id="s4",role="patient",text="Это началось только что."))
        self.assertEqual(repair_presence_onset(original,src)[0],original)

    def test_invalid_evidence_and_nonsynthetic_sources_rejected(self):
        q="Сейчас сильно тошнит."
        with self.assertRaises(ValueError):repair_presence_onset(result([row("Появление сильной тошноты сейчас.","Неверная цитата.")]),source(q))
        src=source(q);src["synthetic"]=False
        with self.assertRaises(ValueError):repair_presence_onset(result(),src)
