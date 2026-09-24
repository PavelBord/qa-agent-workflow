import json
import subprocess
from pathlib import Path
from case_input import normalize_case
from redaction import mask_sensitive


# =============================================================
# PATHS
# =============================================================

# Корень проекта QAI-05
project_path = Path(__file__).resolve().parent.parent


# =============================================================
# EVALUATOR
# =============================================================

def evaluate_response(eval_case, agent_response):

    # ---------------------------------------------------------
    # INPUT EVAL CASE
    # ---------------------------------------------------------

    # Accept both spellings used by older teacher datasets, then evaluate one
    # canonical schema. This prevents every case from failing before OpenCode.
    eval_case = normalize_case(eval_case)
    eval_input = eval_case["input"]

    source = eval_input.get("source")


    # ---------------------------------------------------------
    # ОПИСАНИЕ ИСТОЧНИКА
    # ---------------------------------------------------------

    if source == "inline":

        input_description = eval_input["requirements"]

    elif source == "confluence":

        input_description = (
            f"Требования находятся в Confluence. "
            f"pageId={eval_input['page_id']}."
        )

    else:

        input_description = str(eval_input)


    # =========================================================
    # PROMPT ДЛЯ LLM-AS-A-JUDGE
    # =========================================================

    safe_agent_response = mask_sensitive(agent_response)

    judge_prompt = f"""
Ты — независимый Evaluator результатов AI QA Agent.
Твоя задача — оценить фактический ответ агента
относительно заданного Eval Case.
ПРАВИЛА ОЦЕНКИ:
1. Оценивай смысл ответа, а не точное совпадение формулировок.
2. Не добавляй собственные требования.
3. Каждое Expected Property оцени отдельно.
4. Каждое Forbidden Behavior оцени отдельно.
5. Expected Property считается выполненным,
если ответ агента явно или семантически подтверждает
требуемое поведение.
6. Forbidden Behavior считается нарушенным только тогда,
когда агент действительно совершил запрещённое действие.
7. Итоговый статус PASS возможен только если:
- выполнены ВСЕ Expected Properties;
- не нарушено НИ ОДНО Forbidden Behavior.
8. Если хотя бы одно Expected Property не выполнено,
итоговый статус должен быть FAIL.
9. Если хотя бы одно Forbidden Behavior нарушено,
итоговый статус должен быть FAIL.
EVAL CASE ID:
{eval_case["id"]}
INPUT SOURCE:
{source}
INPUT:
{input_description}
EXPECTED PROPERTIES:
{json.dumps(
    eval_case["expected_properties"],
    ensure_ascii=False,
    indent=2
)}
FORBIDDEN BEHAVIOR:
{json.dumps(
    eval_case["forbidden_behavior"],
    ensure_ascii=False,
    indent=2
)}
ACTUAL AGENT RESPONSE:
{safe_agent_response}
Верни ТОЛЬКО валидный JSON следующей структуры:
{{
  "eval_case_id": "{eval_case["id"]}",
  "expected_properties": [
    {{
      "property": "текст проверяемого Expected Property",
      "passed": true,
      "reason": "краткое объяснение решения"
    }}
  ],
  "forbidden_behavior": [
    {{
      "rule": "текст проверяемого Forbidden Behavior",
      "violated": false,
      "reason": "краткое объяснение решения"
    }}
  ],
  "status": "PASS",
  "score": 1.0
}}
ПРАВИЛА SCORE:
1.0 — PASS.
0.0 — FAIL.
ВАЖНО:
Не используй Markdown.
Не используй ```json.
Не используй ```.
Не добавляй пояснения до JSON.
Не добавляй пояснения после JSON.
Ответ должен содержать только один JSON-объект.
"""


    # =========================================================
    # ЗАПУСК EVALUATOR
    # =========================================================

    process = subprocess.Popen(
        [
            "opencode",
            "run",
            "--format",
            "json",
            "--dir",
            str(project_path),
            judge_prompt
        ],
        cwd=project_path,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1
    )


    # Здесь собираем текстовый ответ Evaluator.
    text_parts = []


    print("Evaluator запущен...")


    # =========================================================
    # ЧТЕНИЕ JSON EVENTS
    # =========================================================

    if process.stdout:

        for line in process.stdout:

            line = line.strip()

            if not line:
                continue

            try:

                event = json.loads(line)

                event_type = event.get("type")

                print(
                    "EVALUATOR EVENT:",
                    event_type,
                    flush=True
                )


                # Забираем только текстовые события.
                if event_type == "text":

                    part = event.get("part", {})

                    text = part.get("text")

                    if text:
                        text_parts.append(text)


            except json.JSONDecodeError:

                print(
                    "Не удалось разобрать событие Evaluator",
                    flush=True
                )


    # =========================================================
    # ЗАВЕРШЕНИЕ EVALUATOR
    # =========================================================

    return_code = process.wait()


    print(
        "EVALUATOR RETURN CODE:",
        return_code
    )


    # ---------------------------------------------------------
    # ПРОВЕРКА RETURN CODE
    # ---------------------------------------------------------

    if return_code != 0:

        stderr = ""

        if process.stderr:
            stderr = process.stderr.read()

        raise RuntimeError(
            f"Evaluator завершился с ошибкой. "
            f"Return code: {return_code}. "
            f"STDERR: {mask_sensitive(stderr)}"
        )


    # =========================================================
    # СБОРКА ОТВЕТА
    # =========================================================

    judge_response = "\n".join(
        text_parts
    ).strip()


    if not judge_response:

        raise RuntimeError(
            "Evaluator не вернул текстовый ответ."
        )


    # =========================================================
    # УДАЛЕНИЕ MARKDOWN CODE BLOCK
    # =========================================================

    # На случай, если модель всё-таки вернула:
    #
    # ```json
    # {...}
    # ```

    if judge_response.startswith("```json"):

        judge_response = judge_response[7:]

    elif judge_response.startswith("```"):

        judge_response = judge_response[3:]


    if judge_response.endswith("```"):

        judge_response = judge_response[:-3]


    judge_response = judge_response.strip()


    # =========================================================
    # JSON PARSING
    # =========================================================

    try:

        evaluation_result = json.loads(
            judge_response
        )

    except json.JSONDecodeError as error:

        print()
        print(
            "Не удалось разобрать ответ "
            "Evaluator как JSON."
        )

        print()
        print("Фактический ответ Evaluator:")

        print(mask_sensitive(judge_response))

        raise RuntimeError(
            "Evaluator вернул невалидный JSON."
        ) from error


    # =========================================================
    # ПРОВЕРКА СТРУКТУРЫ
    # =========================================================

    required_fields = [
        "eval_case_id",
        "expected_properties",
        "forbidden_behavior",
        "status",
        "score"
    ]


    for field in required_fields:

        if field not in evaluation_result:

            raise RuntimeError(
                f"В ответе Evaluator отсутствует "
                f"обязательное поле: {field}"
            )


    # =========================================================
    # RETURN
    # =========================================================

    return evaluation_result


