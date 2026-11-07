"""Print v2 for base S: Russian roles and the stricter «source already named» check (offline)."""
import unittest

from backend import clinical_event_properties_source_print_v2 as P
from tests.test_clinical_event_properties_source_v1 import registry_after_first


class PrintV2Tests(unittest.TestCase):
    def test_english_roles_are_translated_or_neutral(self):
        self.assertEqual(P.mark("Кричит во сне", "wife"), ("Кричит во сне (со слов: жена)", True))
        self.assertEqual(P.mark("Соседка ничего не чувствует", "neighbor_opposite")[0],
                         "Соседка ничего не чувствует (со слов: соседка напротив)")
        self.assertEqual(P.mark("Кричит во сне", "stepfather"), ("Кричит во сне (со слов другого человека)", True))
        self.assertEqual(P.mark("Плохо спит", "patient"), ("Плохо спит", False))

    def test_mention_is_not_a_named_source(self):
        self.assertEqual(P.mark("Раздражается на мужа из-за ерунды", "муж"),
                         ("Раздражается на мужа из-за ерунды (со слов: муж)", True))
        self.assertTrue(P.mark("Муж пробуждается, когда она ходит", "муж")[1])

    def test_reporting_phrases_count_as_named(self):
        for text, who in (("По словам жены, кричит во сне", "жена"), ("Похудела по мнению матери", "мать"),
                          ("Потеря веса по наблюдению матери", "мама"), ("Сестра считает, что похудела", "сестра"),
                          ("Педиатр отметила измученный вид", "педиатр"), ("Мастер: вентиляция в порядке", "мастер"),
                          ("соседка напротив сообщает, что ничего не чувствует", "соседка напротив"),
                          ("Со слов кардиолога, сердце здорово", "cardiologist"),
                          ("Гинеколог на осмотре после родов сказал, что всё в порядке", "гинеколог"),
                          ("Жена говорит, что срывы каждый день", "spouse")):
            self.assertEqual(P.mark(text, who), (text, False), text)

    def test_projection_uses_v2_marks_only_in_print(self):
        reg, sidecar = registry_after_first()
        projection = P.project(reg, {**sidecar, "p2": "wife"})
        self.assertIn("Кричит во сне (со слов: жена)", projection["sections"]["illness_history"])
        self.assertEqual(projection["version"], P.VERSION)


if __name__ == "__main__":
    unittest.main()
