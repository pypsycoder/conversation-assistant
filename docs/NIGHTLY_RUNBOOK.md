# Запуск исследований

Рабочая папка: `D:\PROJECT\Conversation  Assistant` (два пробела).
Python: `.venv\Scripts\python.exe`, jsonschema 4.26.0 уже установлен.
Новый checkout: Python 3.11+, `python -m pip install -r requirements-research.txt`.
Корневой .env остаётся только на машине; используется существующим GigaChatClient.
Публичный CA — по прежнему setup_gigachat_ca, запускается явно, не при импорте.

```powershell
& '.\.venv\Scripts\python.exe' -m unittest tests.test_nightly_research tests.test_gigachat tests.test_three_sections -q
& '.\.venv\Scripts\python.exe' -m backend.nightly_research run --output data/nightly/UNIQUE-smoke
& '.\.venv\Scripts\python.exe' -m backend.nightly_research run --output data/nightly/UNIQUE-live --live --max-calls 3 --max-tokens 60000 --max-seconds 300
```

`--direct` отключает только системный proxy для этого клиента. TLS остаётся включённым.
`--prompt FILE` выбирает кандидат, `--split validation` — проверочный набор.
`--iterations 1..10` повторяет ОДИН зафиксированный кандидат для оценки разброса;
исследовательские итерации с изменением гипотезы выполняет агент отдельными запусками.
Входы не усекать. Итерации по умолчанию 1. Все старые каталоги read-only; output
обязан быть новым. Одновременно работает только один runner (OS file lock).
После краша замок ОС освобождается. Сначала проверить pending attempt без response;
автоматический повтор такой генерации запрещён. При смене ревизии модели — остановка.
Передайте --expected-model-revision с ревизией предыдущего сравнимого запуска, чтобы проверить уже первый ответ каждого варианта.
Время ограничивает старт запросов; один начатый HTTP может длиться ещё до 120 секунд.

Проставить все поля review-template и сохранить как review.json. Затем:

```powershell
& '.\.venv\Scripts\python.exe' -m backend.nightly_research score --gold examples/nightly-v1/d01.gold.json --response data/nightly/RUN/iteration-01/d01/response.json --review data/nightly/RUN/iteration-01/d01/review.json --output data/nightly/RUN/iteration-01/d01/metrics.json
```

Ночной исполнитель — локальная автоматизация Codex, агент читает память, выбирает
узкие эксперименты, вызывает Python, оценивает и пишет reports/YYYY-MM-DD.md.
Запланированная облачная задача ChatGPT сама по себе не получает локальный D:.
Для локальной автоматизации необходимы работающий компьютер, приложение, вход
в аккаунт и доступ в сеть; закрытое окно разговора не является обязательным.
Доступность следующего автономного срабатывания проверяется по фактическому журналу,
а не факту регистрации расписания. Пока не проверено старое «PSYdraft ночной аудит»,
новое расписание держать PAUSED, чтобы не создавать два исследовательских исполнителя.
08.11.2026 пользователь подтвердил отключение старого задания; новая heartbeat
автоматизация `conversation-assistant` создана ACTIVE на 23:00 по Москве и привязана
к текущему чату. Сохранённый automation.toml проверен. Первый heartbeat получен
08.11.2026 в 23:33:36 МСК и обработан: выполнена offline-проверка и подготовлен
пакет врача. Точность старта в 23:00 пока не подтверждена; факт одной регистрации
не является гарантией будущего исполнения. Новых API-генераций в эту ночь нет.
Поддерживаемого инструмента записи утреннего отчёта в обычный ChatGPT-проект в этой
сессии не найдено. Отчёт в Git и ответ автоматизации; не утверждать доставку в ChatGPT.

Публикация: только allowlist кода/синтетики/отчётов. Ни `git add .`, ни загрузки data,
.env, моделей, аудио, сессий и исходных бесед пациентов. Будущие улучшения — branch/PR
в conversation-assistant, никогда auto-merge. psydraft — отдельный потребитель.