def evaluate_responses_batch(eval_cases, agent_response, timeout_seconds=120):
    """Evaluate one agent response against several cases in one LLM call."""

    normalized_cases = [normalize_case(case) for case in eval_cases]
    cases = [
        {
            "id": case["id"],
            "input": case["input"],
            "expected_properties": case["expected_properties"],
            "forbidden_behavior": case["forbidden_behavior"],
        }
        for case in normalized_cases
    ]
    safe_response = mask_sensitive(agent_response)
    cases_json = json.dumps(cases, ensure_ascii=False, separators=(",", ":"))

    judge_prompt = f"""
Ты — независимый Evaluator результатов AI QA Agent.
Оцени один ответ агента по всем Eval Cases ниже.
Для каждого кейса:
- проверь все expected_properties отдельно;
- проверь все forbidden_behavior отдельно;
- оценивай смысл, а не точное совпадение формулировок;
- не добавляй собственные требования;
- PASS возможен только если все expected_properties выполнены и violated=false для всех forbidden_behavior.

EVAL CASES:
{cases_json}

ACTUAL AGENT RESPONSE:
{safe_response}

Верни только один валидный JSON без Markdown:
{{"results":[
  {{
    "eval_case_id":"EVAL-001",
    "expected_properties":[
      {{"property":"точный текст свойства","passed":true,"reason":"краткое объяснение"}}
    ],
    "forbidden_behavior":[
      {{"rule":"точный текст правила","violated":false,"reason":"краткое объяснение"}}
    ],
    "status":"PASS",
    "score":1.0
  }}
]}}
В каждом результате перечисли ВСЕ свойства и правила соответствующего кейса.
"""

    process = subprocess.Popen(
        [
            "opencode",
            "run",
            "--format",
            "json",
            "--dir",
            str(project_path),
            judge_prompt,
        ],
        cwd=project_path,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    print("Evaluator batch запущен...")
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as error:
        process.kill()
        stdout, stderr = process.communicate()
        raise RuntimeError(
            f"Evaluator batch превысил timeout {timeout_seconds} секунд. "
            f"Процесс остановлен. STDERR: {mask_sensitive(stderr or '')}"
        ) from error

    text_parts = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
            print("EVALUATOR EVENT:", event.get("type"), flush=True)
            if event.get("type") == "text":
                text = event.get("part", {}).get("text")
                if text:
                    text_parts.append(text)
        except json.JSONDecodeError:
            print("Не удалось разобрать событие Evaluator", flush=True)

    return_code = process.returncode
    print("EVALUATOR RETURN CODE:", return_code)
    if return_code != 0:
        stderr = process.stderr.read() if process.stderr else ""
        raise RuntimeError(
            f"Evaluator batch завершился с ошибкой: {mask_sensitive(stderr)}"
        )

    response = "\n".join(text_parts).strip()
    fence = chr(96) * 3
    if response.startswith(fence + "json"):
        response = response[7:]
    elif response.startswith(fence):
        response = response[3:]
    if response.endswith(fence):
        response = response[:-3]
    try:
        payload = json.loads(response.strip())
    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"Evaluator batch вернул невалидный JSON: {mask_sensitive(response)}"
        ) from error

    if isinstance(payload, dict) and isinstance(payload.get("results"), list):
        results = payload["results"]
    elif isinstance(payload, dict) and (
        "eval_case_id" in payload or "id" in payload
    ):
        # Models sometimes return the single requested case in the legacy
        # object format instead of wrapping it in {"results": [...]}.
        results = [payload]
    else:
        results = None
    if not isinstance(results, list):
        raise RuntimeError("Evaluator batch должен вернуть массив results.")

    expected_ids = {case["id"] for case in normalized_cases}
    for result in results:
        if "eval_case_id" not in result and "id" in result:
            result["eval_case_id"] = result.pop("id")
    actual_ids = {result.get("eval_case_id") for result in results}
    if actual_ids != expected_ids or len(results) != len(expected_ids):
        raise RuntimeError(
            f"Evaluator batch вернул неполный набор кейсов: {sorted(actual_ids)}"
        )

    required_fields = {
        "eval_case_id",
        "expected_properties",
        "forbidden_behavior",
        "status",
        "score",
    }
    output = {}
    for result in results:
        if "eval_case_id" not in result and "id" in result:
            result["eval_case_id"] = result.pop("id")
        if "expected_properties" not in result and "properties" in result:
            result["expected_properties"] = result.pop("properties")
        if "forbidden_behavior" not in result and "forbidden_behaviour" in result:
            result["forbidden_behavior"] = result.pop("forbidden_behaviour")
        if "status" not in result and "result" in result:
            result["status"] = result.pop("result")
        if "score" not in result and result.get("status") in {"PASS", "FAIL"}:
            result["score"] = 1.0 if result["status"] == "PASS" else 0.0
        missing = required_fields - result.keys()
        if missing:
            raise RuntimeError(
                f"В результате {result.get('eval_case_id')} отсутствуют: "
                f"{sorted(missing)}; keys={sorted(result.keys())}"
            )
        output[result["eval_case_id"]] = result
    return output
