import unittest
from backend.paired_clinical_review import evaluate


class PairedReviewTests(unittest.TestCase):
    def test_one_criterion_may_be_fully_covered_by_multiple_atomic_rows(self):
        gold = {"facts": [{"id": "f1", "required_sections": ["illness_history"]}]}
        result = {"sections": {"complaints": [], "illness_history": [{"text": "Доза"}, {"text": "Длительность"}], "life_history": []}}
        review = {"reviewer": "fixture", "criteria": [{"id": "f1", "status": "full",
            "rows": ["illness_history:0", "illness_history:1"], "complete_sections": ["illness_history"],
            "present_sections": ["illness_history"], "reason": "Dose and duration preserved across two rows"}],
            "rows": [{"id": f"illness_history:{i}", "support": "supported", "inventions": [], "reason": "supported"}
                     for i in range(2)], "inventions": []}
        metrics = evaluate(gold, result, review)
        self.assertEqual((metrics["tp"], metrics["fp"], metrics["complete_required_placements"]), (1, 0, 1))
        with self.assertRaises(ValueError):
            evaluate(gold, result, {**review, "rows": review["rows"][:1]})

    def test_invention_repeated_across_sections_is_one_semantic_claim(self):
        result = {"sections": {"complaints": [{}], "illness_history": [{}], "life_history": []}}
        review = {"reviewer": "fixture", "criteria": [],
            "rows": [{"id": f"{s}:0", "support": "unsupported", "inventions": ["x"], "reason": "invented"}
                     for s in ("complaints", "illness_history")], "inventions": [{"id": "x", "reason": "no source"}]}
        metrics = evaluate({"facts": []}, result, review)
        self.assertEqual((metrics["unsupported_unique"], metrics["unsupported_rows"]), (1, 2))


if __name__ == "__main__":
    unittest.main()
