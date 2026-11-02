# Классификация и приоритизация расхождений

Каждая находка содержит `taxonomy` — единую классификацию по аспекту контракта,
`priority` — приоритет разбора, и прежнюю детальную категорию `category`.
Старые категории и правила `ignore.category` сохранены.

| Аспект | `taxonomy` | Детальные категории |
|---|---|---|
| Отсутствующий в коде эндпоинт | `missing_endpoint` | `missing_endpoint` |
| Незадокументированный эндпоинт | `undocumented_endpoint` | `ghost_endpoint` |
| Состав path-параметров | `path_parameter` | `parameter_drift` |
| Состав query-параметров | `query_parameter` | `parameter_drift` |
| Состав header-параметров | `header_parameter` | `parameter_drift` |
| Состав cookie-параметров | `cookie_parameter` | `parameter_drift` |
| Схемы, поля, типы, format, enum, тип содержимого запроса | `schema` | `additive_drift`, `destructive_drift`, `type_drift`, расхождение content type |
| Обязательность и nullable | `required_nullable` | `required_drift`, `nullability_drift` |
| Коды ответов | `response_code` | `status_code_drift` |
| Описания и summary | `description` | `description_drift` |
| Примеры | `example` | `example_drift` |
| Ограничение статического анализа | `analysis_limitation` | `analysis_limitation` |

Для любого расхождения параметра `parameter_location` отдельно сохраняет `path`,
`query`, `header` или `cookie`. Например, несовпадение типа query-параметра имеет
`taxonomy=schema`, `category=type_drift`, `parameter_location=query`.
Для остальных находок `parameter_location=null`.
Одинаковые имена параметров из разных мест запроса получают разные расположения
и ID, например `parameters.query.id` и `parameters.header.id`.

## Приоритеты

Существующие уровни серьёзности остаются источником приоритета:

| `severity` | `priority` | Очерёдность |
|---|---|---|
| `error` | `P1` | В первую очередь |
| `warning` | `P2` | Следом за ошибками |
| `info` | `P3` | Информационный разбор |

Результаты сортируются по приоритету, затем по эндпоинту, расположению,
категории и ID. Описания и примеры имеют `info/P3` и сами по себе не приводят
к ненулевому коду завершения с `--exit-code`. Настраиваемая бизнес-оценка
критичности в этой доработке не вводится.

## Описания и примеры

Парсер OpenAPI сохраняет `summary`, `description`, одиночный `example`,
списки примеров схем и именованные `examples` параметров/медиатипов.
AST-анализатор читает литеральные метаданные декораторов, `Query`, `Path`,
`Header`, `Cookie`, `Body`, `Field`, включая `Annotated` и `json_schema_extra`.
У моделей поддержан `model_config` в виде словаря или `ConfigDict` с
литеральным `json_schema_extra`. Docstring обработчика используется как описание,
если в декораторе нет `description`; docstring модели — как описание схемы.
Явный `response_description` сравнивается с описанием соответствующего ответа.

Отсутствующее с одной стороны описание или пример тоже считается расхождением.
Пробельные различия описаний игнорируются; смысловая эквивалентность текста
не оценивается. Примеры сравниваются как JSON: порядок ключей объекта не важен,
порядок элементов массива важен, `false` отличается от `0`. Отсутствующий пример
отличается от явного примера `null`. Имена именованных примеров служат для
стабильного порядка значений; их summary/description отдельно не сравниваются.
Документация параметра берётся с уровня параметра, а при её отсутствии — из его
схемы. Повтор одного описания на обоих уровнях не создаёт дублирующих находок.

Вычисляемые метаданные и примеры с `externalValue` дают `analysis_limitation`
с `requires_review=true`; код приложения не исполняется и внешние URL не загружаются.
Дополнительные ответы FastAPI через `responses`, зависимости, сложные схемы
и прочие прежние ограничения статического анализатора остаются в силе.
Автоматические описания FastAPI, генерируемые из имени функции, не синтезируются.
Поэтому описание, существующее только в OpenAPI, будет отмечено как расхождение.

## Вывод и игнорирование

JSON содержит новые поля каждого элемента и сводки `taxonomy_summary`,
`priority_summary`. Прежняя сводка `summary` сохранена. TUI отображает таксономию
и приоритет рядом с находкой. Формальная схема:
[static-findings.schema.json](static-findings.schema.json).
Версия оболочки находки `schema_version=1.1` сохранена; потребители строгих
списков категорий должны добавить `description_drift` и `example_drift`.

```yaml
ignore:
  - endpoint: "POST /items"
    taxonomy: "description"
  - taxonomy: "example"
```

При одновременном указании `endpoint`, `category` и `taxonomy` правило применяется,
только если совпали все указанные условия.

## Проверка

```powershell
.\.venv\Scripts\python.exe -m pytest tests checks/static_analysis checks/classification -q --basetemp=.venv/classification-tests
```

Проверки новой функции находятся в `checks/classification`: покрыты все группы,
стабильность ID, очерёдность приоритетов, метаданные OpenAPI/AST, отсутствие ложных
различий при совпадении данных, неопределённость, JSON, ignore-правила и CLI.
