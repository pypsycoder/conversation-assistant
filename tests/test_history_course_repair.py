import copy
import unittest
from backend.history_course_repair import repair_history_course, source_candidates


def source(text, role="patient"):
    return {"synthetic": True, "segments": [{"id": "s2", "role": role, "text": text}]}


def row(text, quote=None):
    return {"text": text, "evidence": [{"segment_id": "s2", "quote": quote or text}]}


def result(history=(), complaints=()):
    return {"sections": {"complaints": list(complaints), "illness_history": list(history),
                         "life_history": []}, "gaps": []}


class HistoryCourseRepairTests(unittest.TestCase):
    def test_replace_lost_recurrence_and_invented_transition(self):
        quote="С ночи мне в целом снова хуже."
        original=result([row("С ночи состояние ухудшилось.", quote)], [row("Сейчас сильно болит горло.")])
        src=source(quote+" Сейчас сильно болит горло.")
        snapshot=copy.deepcopy((original,src))
        after,changes,_=repair_history_course(original,src)
        self.assertEqual(after["sections"]["illness_history"],[row(quote)])
        self.assertEqual((original,src),snapshot)
        self.assertEqual(after["sections"]["complaints"],original["sections"]["complaints"])
        self.assertEqual(len(changes),1)
        self.assertEqual(repair_history_course(after,src)[1],[])

    def test_missing_course_after_improvement(self):
        src=source("Вчера мне было легче, а сегодня мне в целом снова хуже.")
        after,changes,_=repair_history_course(result(),src)
        self.assertEqual(after["sections"]["illness_history"][0],
                         row("Сегодня мне в целом снова хуже.","сегодня мне в целом снова хуже."))
        self.assertEqual(changes[0]["action"],"insert")

    def test_mixed_symptom_row_is_preserved(self):
        text="С вечера мне в целом снова хуже. Сейчас сильно болит живот."
        original=result([row("Ухудшение началось с вечера, сейчас болит живот.",text)])
        after,changes,abstentions=repair_history_course(original,source(text))
        self.assertEqual(after,original)
        self.assertFalse(changes)
        self.assertEqual(abstentions[0]["reason"],"mixed_or_unrecognized_history_row")

    def test_safe_mixed_source_preserves_current_symptom(self):
        text="С утра мне в целом снова хуже, а сейчас сильно тошнит."
        src=source(text)
        original=result([row("С утра общее ухудшение.","С утра мне в целом снова хуже")],
                        [row(text)])
        after,changes,_=repair_history_course(original,src)
        self.assertEqual(after["sections"]["illness_history"],[
            row("С утра мне в целом снова хуже.","С утра мне в целом снова хуже")])
        self.assertEqual(after["sections"]["complaints"],original["sections"]["complaints"])
        self.assertEqual(len(changes),1)

    def test_conditions_negation_uncertainty_and_other_subject_abstain(self):
        for text in (
            "С утра мне в целом хуже, если встаю.",
            "Не могу сказать, что с утра мне в целом снова хуже.",
            "Кажется, с утра мне в целом снова хуже.",
            "С утра мне в целом снова хуже, а сейчас сильно тошнит при наклоне.",
            "С утра в целом снова хуже.",
            "Мать сказала: «С утра мне в целом снова хуже».",
        ):
            with self.subTest(text=text):
                self.assertEqual(repair_history_course(result(),source(text))[0],result())

    def test_doctor_and_real_data_not_used(self):
        self.assertFalse(source_candidates(source("Сегодня мне в целом хуже.","doctor")))
        with self.assertRaises(ValueError):
            repair_history_course(result(),{"synthetic":False,"segments":[]})

    def test_repeated_course_across_utterances_abstains(self):
        src=source("Сегодня мне в целом хуже.")
        src["segments"].append({"id":"s4","role":"patient","text":"Сегодня мне в целом снова хуже."})
        after,changes,abstentions=repair_history_course(result(),src)
        self.assertEqual(after,result())
        self.assertFalse(changes)
        self.assertEqual(len(abstentions),2)

    def test_invalid_provenance_and_duplicate_ids_rejected(self):
        src=source("Сегодня мне в целом хуже.")
        with self.assertRaises(ValueError):
            repair_history_course(result([row("С ночи мне в целом хуже.")]),src)
        src["segments"].append(src["segments"][0])
        with self.assertRaises(ValueError):
            repair_history_course(result(),src)

    def test_other_time_and_negative_course_remain(self):
        src=source("Хуже стало в пятницу. Сегодня мне в целом снова хуже. Сегодня сильнее не стало.")
        original=result([row("Хуже стало в пятницу."),row("Сегодня сильнее не стало.")])
        after,changes,_=repair_history_course(original,src)
        self.assertEqual(after["sections"]["illness_history"][:2],original["sections"]["illness_history"])
        self.assertEqual(changes[0]["action"],"insert")

    def test_multiple_citations_and_extra_meaning_are_not_overwritten(self):
        quote="С утра мне в целом снова хуже."
        src=source(quote+" Лекарство не помогло.")
        original=result([row("С утра состояние ухудшилось, лекарство не помогло.",quote)])
        self.assertEqual(repair_history_course(original,src)[0],original)

    def test_later_retraction_does_not_reintroduce_old_course(self):
        src=source("С утра мне в целом снова хуже.")
        src["segments"].append({"id":"s4","role":"patient","text":"Нет, я ошибся. С утра мне не хуже."})
        original=result([{"text":"С утра мне не хуже.","evidence":[{"segment_id":"s4","quote":"С утра мне не хуже."}]}])
        self.assertEqual(repair_history_course(original,src)[0],original)
        self.assertFalse(repair_history_course(original,src)[1])
