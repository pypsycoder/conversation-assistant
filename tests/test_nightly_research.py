import tempfile
import unittest
from pathlib import Path
from backend.nightly_research import score, exclusive_lock


class ResearchTests(unittest.TestCase):
    def review(self, rows):
        return {"reviewer": "unit fixture", "rows": rows}

    def row(self, rid, ids=(), unsupported=0, partial=()):
        return dict(row_id=rid, complete_fact_ids=list(ids), partial_fact_ids=list(partial),
                    unsupported_atoms=unsupported, polarity_errors=0, temporal_errors=0, source_errors=0)

    def test_missing_and_unsupported_fact_change_both_precision_and_recall(self):
        gold = {"facts": [{"id": "a", "required_sections": ["complaints"]},
                          {"id": "b", "required_sections": ["life_history"]}]}
        result = {"sections": {"complaints": [{}, {}], "illness_history": [], "life_history": []}}
        m = score(gold, result, self.review([self.row("complaints:0", ["a"]), self.row("complaints:1", unsupported=1)]))
        self.assertEqual((m["tp"], m["fp"], m["fn"]), (1, 1, 1))
        self.assertEqual((m["precision"], m["recall"], m["f1"]), (.5, .5, .5))

    def test_repeated_placements_do_not_inflate_recall(self):
        gold = {"facts": [{"id": "a", "required_sections": ["complaints", "illness_history"]}]}
        result = {"sections": {"complaints": [{}, {}], "illness_history": [{}], "life_history": []}}
        m = score(gold, result, self.review([self.row("complaints:0", ["a"]), self.row("complaints:1", ["a"]), self.row("illness_history:0", ["a"])]))
        self.assertEqual((m["tp"], m["covered_placements"], m["duplicate_placements"]), (1, 2, 1))

    def test_incomplete_review_cannot_produce_metrics(self):
        with self.assertRaises(ValueError):
            score({"facts": []}, {"sections": {"complaints": [{}], "illness_history": [], "life_history": []}}, self.review([]))

    def test_partial_fact_is_not_complete_recall(self):
        gold = {"facts": [{"id": "a", "required_sections": ["complaints"]}]}
        result = {"sections": {"complaints": [{}], "illness_history": [], "life_history": []}}
        m = score(gold, result, self.review([self.row("complaints:0", partial=["a"])]))
        self.assertEqual((m["tp"], m["fp"], m["fn"]), (0, 1, 1))

    def test_second_process_lock_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "lock"
            with exclusive_lock(path):
                with self.assertRaises(OSError):
                    with exclusive_lock(path):
                        self.fail("concurrent lock acquired")
            with exclusive_lock(path):
                pass


if __name__ == "__main__":
    unittest.main()
