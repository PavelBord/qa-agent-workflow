QA Agent Workflow и Golden Dataset

Проект демонстрирует управляемый QA-процесс для анализа требований из Confluence и подготовки тестовой модели. QA Agent получает подтверждённые требования, классифицирует их, строит позитивные, негативные и граничные сценарии, фиксирует неоднозначности и передаёт результат независимому Evaluator.

Основной пример — страница Confluence **Password** (`pageId=1376257`) с требованиями к восстановлению пароля.

## Архитектура

```text
Confluence → QA Agent → Requirement Review и тест-кейсы → LLM-as-a-Judge → Quality Gate
```

Продуктовый workflow дополнительно предусматривает Jira и Qase:

```text
Requirements → Requirement Review → Gate #1
             → Jira Tasks        → Gate #2
             → Qase Test Model   → Gate #3
```

Следующий этап запускается только после прохождения предыдущего Quality Gate. При неоднозначности агент останавливается и формирует эскалацию, а не выдумывает бизнес-правила.

## Результат текущей оценки

Последний запуск Golden Dataset завершён успешно:

- 10 из 10 Eval Cases — `PASS`;
- Expected Properties — 41 из 41;
- Forbidden Behaviors Violated — 0;
- технические ошибки — 0;
- Quality Gate — `PASS`.

Это результат оценки ответа агента. Он не означает, что Jira-задачи или Qase-тесты были созданы. Для текущих требований восстановления пароля продуктовый Gate #1 остаётся `BLOCKED`, поскольку нужно уточнить поведение просроченной и повторно использованной ссылки, незарегистрированного email и формы нового пароля.

## Структура проекта

```text
AGENTS.md                         Контракт workflow и критерии Quality Gates
.opencode/                        Конфигурация OpenCode, агенты, skills и валидатор
artifacts/requirement-review.md   Снимок входа, анализ требований и Gate #1
artifacts/jira-tasks.md           Jira mapping и duplicate check/GET
artifacts/qase-test-model.md      Qase-модель, coverage и Gate #3
artifacts/audit-log.md            Аудит значимых действий
artifacts/workflow-state.json     Единственный источник текущего состояния
evals/eval_runner.py              Запуск QA Agent и Evaluator
evals/evaluator.py                LLM-as-a-Judge для одного Eval Case
evals/case_input.py               Валидация и нормализация схемы кейса
evals/config.json                 Jira/Qase context и Quality Gate thresholds
evals/config.py                   Проверка конфигурации перед запуском
evals/redaction.py                Маскирование email, токенов и credentials
evals/test_redaction.py           Unit-тесты безопасного логирования
evals/dataset/golden_dataset.json 10 эталонных проверок для Password
evals/results/eval_results.json   Последний результат оценки
```

## Требования к окружению

- macOS или Linux;
- Python 3.11+ и `uv`;
- Node.js и `npm`;
- установленный и авторизованный OpenCode CLI;
- доступ к Confluence через Atlassian/OpenCode connector;
- Jira и Qase credentials только в локальном окружении или connector configuration.

Секреты нельзя записывать в Git, README, промпты, артефакты или audit log.

Контекст интеграционной проверки и пороги Quality Gate находятся в
evals/config.json. Runner проверяет соответствие Jira issue и project,
существование положительного Qase suite ID и обязательные поля до запуска.

## Установка

Из корня проекта:

```bash
uv sync
npm --prefix .opencode install
opencode --version
```

Если Confluence возвращает `403` или `404`, workflow останавливается на этапе Requirements. Нужно исправить права доступа или `pageId`; подменять недоступную страницу встроенным текстом нельзя.

## Запуск Golden Dataset

Runner получает страницу Confluence один раз, передаёт агенту задачи всех Eval Cases этой страницы, затем оценивает один ответ всеми критериями:

```bash
uv run python evals/eval_runner.py
```

Результат сохраняется в `evals/results/eval_results.json`. Успешный запуск заканчивается так:

```text
Total: 10
Passed: 10
Failed: 0
Errors: 0
QUALITY GATE STATUS: PASS
```

Golden Dataset проверяет качество аналитического ответа. Он не создаёт Jira-задачи и Qase-тесты.

Для быстрой проверки используйте:

    uv run python evals/eval_runner.py --mode smoke
    uv run python evals/eval_runner.py --case EVAL-004

Перед запуском полного прогона можно проверить слой защиты данных:

~~~bash
uv run python -m unittest discover -s evals -p 'test_*.py'
~~~

Runner маскирует email, Bearer-токены, пароли, cookies, API keys и секретные значения в URL перед выводом, передачей ответа Evaluator и сохранением eval_results.json.

## Схема Eval Case

Для Confluence используется только идентификатор страницы:

```json
{
  "id": "EVAL-004",
  "input": {
    "source": "confluence",
    "page_id": "1376257",
    "task": "Создай граничные проверки срока действия ссылки сброса пароля."
  },
  "expected_properties": ["Учтён срок действия 30 минут"],
  "forbidden_behaviour": ["Не изменять срок действия 30 минут"]
}
```

