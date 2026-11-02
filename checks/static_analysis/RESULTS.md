# Результаты доработки пункта 1

Выполнены семь согласованных шагов: исходная проверка, примеры ошибок, расширение
маршрутов, параметры и обязательность, явная неопределённость, описание выходного
контракта и документация с покрытием. Это статический анализ распространённых
конструкций FastAPI, с явно перечисленными ограничениями в `docs/STATIC_ANALYSIS.md`.

## Проверки

- Исходный набор до изменений: **25 passed**.
- После всех изменений: **94 passed**, код возврата 0.
- Состав: 25 прежних тестов и 69 новых проверок в `checks/static_analysis`.
- Команда: `python -m pytest tests checks/static_analysis -q -p no:cacheprovider`.
- Проверены параметры, модели, nullable/required, aliases, маршруты, рекурсия,
  зависимости, неизвестные схемы, JSON Schema формата находок и запрет выдачи
  LLM-патчей для диагностических находок.
- Отдельный запуск CLI на `examples/app.py` и `examples/openapi.yaml` завершился
  успешно и выдал ровно три ожидаемые категории: `required_drift`,
  `nullability_drift`, `analysis_limitation`.
- `git diff --check` прошёл.
- Все 28 файлов в `tests`, `.gitignore` и `simple_report.json` сохранены:
  количество файлов и SHA-256 совпали с исходным снимком.

## Покрытие исполняемых строк

| Область | Покрыто / всего | Покрытие |
|---|---:|---:|
| Весь `src/drift_agent` | 1414 / 2121 | 66,7% |
| `code_analyzer` | 499 / 593 | 84,1% |
| `spec_parser` | 193 / 229 | 84,3% |
| `diff_engine` | 132 / 144 | 91,7% |

Исходное покрытие всего проекта составляло 1195 / 1934 = 61,8%.
Проценты измеряют выполнение строк, а не полноту требований или точность на
реальных сервисах. Старый и новый наборы различаются по числу тестов и объёму кода.
Общий показатель включает CLI, LLM и другие модули вне основной доработки.

Окружение: Windows, Python 3.12.14, pytest 8.4.2, coverage 7.16.2.
Используется отдельное окружение `.venv`, зависимости установлены из `.[dev]`.
Новые зависимости в `pyproject.toml` не добавлялись.

## Воспроизведение покрытия

Из корня проекта после установки зависимостей:

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
.\.venv\Scripts\python.exe -m coverage run --data-file=.venv/final-coverage-data --source=src/drift_agent -m pytest tests checks/static_analysis -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m coverage report --data-file=.venv/final-coverage-data
.\.venv\Scripts\python.exe -m coverage json --data-file=.venv/final-coverage-data -o .venv/final-coverage-report.json
```

Финальный лог текущего запуска: `.venv/final-tests.txt`; машиночитаемое покрытие:
`.venv/final-coverage-report.json`; демонстрационный результат: `.venv/static-demo.json`.
Эти локальные файлы не предназначены для включения в Git. В репозитории остаётся
настоящий отчёт и воспроизводимые проверки.

## Передача команде

Выходные находки сохраняют старые поля, но добавляют `schema_version`, `source_kind`,
`source_file`, `source_line`, `requires_review`. Новая категория `analysis_limitation`
информационная и требует ревью; её нельзя считать подтверждённым расхождением.
Участникам нужно учесть это в строгих enum-схемах и при подсчёте ошибок.
JSON Schema элемента находки: `docs/static-findings.schema.json`.

Веб-интерфейс, экспорт после ревью, CI и общий испытательный стенд не изменялись.
Динамический анализ и объединённый классификатор остаются отдельными частями проекта.
