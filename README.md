# qa-agent-workflow

Контролируемый QA workflow для подготовки требований, Jira-задач и тестовой модели Qase. Процесс выполняет `qa-orchestrator`, а содержательные этапы делегируются специализированным агентам. Формальные правила находятся в [AGENTS.md](AGENTS.md).

Проект предназначен для пилотного командного использования с ручным решением Quality Gates. Локальный валидатор проверяет структуру и согласованность состояния; он не подтверждает содержание требований, внешние GET или успешность продукта.

## Workflow

```text
Подтверждённый источник
  → Requirement Review → Gate #1
  → Jira Task Creator   → Gate #2
  → Qase Model Designer → Gate #3
  → completed
```

Переход разрешён только после `PASS` предыдущего Gate. `FAIL` или `BLOCKED` останавливает продвижение и требует решения владельца соответствующего finding.

| Этап | Артефакт | Проверка Gate |
|---|---|---|
| Requirement Review | `artifacts/requirement-review.md` | FR/BR/AC/Constraints, ambiguity, gaps, contradictions, traceability, готовность требований |
| Jira | `artifacts/jira-tasks.md` | mapping каждого FR, полный duplicate check, тип/priority, Jira GET и отсутствие обязательных ошибок |
| Qase | `artifacts/qase-test-model.md` | Jira/Qase mapping, существующие suites, данные, наблюдаемость, воспроизводимость, 100% покрытие обязательных требований |

Покрытие моделью не означает выполнение тестов. GET подтверждает сохранённое содержание сущности, но не заменяет содержательную проверку.

## Ответственность

- `qa-orchestrator` владеет state, audit log и решениями Gate.
- `product-owner` разрешает неоднозначности требований и бизнес-правила.
- `qa-lead` подтверждает тестируемость, данные, наблюдаемость и достаточность покрытия.
- Jira/Qase owners подтверждают проект, тип, priority и target suite.

Для каждого Gate и каждого blocking finding в state фиксируются `owner`, `reviewer`, `decision_at` и `evidence_refs`. Неопределённый результат внешней операции не считается успехом.

## Артефакты и состояние

```text
AGENTS.md                              Контракт процесса и критерии Gate
.opencode/agent/                       Роли оркестратора и сабагентов
.opencode/skills/                      Методики review, task-design и test-design
.opencode/tools/validate-workflow.mjs  Структурный валидатор и self-test
artifacts/requirement-review.md        Requirement Review и Gate #1
artifacts/jira-tasks.md                Jira mapping, duplicate check и GET
artifacts/qase-test-model.md           Qase model, coverage и Gate #3
artifacts/audit-log.md                 История значимых действий
artifacts/workflow-state.json          Единственный источник текущего state и next_stage
```

`run_type` различает `product`, `resume`, `audit` и `maintenance`. Технический аудит и обслуживание процесса не должны маскироваться под продуктовый запуск. Исторические PASS не являются активным входом нового запуска.

## Подготовка

1. Откройте проект из корня в OpenCode и убедитесь, что доступны оркестратор, три сабагента и skills.
2. Установите зависимости для инструмента чтения Confluence:

   ```sh
   npm --prefix .opencode install
   ```

3. Подключите Jira и Qase в окружении OpenCode. Credentials не хранятся в репозитории.
4. До внешнего создания подтвердите источник требований, Jira project, тип и priority, Qase project и уже существующую target suite.

Для Confluence используются `CONFLUENCE_URL`, `CONFLUENCE_EMAIL` и `CONFLUENCE_API_TOKEN`. Реальные значения нельзя записывать в README, артефакты или Git.

## Первый запуск

Передайте оркестратору однозначный источник и контекст:

```text
Выполни QA workflow по AGENTS.md.
Источник: Confluence pageId=<PAGE_ID>, версия=<VERSION>.
Scope: <ФУНКЦИОНАЛЬНОСТЬ>.
Jira project: <PROJECT_KEY>.
Jira type и priority: <ПОДТВЕРЖДЁННЫЕ ЗНАЧЕНИЯ>.
Qase project: <PROJECT_CODE>, target suite: <SUITE_ID>.

Сначала прочитай существующие артефакты и подтверди актуальность источника.
Выполняй этапы последовательно. Создавай только отсутствующие сущности после полного duplicate check.
Существующие Jira-задачи, Qase-тесты и suites не изменяй.
```