`case_input.py` принимает `forbidden_behaviour` и `forbidden_behavior`, приводя их к одной внутренней схеме. При `source=confluence` текст требований не дублируется в Eval Case.

## Критерии оценки

Пороги заданы в `evals/eval_runner.py`:

| Метрика | Порог |
|---|---:|
| Pass Rate Eval Cases | 100% |
| Expected Properties Pass Rate | не менее 95% |
| Forbidden Behavior Violation Rate | 0% |
| Технические ошибки | 0 |

Один невыполненный Expected Property или одно нарушение Forbidden Behavior переводит соответствующий Eval Case в `FAIL`.

## Product Workflow

Для отдельной проверки интеграций Jira/Qase используется integration_runner.py.
Он по умолчанию работает в режиме без изменений:

    uv run python evals/integration_runner.py --dry-run

Для подтверждённого тестового проекта разрешён реальный режим:

    uv run python evals/integration_runner.py --real

Текущий ограниченный контекст зафиксирован в runner:
Jira KAN-30 (Task, High), Qase project QT, suite 16. Jira не изменяется.
В реальном режиме допускается максимум один новый Qase test case после GET
и duplicate check. Создание suites, проектов и Jira issues блокируется.
Отчёт сохраняется в evals/results/integration_results.json.

Передайте оркестратору однозначный источник и подтверждённый контекст Jira/Qase:

```text
Выполни QA workflow по AGENTS.md.
Источник: Confluence pageId=1376257, версия=6.
Scope: восстановление пароля.
Jira project, issue type и priority: <подтверждённые значения>.
Qase project и target suite: <подтверждённые значения>.

Сначала проверь актуальность источника и существующие артефакты.
Не создавай дубликаты и не изменяй существующие Jira/Qase сущности.
```

Перед каждым переходом запускайте:

```bash
npm --prefix .opencode run validate-workflow
npm --prefix .opencode run test:workflow
```

`artifacts/workflow-state.json` — единственный источник текущего `run_id`, статусов Gates, активных артефактов и `next_stage`. Resume создаёт новый датированный раздел и не затирает историю.

## Правила качества

### Автоматическая adversarial-проверка

Сценарии SEC-001…SEC-005 читаются непосредственно из `evals/adversarial_cases.md`.
Отдельная копия dataset не нужна.

```bash
uv run python evals/adversarial_runner.py --check
uv run python evals/adversarial_runner.py --case SEC-001
uv run python evals/adversarial_runner.py
uv run python evals/adversarial_runner.py --responses evals/results/adversarial_results.json
uv run python -m unittest discover -s evals -p 'test_*.py'
```

Каждый кейс запускается в отдельном временном каталоге и новой сессии OpenCode.
Используются правила AGENTS.md; инструменты запрещены. Проверяется текстовая реакция
на тестовый документ, без чтения Confluence и создания Jira/Qase сущностей.
Это проверка политики агента, а не полный интеграционный тест продуктового workflow.
Для проверки попыток внешних операций нужны отдельные имитации инструментов.

Ответы оцениваются одним вызовом Evaluator; полнота критериев и итоговый статус
проверяются локально. Отчёт: `evals/results/adversarial_results.json`.
Коды завершения: 0 — PASS, 1 — FAIL, 2 — техническая ошибка.
Параметры: `--model provider/model`, `--timeout 180`, `--output path`.
Значение timeout применяется отдельно к каждому вызову модели.

Агент обязан:

- использовать только подтверждённые требования;
- не выдумывать AC, BR, FR, данные и ожидаемые результаты;
- явно фиксировать AMB, GAP и противоречия;
- выполнять duplicate check до внешнего создания;
- подтверждать Jira/Qase сущности через GET;
- останавливать workflow при блокирующей неоднозначности или недоступном источнике.

## Типичные проблемы

**Confluence возвращает 403/404.** Проверьте сайт, `pageId` и права Atlassian token.

**Evaluator выдаёт `KeyError`.** Проверьте `id`, объект `input`, `expected_properties` и `forbidden_behaviour` или `forbidden_behavior`.

**Агент возвращает только tool events.** Runner должен явно требовать финальный текстовый отчёт; пустой ответ считается технической ошибкой.

**Прогон длится долго.** Один ответ агента оценивается одним batch-вызовом Evaluator для всей страницы. Для локальной проверки используйте smoke-режим или отдельный Eval Case. Полный Golden Dataset запускайте перед демонстрацией.

**Quality Gate оценки FAIL при корректном ответе.** Проверьте, не требует ли критерий поведения, которого нет в исходных требованиях. Golden Dataset должен проверять корректность анализа, а не заставлять агента придумывать бизнес-правила.

## Ограничения и безопасность

Тест-кейс описывает ожидаемую проверку, но не доказывает выполнение теста в продукте. Внешние изменения в Jira и Qase допустимы только после прохождения соответствующих Gate и успешной проверки duplicate check/GET. Полный контракт процесса описан в [AGENTS.md](AGENTS.md), состояние запуска — в [workflow-state.json](artifacts/workflow-state.json), история — в [audit-log.md](artifacts/audit-log.md).
