# Conversation Assistant

Исследовательский модуль аккаунта pypsycoder: готовый русский текст беседы →
проверяемые жалобы, анамнез заболевания, анамнез жизни. Отдельный от PSYdraft
репозиторий; его формы и инфраструктура не меняются. ASR сейчас вне задачи.

Начать с [отчёта 08.11.2026](reports/2026-11-08.md),
[методики](CLINICAL_EVALUATION.md), [памяти](RESEARCH_MEMORY.md),
[очереди](NEXT_EXPERIMENTS.md) и [инструкции запуска](docs/NIGHTLY_RUNBOOK.md).

В этой первой публикации отобраны существующий GigaChat-клиент и минимальные
зависимости прямого пути, новая система измерения, синтетический набор и тесты.
Остальная большая локальная исследовательская база не импортирована целиком.
Основа S, её зависимости и парный адаптер теперь импортированы выборочно.
Свежий замер и его ограничения: reports/2026-11-08-cycle-02.md.

Python 3.11+, `pip install -r requirements-research.txt`. Ключ хранится только
в локальном `.env` под одним из имён, поддержанных backend/gigachat.py.
При необходимости явно выполнить `python -m backend.setup_gigachat_ca` для
загрузки публичного CA в проект, без установки в ОС. TLS не отключать.

```powershell
python -m unittest tests.test_nightly_research tests.test_gigachat tests.test_three_sections -q
python -m backend.nightly_research run --output data/nightly/unique-smoke
python -m backend.nightly_research run --output data/nightly/unique-live --live --direct --max-calls 3 --max-tokens 60000 --max-seconds 300
python -m backend.s_direct_comparison --output data/nightly/unique-paired-smoke
python scripts/verify_cycle02.py
```

Синтетика: examples/nightly-v1. Новый runner по умолчанию НЕ вызывает API.
Результаты локально в data/nightly; символ `unique` нужно заменять новым ID.
Анонимизированные синтетические evidence нулевой итерации — reports/evidence/2026-11-08.
`python scripts/review_nightly_baseline.py` воспроизводит исходный подсчёт из них.

Пока это исследовательский прототип, не клинически валидированное приложение.
Правки врача, Session и перенос в PSYdraft не подключены к этому runner.
Прямой baseline v2 не объявляется лучше принятой локальной S. Не считать техническую
валидность JSON и цитат доказательством клинической достоверности.

Ночная локальная автоматизация настроена на 23:00 Europe/Moscow, не переносится
вместе с clone. Компьютер и приложение должны работать. Первое срабатывание ещё
не наблюдалось. Автоматическое слияние в main запрещено.