Для локального review явно ограничьте запрос этапом Requirement Review и Gate #1.

## Resume и ошибки

- Перед resume повторно сверяются identity, версия и точное содержание источника; при невозможности подтвердить актуальность workflow блокируется.
- Новый resume создаёт датированный активный раздел с новым `run_id`; история не перезаписывается.
- Изменение требований требует impact analysis для Jira и Qase. Новая версия не является основанием создавать копии.
- Duplicate check охватывает все страницы результатов; совпадения подтверждаются через GET и сравнением содержания.
- Retryable read/search/GET ошибки повторяются до трёх раз после исходной попытки. Ошибки авторизации и non-retryable ошибки не повторяются.
- После timeout создания сначала выполняются поиск и GET; автоматическое повторное создание запрещено.
- Каждый нерешённый блокирующий finding сохраняется в `blocking_findings` и останавливает продвижение. Неблокирующие замечания сохраняются в артефакте review.

## Проверки

Перед каждым разрешённым переходом запускайте:

```sh
npm --prefix .opencode run validate-workflow
```

Для регрессионной проверки валидатора:

```sh
npm --prefix .opencode run test:workflow
```

Валидатор сверяет owner, reviewer, время решения и набор evidence refs между state и активным артефактом, проверяет локальные файлы и явные якоря свидетельств. Неверные типы входных данных возвращаются как ошибки проверки. HTTP(S)-ссылки не открываются.

`PASS` валидатора означает только структурную согласованность. Решение Gate принимает оркестратор после проверки содержания и evidence.

## Текущее состояние

Текущий вход `20260910-user-input-016` — точный текст «Регистрация пользователя», переданный пользователем. Снимок и SHA-256 подтверждены для user_text; версия страницы Confluence неизвестна. SRC-1 закрыт для этого входа. Gates нового входа NOT_RUN, next_stage=requirements_clarification: ожидается ответ по AMB-3 (исчезнувшие * в regex); AMB-1/AMB-2 и LR-1…LR-5 сохраняются для повторной оценки. Jira и Qase не изменялись.

Подробные причины и evidence находятся в [audit-log.md](artifacts/audit-log.md), а актуальные указатели — в [workflow-state.json](artifacts/workflow-state.json).

Полный контракт, критерии Gate и правила эскалации описаны в [AGENTS.md](AGENTS.md).


## Воспроизводимый вход

Снимок хранится в `artifacts/requirement-review.md` под отдельным заголовком `##` и явным якорем. `source.input_ref` указывает на него; это отдельный указатель от `active_artifacts.requirement_review`. Формат `workflow-input-v1` и точный алгоритм состава описаны в AGENTS.md. JSON сохраняет исходные переводы строк, пробелы и текст уточнений без изменения оригинала.

Для пересчёта хеша текущего снимка:

```sh
npm --prefix .opencode run validate-workflow -- --source-hash
```

Для независимого пересчёта сохранённой архивной копии (не подтверждает актуальность):

```sh
npm --prefix .opencode run validate-workflow -- --source-hash artifacts/requirement-review.md#archived-input-20260910-015
```

Для сравнения текущего снимка с предыдущим передайте его реальный указатель:

```sh
npm --prefix .opencode run validate-workflow -- --compare-input artifacts/requirement-review.md#previous-input-anchor
```

`previous-input-anchor` — шаблон: замените существующим якорем предыдущего подтверждённого снимка. Команда показывает изменения источника, версии, оригинала, уточнений и хешей; ничего не записывает. Текущий снимок user_text подтверждён; сравнение с архивом не подтверждает его эквивалентность актуальной странице Confluence. Новый текст/уточнения требуют новой оценки по RESUME; автоматически подтверждать источник или переписывать прежний хеш нельзя.
