import copy
import unittest
from backend.history_course_repair import repair_history_course
from tests.test_history_course_repair import source, row, result


class HistoryBoundaryV2Tests(unittest.TestCase):
    def test_long_transition_restores_recurrence(self):
        q="Вчера после ужина мне опять стало в целом хуже."
        original=result([row("Ухудшение началось вчера после ужина.",q)])
        after,changes,_=repair_history_course(original,source(q))
        self.assertEqual(after["sections"]["illness_history"],[row(q)])
        self.assertEqual(len(changes),1)

    def test_leading_conjunction_does_not_convert_state_to_new_onset(self):
        text="В выходные мне было легче, а с ночи мне в целом снова хуже."
        quote="а с ночи мне в целом снова хуже"
        original=result([row("С ночи стало хуже.",quote)])
        after,changes,_=repair_history_course(original,source(text))
        self.assertEqual(after["sections"]["illness_history"],[
            row("С ночи мне в целом снова хуже.","с ночи мне в целом снова хуже.")])
        self.assertEqual(repair_history_course(after,source(text))[1],[])

    def test_condition_belongs_to_explicit_current_symptom(self):
        q="Со вчерашнего вечера мне в целом снова хуже"
        symptom="сейчас сильно кружится голова, если наклоняюсь."
        text=q+", а "+symptom
        original=result([row("Со вчерашнего вечера общее ухудшение.",q),
                         row("Сейчас сильно кружится голова при наклоне.",symptom)],
                        [row(text)])
        snapshot=copy.deepcopy(original)
        after,changes,_=repair_history_course(original,source(text))
        self.assertEqual(after["sections"]["illness_history"][0],row(q+".",q))
        self.assertEqual(after["sections"]["illness_history"][1],original["sections"]["illness_history"][1])
        self.assertEqual(after["sections"]["complaints"],original["sections"]["complaints"])
        self.assertEqual(original,snapshot)
        self.assertEqual(len(changes),1)

    def test_condition_on_general_state_is_not_detached(self):
        for text in (
            "С ночи мне в целом снова хуже, если встаю. Сейчас сильно тошнит.",
            "С ночи мне в целом снова хуже, если встаю, а сейчас сильно тошнит.",
            "С ночи мне в целом снова хуже, сейчас сильно тошнит, если встаю.",
            "С ночи мне в целом снова хуже, а сейчас сильно тошнит, если отцу плохо.",
        ):
            with self.subTest(text=text):
                self.assertEqual(repair_history_course(result(),source(text))[0],result())

    def test_broad_quote_preserves_improvement(self):
        text="Позавчера мне было полегче, а с утра мне в целом снова хуже."
        original=result([row("Позавчера было полегче, с утра стало хуже.",text)])
        self.assertEqual(repair_history_course(original,source(text))[0],original)

    def test_extra_treatment_or_negation_is_not_overwritten(self):
        q="Вчера после обеда мне снова стало хуже в целом."
        for text in ("Ухудшение началось вчера после обеда, лекарство не помогло.",
                     "Вчера после обеда стало хуже, но сегодня не хуже."):
            original=result([row(text,q)])
            self.assertEqual(repair_history_course(original,source(q))[0],original)

    def test_symptom_onset_keeps_its_own_date(self):
        q="С утра мне в целом снова хуже."
        onset="Дрожь началась во вторник."
        text=q+" "+onset
        original=result([row("С утра стало хуже.",q),row(onset)])
        after,_,_=repair_history_course(original,source(text))
        self.assertEqual(after["sections"]["illness_history"],[row(q),row(onset)])

    def test_later_retraction_also_blocks_extended_boundaries(self):
        q="Позавчера после ужина мне опять стало в целом хуже."
        src=source(q)
        src["segments"].append(dict(id="s4",role="patient",text="Нет. Я ошибся."))
        self.assertEqual(repair_history_course(result(),src)[0],result())
