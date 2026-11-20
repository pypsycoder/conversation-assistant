import copy
import unittest
from backend.history_course_repair import repair_history_course
from tests.test_history_course_repair import source, row, result


class ReversedNominalTests(unittest.TestCase):
    def test_trailing_time_forms_restore_recurrence(self):
        for history in ("Ухудшение состояния с вечера.","Ухудшение с вечера.","Общее ухудшение с вечера."):
            quote="С вечера мне в целом снова хуже."
            after,changes,_=repair_history_course(result([row(history,quote)]),source(quote))
            self.assertEqual(after["sections"]["illness_history"],[row(quote)])
            self.assertEqual(len(changes),1)
            self.assertFalse(repair_history_course(after,source(quote))[1])

    def test_source_time_replaces_wrong_course_time_not_symptom_date(self):
        quote="С ночи мне в целом снова хуже."
        onset="Боль началась в понедельник."
        original=result([row("Ухудшение с утра.",quote),row(onset)])
        before=copy.deepcopy(original)
        after,changes,_=repair_history_course(original,source(quote+" "+onset))
        self.assertEqual(after["sections"]["illness_history"],[row(quote),row(onset)])
        self.assertEqual(original,before)
        self.assertEqual(len(changes),1)

    def test_contrast_quote_keeps_earlier_improvement(self):
        im="Позавчера мне было легче"
        quote="с утра мне в целом снова хуже."
        original=result([row(im+".",im),row("Ухудшение состояния с утра.","а "+quote.removesuffix("."))])
        after,changes,_=repair_history_course(original,source(im+", а "+quote))
        self.assertEqual(after["sections"]["illness_history"][0],original["sections"]["illness_history"][0])
        self.assertEqual(after["sections"]["illness_history"][1],row("С утра мне в целом снова хуже.",quote))
        self.assertEqual(len(changes),1)

    def test_specific_mixed_or_uncertain_rows_abstain(self):
        quote="С вечера мне в целом снова хуже."
        for history in ("Ухудшение памяти с вечера.","Ухудшение тошноты с вечера.",
                        "Ухудшение с вечера, лекарство не помогло.","Ухудшение с вечера при вставании.",
                        "Возможно ухудшение с вечера."):
            original=result([row(history,quote)])
            self.assertEqual(repair_history_course(original,source(quote))[0],original)

    def test_general_condition_and_source_uncertainty_remain(self):
        for text,quote in (
            ("С утра мне в целом снова хуже, если наклоняюсь.","С утра мне в целом снова хуже"),
            ("Кажется, с утра мне в целом снова хуже.","с утра мне в целом снова хуже."),
        ):
            original=result([row("Ухудшение с утра.",quote)])
            self.assertEqual(repair_history_course(original,source(text))[0],original)

    def test_weak_unrelated_citation_does_not_block_old_insertion(self):
        quote="С утра мне в целом снова хуже.";symptom="Сейчас сильно болит живот."
        original=result([row("Ухудшение с утра.",symptom)])
        after,changes,_=repair_history_course(original,source(quote+" "+symptom))
        self.assertEqual(after["sections"]["illness_history"],original["sections"]["illness_history"]+[row(quote)])
        self.assertEqual(changes[0]["action"],"insert")

    def test_wide_multiple_and_retracted_evidence_abstain(self):
        quote="С утра мне в целом снова хуже.";symptom="Сейчас сильно тошнит."
        src=source(quote+" "+symptom)
        wide=result([row("Ухудшение с утра.",quote+" "+symptom)])
        self.assertEqual(repair_history_course(wide,src)[0],wide)
        multiple=result([row("Ухудшение с утра.",quote)])
        multiple["sections"]["illness_history"][0]["evidence"].append({"segment_id":"s2","quote":symptom})
        self.assertEqual(repair_history_course(multiple,src)[0],multiple)
        src["segments"].append(dict(id="s4",role="patient",text="Нет. Я ошибся."))
        original=result([row("Ухудшение с утра.",quote)])
        self.assertEqual(repair_history_course(original,src)[0],original)
