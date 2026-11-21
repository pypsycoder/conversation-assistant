import copy
import unittest
from backend.history_course_repair import repair_history_course, repair_adjectival_history
from tests.test_history_course_repair import source, row, result


class AdjectivalHistoryTests(unittest.TestCase):
    def test_adjectival_rows_restore_literal_period_and_recurrence(self):
        for time, adjective in (("С утра","Утреннее"),("С вечера","Вечернее"),("С ночи","Ночное")):
            quote=f"{time} мне в целом снова хуже."
            original=result([row(adjective+" ухудшение состояния.",quote)])
            after,changes,_=repair_adjectival_history(original,source(quote))
            self.assertEqual(after["sections"]["illness_history"],[row(quote)])
            self.assertEqual(len(changes),1)
            self.assertFalse(repair_adjectival_history(after,source(quote))[1])

    def test_reverse_candidate_is_not_mixed_into_adjective_candidate(self):
        quote="С вечера мне в целом снова хуже."
        original=result([row("Ухудшение состояния с вечера.",quote)])
        self.assertEqual(repair_adjectival_history(original,source(quote))[0],original)
        self.assertTrue(repair_history_course(original,source(quote))[1])

    def test_symptom_onset_and_improvement_remain(self):
        im="Вчера мне было легче";quote="с ночи мне в целом снова хуже."
        onset="Тошнота началась в пятницу утром."
        original=result([row(im+".",im),row("Ночное ухудшение.","а "+quote.removesuffix(".")),row(onset)])
        snapshot=copy.deepcopy(original)
        after,changes,_=repair_adjectival_history(original,source(im+", а "+quote+" "+onset))
        self.assertEqual(original,snapshot)
        self.assertEqual(after["sections"]["illness_history"],[snapshot["sections"]["illness_history"][0],
                         row("С ночи мне в целом снова хуже.",quote),snapshot["sections"]["illness_history"][2]])
        self.assertEqual(len(changes),1)

    def test_condition_and_uncertainty_in_source_are_not_detached(self):
        for text,quote in (("С утра мне в целом снова хуже, если встаю.","С утра мне в целом снова хуже"),
                           ("Кажется, с утра мне в целом снова хуже.","с утра мне в целом снова хуже.")):
            original=result([row("Утреннее ухудшение.",quote)])
            self.assertEqual(repair_adjectival_history(original,source(text))[0],original)

    def test_extra_meanings_and_uncertainty_in_row_abstain(self):
        quote="С утра мне в целом снова хуже."
        for text in ("Утреннее ухудшение памяти.","Утреннее выраженное ухудшение состояния.",
                     "Возможно утреннее ухудшение.","Утреннее ухудшение при вставании.",
                     "Утреннее ухудшение, лекарство не помогло."):
            original=result([row(text,quote)])
            self.assertEqual(repair_adjectival_history(original,source(quote))[0],original)

    def test_wide_multiple_and_retracted_citations_abstain(self):
        quote="С утра мне в целом снова хуже.";sym="Сейчас сильно болит горло."
        src=source(quote+" "+sym)
        wide=result([row("Утреннее ухудшение.",quote+" "+sym)])
        self.assertEqual(repair_adjectival_history(wide,src)[0],wide)
        multiple=result([row("Утреннее ухудшение.",quote)])
        multiple["sections"]["illness_history"][0]["evidence"].append({"segment_id":"s2","quote":sym})
        self.assertEqual(repair_adjectival_history(multiple,src)[0],multiple)
        src["segments"].append(dict(id="s4",role="patient",text="Нет. Я ошибся."))
        original=result([row("Утреннее ухудшение.",quote)])
        self.assertEqual(repair_adjectival_history(original,src)[0],original)

    def test_unrelated_citation_does_not_block_previous_insertion(self):
        quote="С утра мне в целом снова хуже.";sym="Сейчас сильно тошнит."
        original=result([row("Утреннее ухудшение.",sym)])
        after,changes,_=repair_adjectival_history(original,source(quote+" "+sym))
        self.assertEqual(after["sections"]["illness_history"],original["sections"]["illness_history"]+[row(quote)])
        self.assertEqual(changes[0]["action"],"insert")
