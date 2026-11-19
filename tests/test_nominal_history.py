import copy
import unittest
from backend.history_course_repair import repair_history_course
from tests.test_history_course_repair import source, row, result


class NominalHistoryTests(unittest.TestCase):
    def test_isolated_nominal_forms_restore_state_and_recurrence(self):
        for time, noun in (("С ночи","ухудшение состояния"),("Со вчерашнего утра","ухудшение")):
            with self.subTest(time=time,noun=noun):
                quote=f"{time} мне в целом снова хуже."
                original=result([row(f"{time} {noun}.",quote)])
                after,changes,_=repair_history_course(original,source(quote))
                self.assertEqual(after["sections"]["illness_history"],[row(quote)])
                self.assertEqual(len(changes),1)
                self.assertFalse(repair_history_course(after,source(quote))[1])

    def test_improvement_and_independent_symptom_onset_are_preserved(self):
        text="Вчера мне было легче, а с утра мне в целом снова хуже. Боль началась во вторник."
        original=result([row("С утра ухудшение.","а с утра мне в целом снова хуже"),
                         row("Боль началась во вторник.")])
        before=copy.deepcopy(original)
        after,changes,_=repair_history_course(original,source(text))
        self.assertEqual(after["sections"]["illness_history"][0],
                         row("С утра мне в целом снова хуже.","с утра мне в целом снова хуже."))
        self.assertEqual(after["sections"]["illness_history"][1],before["sections"]["illness_history"][1])
        self.assertEqual(original,before)
        self.assertEqual(len(changes),1)

    def test_general_condition_or_uncertainty_is_not_detached(self):
        for text,quote in (
            ("С утра мне в целом снова хуже, если встаю.","С утра мне в целом снова хуже"),
            ("Кажется, с утра мне в целом снова хуже.","с утра мне в целом снова хуже."),
        ):
            original=result([row("С утра ухудшение.",quote)])
            self.assertEqual(repair_history_course(original,source(text))[0],original)

    def test_specific_symptom_treatment_and_qualifiers_are_not_rewritten(self):
        quote="С ночи мне в целом снова хуже."
        for history in ("С ночи ухудшение памяти.","С ночи ухудшение, лекарство не помогло.",
                        "С ночи ухудшение при вставании.","С ночи возможное ухудшение."):
            with self.subTest(history=history):
                original=result([row(history,quote)])
                self.assertEqual(repair_history_course(original,source(quote))[0],original)

    def test_wide_and_multiple_citations_remain_intact(self):
        quote="С утра мне в целом снова хуже."
        text=quote+" Сейчас сильно болит живот."
        wide=result([row("С утра ухудшение.",text)])
        self.assertEqual(repair_history_course(wide,source(text))[0],wide)
        multiple=result([row("С утра ухудшение.",quote)])
        multiple["sections"]["illness_history"][0]["evidence"].append(
            {"segment_id":"s2","quote":"Сейчас сильно болит живот."})
        self.assertEqual(repair_history_course(multiple,source(text))[0],multiple)

    def test_later_retraction_and_duplicate_history_rows_abstain(self):
        quote="С ночи мне в целом снова хуже."
        original=result([row("С ночи ухудшение состояния.",quote)])
        src=source(quote)
        src["segments"].append(dict(id="s4",role="patient",text="Нет. Я ошибся."))
        self.assertEqual(repair_history_course(original,src)[0],original)
        doubled=result([row("С ночи ухудшение.",quote),row("С ночи ухудшение состояния.",quote)])
        self.assertEqual(repair_history_course(doubled,source(quote))[0],doubled)

    def test_unrelated_citation_does_not_block_previous_safe_insertion(self):
        quote="С утра мне в целом снова хуже."
        symptom="Сейчас сильно тошнит."
        original=result([row("С утра ухудшение.",symptom)])
        after,changes,_=repair_history_course(original,source(quote+" "+symptom))
        self.assertEqual(after["sections"]["illness_history"],original["sections"]["illness_history"]+[row(quote)])
        self.assertEqual(changes[0]["action"],"insert")
