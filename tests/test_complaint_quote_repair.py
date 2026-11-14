import unittest

from backend.complaint_quote_repair import repair_complaints


class ComplaintQuoteRepairTests(unittest.TestCase):
    def test_clause_after_earlier_improvement_keeps_history(self):
        quote = "сегодня мне в целом снова хуже."
        row = {"text": quote.capitalize(), "evidence": [{"segment_id": "s2", "quote": quote}]}
        result = {"sections": {"complaints": [row], "illness_history": [row], "life_history": []}, "gaps": []}
        source = {"synthetic": True, "segments": [
            {"id": "s2", "role": "patient", "text": f"Позавчера мне было лучше, а {quote}"},
        ]}
        edited, changes = repair_complaints(result, source)
        self.assertEqual(edited["sections"]["complaints"], [])
        self.assertEqual(edited["sections"]["illness_history"], [row])
        self.assertEqual(changes[0]["original"], row)

    def test_quote_inside_qualifier_does_not_authorize_removal(self):
        quote = "сегодня мне в целом хуже"
        row = {"text": quote.capitalize() + ".", "evidence": [{"segment_id": "s2", "quote": quote}]}
        result = {"sections": {"complaints": [row], "illness_history": [row], "life_history": []}, "gaps": []}
        for text in (f"Не могу сказать, что {quote}.", f"Вчера было лучше, а {quote}, если встаю."):
            with self.subTest(text=text):
                source = {"synthetic": True, "segments": [{"id": "s2", "role": "patient", "text": text}]}
                self.assertEqual(repair_complaints(result, source), (result, []))

    def test_state_at_a_time_is_not_replaced_by_a_change_at_that_time(self):
        quote = "Вчера мне в целом хуже, и сейчас болит горло."
        source = {"synthetic": True, "segments": [{
            "id": "s2",
            "role": "patient",
            "text": f"Позавчера мне стало хуже. {quote} С позавчера хуже не становилось.",
        }]}
        original = {"sections": {
            "complaints": [{"text": quote, "evidence": [{"segment_id": "s2", "quote": quote}]}],
            "illness_history": [{
                "text": "Вчера стало хуже в целом.",
                "evidence": [{"segment_id": "s2", "quote": "Вчера мне в целом хуже"}],
            }],
            "life_history": [],
        }, "gaps": []}
        self.assertEqual(repair_complaints(original, source), (original, []))
