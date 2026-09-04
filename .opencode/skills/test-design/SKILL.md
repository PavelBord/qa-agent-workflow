---
name: test-design
description: Проектирует и создаёт тестовую модель в Qase на основе Requirement Review Artifact и Jira-задач.
---

# SKILL: QASE TEST MODEL DESIGN

## PURPOSE

Создать тестовую модель Qase с полной traceability:

`Requirement → Jira Task → Qase Test Case`

## INPUT

Обязательные условия:

- `artifacts/requirement-review.md` = `PASS`
- `artifacts/jira-tasks.md` = `PASS`
- Qase project и target suite

`Requirement ID` извлекается из `artifacts/requirement-review.md`.

Дополнительные данные:

- Jira Task ID, если задача существует.

Источник требований — только `Requirement Review Artifact`.

Источник Jira mapping — только `artifacts/jira-tasks.md`.

Не использовать:

- предположения;
- неподтверждённые данные;
- исторические версии;
- самостоятельно найденные требования.

## PROCEDURE

### Test Design

Для каждой функциональности определить необходимые тесты на основании Requirement Review:

- positive;
- negative — только для заданных правил валидации;
- boundary — только для заданных ограничений;
- business rules / AC.

Не создавать тесты, основанные только на общих QA-предположениях.

Для каждого теста определить:

- Suite;
- заголовок;
- описание;
- предусловия, если определены;
- шаги;
- ожидаемый результат;
- Requirement ID;
- FR/BR/AC mapping;
- Jira Task ID, если существует.

### Qase Validation

Перед созданием:

- проверить существующие Qase suites;
- проверить существующие test cases;
- выполнить duplicate check;
- определить отсутствующие тесты.

Не создавать дубликаты.

Если Qase project или target suite недоступны:

- `BLOCKED`;
- тесты не создавать.

### Test Creation

Создавать только отсутствующие тесты.

После создания каждого теста:

- выполнить Qase GET verification;
- проверить Qase Test Case ID;
- проверить заголовок;
- проверить Requirement ID;
- проверить FR/BR/AC mapping;
- проверить соответствие Requirement Review.

Тест считать `created` только после успешной GET verification.

Существующие подтверждённые тесты не изменять.

Тесты для `BLOCKED` Jira-задач не создавать.

Если создание теста завершилось ошибкой:

- не считать тест созданным;
- установить статус `error`;
- зафиксировать причину.

Если GET verification завершилась ошибкой:

- установить статус `error`;
- не считать тест подтверждённым.

### Jira Mapping

Для каждого теста определить Jira Task ID из `artifacts/jira-tasks.md`.

Если Jira Task существует:

`Requirement ID → Jira Task ID → Qase Test Case ID`

Если Jira Task отсутствует:

- не создавать Jira mapping самостоятельно;
- использовать `N/A`, если отсутствие Jira mapping допустимо;
- использовать `BLOCKED`, если Jira mapping обязателен.

## DUPLICATE CHECK

Проверять существующие тесты по:

- Requirement ID;
- FR;
- BR;
- AC;
- функциональности;
- заголовку.

При обнаружении существующего теста:

- не создавать дубликат;
- сохранить его Qase Test Case ID;
- выполнить необходимую GET verification;
- зафиксировать статус `existing`.

Если duplicate check невозможно выполнить:

- установить `BLOCKED`;
- тест не создавать;
- зафиксировать причину.

## COVERAGE

Рассчитать покрытие:

- FR;
- BR;
- AC.

Для каждого определить:

`total / covered / uncovered / coverage %`

Покрытие считается только по тестам со статусом:

- `created` — после успешной GET verification;
- `existing` — после подтверждения существующего теста.

Тесты со статусом `blocked` или `error` не учитываются как покрытие.

Правила:

- если `total > 0` → coverage должен быть `100%`;
- если `total = 0` → coverage = `N/A`;
- непокрытые требования должны быть явно перечислены.

Для успешного завершения:

- FR = `100%` или `N/A`;
- BR = `100%` или `N/A`;
- AC = `100%` или `N/A`.

Не создавать искусственные тесты для требований, которых нет.

## OUTPUT

Сохранить результат в:

`artifacts/qase-test-model.md`

Для каждого теста сохранять:

- Qase Test Case ID;
- Suite;
- заголовок;
- тип;
- шаги;
- ожидаемый результат;
- Requirement ID;
- FR/BR/AC mapping;
- Jira Task ID;
- статус:
  - `created`
  - `existing`
  - `blocked`
  - `error`.

Также сохранить:

- FR coverage;
- BR coverage;
- AC coverage;
- непокрытые требования;
- результаты duplicate check;
- результаты GET verification;
- ошибки;
- блокировки;
- эскалации;
- `Requirement → Jira Task → Qase Test Case`.

Artifact должен содержать:

`Qase Stage: PASS / FAIL / BLOCKED`

## RULES

- Не выдумывать требования.
- Не выдумывать сценарии, которые не следуют из требований.
- Не выдумывать ожидаемые результаты.
- Каждый тест должен иметь requirement mapping.
- Не создавать дубликаты suites и тестов.
- Не изменять существующие тесты.
- Не изменять Test Runs и результаты.
- Не изменять настройки Qase.
- Не анализировать требования повторно.
- Не создавать Jira-задачи.
- Не считать тест созданным без успешной Qase GET verification.
- Ошибку авторизации считать блокирующей.
- Не логировать секреты, токены и пароли.
- Не считать `PASS`, если существуют нерешённые обязательные `BLOCKED` или `ERROR`.
- Не использовать Qase Test Case как источник требований.
- Не использовать Jira как источник требований.
- Не считать `blocked` или `error` тесты покрывающими требования.

## COMPLETION CRITERIA

Skill выполнен успешно, если:

- Requirement Review = `PASS`;
- Jira Stage = `PASS`;
- каждый созданный или существующий тест имеет Requirement ID;
- каждый тест имеет соответствующий FR/BR/AC mapping;
- Jira mapping сохранён, если он существует;
- дубликаты не созданы;
- каждый новый тест подтверждён через Qase GET;
- существующие тесты подтверждены;
- FR coverage = `100%` или `N/A`;
- BR coverage = `100%` или `N/A`;
- AC coverage = `100%` или `N/A`;
- отсутствуют непокрытые обязательные требования;
- отсутствуют нерешённые обязательные `BLOCKED` / `ERROR`;
- сохранена связь `Requirement → Jira Task → Qase Test Case`;
- результат сохранён в `artifacts/qase-test-model.md`.