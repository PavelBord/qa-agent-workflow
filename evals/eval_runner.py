import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from config import load_config
from evaluator import evaluate_responses_batch
from redaction import mask_object, mask_sensitive
from response_store import load_response, save_response
from process_control import RunInterrupted, wait_for_process

# =============================================================
# PATHS
# =============================================================

project_path = Path(__file__).resolve().parent.parent

default_dataset_path = (
    Path(__file__).parent
    / "dataset"
    / "golden_dataset.json"
)

def main():
    parser = argparse.ArgumentParser(description="Run QA Agent Golden Dataset evaluation.")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=default_dataset_path,
        help="Path to a JSON Eval Case dataset.",
    )
    parser.add_argument(
        "--mode",
        choices=("smoke", "golden"),
        default="golden",
        help="smoke runs one case; golden runs the complete dataset.",
    )
    parser.add_argument(
        "--case",
        action="append",
        dest="case_ids",
        help="Run only the selected Eval Case id. Can be repeated.",
    )
    parser.add_argument('--responses', type=Path, help='Evaluate a saved response without running QA Agent.')
    parser.add_argument('--output', type=Path, help='Custom evaluation report path.')
    parser.add_argument('--agent-timeout', type=int, default=300, help='QA Agent timeout in seconds (default: 300).')
    args = parser.parse_args()
    if args.agent_timeout <= 0:
        parser.error('--agent-timeout must be positive')
    dataset_path = args.dataset


    # =============================================================
    # QUALITY GATE THRESHOLDS
    # =============================================================

    quality_gate = load_config()["quality_gate"]
    MIN_PASS_RATE = float(quality_gate["min_pass_rate"])
    MIN_EXPECTED_PROPERTIES_PASS_RATE = float(
        quality_gate["min_expected_properties_pass_rate"]
    )
    MAX_FORBIDDEN_BEHAVIOR_VIOLATION_RATE = float(
        quality_gate["max_forbidden_behavior_violation_rate"]
    )
    MAX_ERRORS = int(quality_gate["max_errors"])
    EVALUATOR_TIMEOUT_SECONDS = int(quality_gate["evaluator_timeout_seconds"])


    # =============================================================
    # ЗАГРУЗКА GOLDEN DATASET
    # =============================================================

    with open(
        dataset_path,
        "r",
        encoding="utf-8"
    ) as file:

        eval_cases = json.load(file)

    if args.case_ids:
        requested = set(args.case_ids)
        eval_cases = [case for case in eval_cases if case.get("id") in requested]
        missing = requested - {case.get("id") for case in eval_cases}
        if missing:
            raise RuntimeError(f"Eval Case не найден: {sorted(missing)}")
    elif args.mode == "smoke":
        eval_cases = eval_cases[:1]

    if not eval_cases:
        raise RuntimeError("Dataset не содержит Eval Cases для запуска.")


    saved_response = load_response(args.responses, eval_cases) if args.responses else None
    response_refs = []
    eval_results = []
    interrupted = False


    # =============================================================
    # ГРУППИРОВКА EVAL CASES ПО СТРАНИЦЕ CONFLUENCE
    # =============================================================

    cases_by_page = {}


    for eval_case in eval_cases:

        eval_input = eval_case["input"]

        source = eval_input.get("source")


        if source != "confluence":

            raise RuntimeError(
                f"Eval Case {eval_case['id']} использует "
                f"неподдерживаемый источник: {source}"
            )


        page_id = eval_input["page_id"]


        if page_id not in cases_by_page:

            cases_by_page[page_id] = []


        cases_by_page[page_id].append(
            eval_case
        )


    # =============================================================
    # ЗАПУСК QA AGENT
    # =============================================================

    for page_id, page_eval_cases in cases_by_page.items():
        if interrupted:
            eval_results.extend({'id': c['id'], 'name': c.get('name', c['id']), 'status': 'ERROR', 'score': 0.0, 'expected_properties': [], 'forbidden_behavior': [], 'error': 'Запуск прерван пользователем'} for c in page_eval_cases)
            continue

        if args.responses:
            agent_response = saved_response
            response_refs.append(str(args.responses))
            print(f'Повторная оценка исторического ответа: {args.responses}. Актуальность Confluence не проверяется.')
        else:
            print()
            print("=" * 80)
            print("ЗАПУСК QA AGENT")
            print("=" * 80)

            print()
            print("Источник требований: Confluence")
            print(f"pageId: {page_id}")

            print(
                f"Количество Eval Cases для этой страницы: "
                f"{len(page_eval_cases)}"
            )

            print()


            # =========================================================
            # PROMPT ДЛЯ QA AGENT
            # =========================================================

            # Runner передаёт агенту только исходную задачу.
            #
            # Expected Properties и Forbidden Behavior
            # агенту не передаются.

            tasks = "\n".join(
                f"{index}. {case['input'].get('task', 'Проанализируй требования.')}"
                for index, case in enumerate(page_eval_cases, 1)
            )
            prompt = (
                f"Получи актуальные требования из Confluence со страницы pageId={page_id}.\n"
                "Выполни все задачи ниже в одном анализе, не обращаясь к golden dataset и критериям оценки:\n"
                f"{tasks}\n\n"
                "После завершения обязательно верни подробный итоговый текст: результаты анализа, "
                "тест-кейсы, найденные неоднозначности и ограничения. Не заканчивай workflow только tool-вызовами."
            )


            # =========================================================
            # ЗАПУСК OPENCODE
            # =========================================================

            text_parts, event_types, agent_errors = [], [], []
            stderr = ''
            failure_reason = None
            try:
                process = subprocess.Popen(
                    ['opencode', 'run', '--format', 'json', '--dir', str(project_path), prompt],
                    cwd=project_path, stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, start_new_session=True,
                )
                print('QA Agent запущен...', flush=True)
                stdout, stderr = wait_for_process(process, args.agent_timeout, 'QA Agent')
                return_code = process.returncode
                for line in stdout.splitlines():
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(event, dict):
                        continue
                    event_type = event.get('type')
                    event_types.append(event_type)
                    print('AGENT EVENT:', event_type)
                    if event_type == 'error':
                        agent_errors.append(mask_object(event))
                    if event_type == 'text':
                        text = event.get('part', {}).get('text')
                        if text:
                            text_parts.append(text)
                if agent_errors:
                    return_code = return_code or 1
                failure_reason = mask_sensitive(stderr or (json.dumps(agent_errors, ensure_ascii=False) if agent_errors else f'exit {return_code}'))
            except (RuntimeError, OSError) as error:
                return_code = 1
                failure_reason = mask_sensitive(error)
                interrupted = isinstance(error, RunInterrupted)
            agent_response = '\n'.join(text_parts).strip()
            print('QA AGENT RETURN CODE:', return_code)

            # =========================================================
            # ОБРАБОТКА ОШИБКИ QA AGENT
            # =========================================================

            if return_code != 0:

                print(
                    "QA Agent завершился с ошибкой."
                )


                print(failure_reason)

                for eval_case in page_eval_cases:

                    eval_results.append(
                        {
                            "id": eval_case["id"],
                            "name": eval_case.get("name", eval_case["id"]),
                            "status": "ERROR",
                            "error": failure_reason,
                            "score": 0.0,
                            "expected_properties": [],
                            "forbidden_behavior": []
                        }
                    )


                continue


            # =========================================================
            # ПРОВЕРКА ПУСТОГО ОТВЕТА
            # =========================================================

            if not agent_response:

                print(
                    "QA Agent не вернул "
                    f"текстовый ответ. Получены события: {', '.join(str(item) for item in event_types)}."
                )


                for eval_case in page_eval_cases:

                    eval_results.append(
                        {
                            "id": eval_case["id"],
                            "name": eval_case.get("name", eval_case["id"]),
                            "status": "ERROR",
                            "score": 0.0,
                            "expected_properties": [],
                            "forbidden_behavior": []
                        }
                    )


                continue


            response_path = save_response(
                Path(__file__).parent / 'results' / 'responses',
                page_id, page_eval_cases, agent_response,
            )
            response_refs.append(str(response_path))
            print(f'Ответ сохранён до Evaluator: {response_path}', flush=True)

        # =========================================================
        # ВЫВОД ОТВЕТА QA AGENT
        # =========================================================

        print()
        print("=" * 80)
        print("ОТВЕТ QA AGENT")
        print("=" * 80)

        print(mask_sensitive(agent_response))

        print("=" * 80)


        # =========================================================
        # EVALUATION
        # =========================================================

        # Один фактический Agent Response проверяется всеми Eval Cases
        # одним вызовом Evaluator, чтобы не передавать большой текст повторно.
        batch_error = None
        try:
            batch_results = evaluate_responses_batch(
                page_eval_cases,
                agent_response,
                timeout_seconds=EVALUATOR_TIMEOUT_SECONDS,
            )
        except Exception as error:
            print()
            print("Ошибка Evaluator batch:")
            print(mask_sensitive(error))
            interrupted = isinstance(error, RunInterrupted)
            batch_error = mask_sensitive(error)
            batch_results = {}

        for eval_case in page_eval_cases:

            print()
            print()

            print("-" * 80)

            print(
                f"Evaluation: "
                f"{eval_case['id']}"
            )

            print(
                f"Название: "
                f"{eval_case.get('name', eval_case['id'])}"
            )

            print("-" * 80)

            print()
            print("Результат пакетной оценки:")


            try:

                if batch_error:
                    raise RuntimeError(batch_error)
                evaluation_result = batch_results[eval_case["id"]]


                print()
                print("=" * 80)
                print("РЕЗУЛЬТАТ EVALUATION")
                print("=" * 80)


                print(
                    json.dumps(
                        evaluation_result,
                        ensure_ascii=False,
                        indent=2
                    )
                )


                print("=" * 80)


                status = evaluation_result[
                    "status"
                ]

                score = evaluation_result[
                    "score"
                ]


                eval_results.append(
                    {
                        "id": eval_case["id"],
                        "name": eval_case.get("name", eval_case["id"]),
                        "status": status,
                        "score": score,
                        "judge_status": evaluation_result.get("judge_status"),
                        "judge_score": evaluation_result.get("judge_score"),
                        "aggregation_corrected": evaluation_result.get("aggregation_corrected", False),

                        "expected_properties":
                            evaluation_result[
                                "expected_properties"
                            ],

                        "forbidden_behavior":
                            evaluation_result[
                                "forbidden_behavior"
                            ]
                    }
                )


                print()

                print(
                    "EVAL CASE:",
                    eval_case["id"]
                )

                print(
                    "STATUS:",
                    status
                )

                print(
                    "SCORE:",
                    score
                )


            except Exception as error:

                print()
                print("Ошибка Evaluator:")
                print(error)


                eval_results.append(
                    {
                        "id": eval_case["id"],
                        "name": eval_case.get("name", eval_case["id"]),
                        "status": "ERROR",
                        "score": 0.0,
                        "expected_properties": [],
                        "forbidden_behavior": [],
                        "error": mask_sensitive(error),
                    }
                )


    # =============================================================
    # EVALUATION SUMMARY
    # =============================================================

    print()
    print()

    print("=" * 80)
    print("EVALUATION SUMMARY")
    print("=" * 80)


    # =============================================================
    # BASIC METRICS
    # =============================================================

    total = len(eval_results)


    passed = sum(
        1
        for result in eval_results
        if result["status"] == "PASS"
    )


    failed = sum(
        1
        for result in eval_results
        if result["status"] == "FAIL"
    )


    errors = sum(
        1
        for result in eval_results
        if result["status"] == "ERROR"
    )


    # =============================================================
    # PASS RATE
    # =============================================================

    if total > 0:

        pass_rate = (
            passed / total
        ) * 100

    else:

        pass_rate = 0.0


    # =============================================================
    # AVERAGE SCORE
    # =============================================================

    if total > 0:

        average_score = (
            sum(
                result["score"]
                for result in eval_results
            )
            / total
        )

    else:

        average_score = 0.0


    # =============================================================
    # EXPECTED PROPERTIES PASS RATE
    # =============================================================

    total_expected_properties = 0

    passed_expected_properties = 0


    for result in eval_results:

        expected_properties = result.get(
            "expected_properties",
            []
        )


        for expected_property in expected_properties:

            total_expected_properties += 1


            if expected_property.get(
                "passed"
            ) is True:

                passed_expected_properties += 1


    if total_expected_properties > 0:

        expected_properties_pass_rate = (
            passed_expected_properties
            / total_expected_properties
        ) * 100

    else:

        expected_properties_pass_rate = 0.0


    # =============================================================
    # FORBIDDEN BEHAVIOR VIOLATION RATE
    # =============================================================

    total_forbidden_behaviors = 0

    violated_forbidden_behaviors = 0


    for result in eval_results:

        forbidden_behaviors = result.get(
            "forbidden_behavior",
            []
        )


        for forbidden_behavior in forbidden_behaviors:

            total_forbidden_behaviors += 1


            if forbidden_behavior.get(
                "violated"
            ) is True:

                violated_forbidden_behaviors += 1


    if total_forbidden_behaviors > 0:

        forbidden_behavior_violation_rate = (
            violated_forbidden_behaviors
            / total_forbidden_behaviors
        ) * 100

    else:

        forbidden_behavior_violation_rate = 0.0


    # =============================================================
    # BASIC METRICS OUTPUT
    # =============================================================

    print()

    print(
        f"Total:         {total}"
    )

    print(
        f"Passed:        {passed}"
    )

    print(
        f"Failed:        {failed}"
    )

    print(
        f"Errors:        {errors}"
    )

    print(
        f"Pass Rate:     "
        f"{pass_rate:.1f}%"
    )

    print(
        f"Average Score: "
        f"{average_score:.2f}"
    )


    # =============================================================
    # QUALITY METRICS OUTPUT
    # =============================================================

    print()

    print("QUALITY METRICS")

    print("-" * 80)


    print(
        f"Expected Properties:                 "
        f"{passed_expected_properties}/"
        f"{total_expected_properties}"
    )


    print(
        f"Expected Properties Pass Rate:       "
        f"{expected_properties_pass_rate:.1f}%"
    )


    print(
        f"Forbidden Behaviors Violated:        "
        f"{violated_forbidden_behaviors}/"
        f"{total_forbidden_behaviors}"
    )


    print(
        f"Forbidden Behavior Violation Rate:   "
        f"{forbidden_behavior_violation_rate:.1f}%"
    )


    # =============================================================
    # РЕЗУЛЬТАТЫ ПО КАЖДОМУ EVAL CASE
    # =============================================================

    print()

    print("-" * 80)


    for result in eval_results:

        print(
            f"{result['id']:<10}"
            f"{result['status']:<10}"
            f"Score: {result['score']}"
        )


    print("-" * 80)


    # =============================================================
    # QUALITY GATE
    # =============================================================

    # Теперь решение о допуске принимается
    # на основании измеримых метрик.


    # -------------------------------------------------------------
    # ПРОВЕРКА PASS RATE
    # -------------------------------------------------------------

    pass_rate_gate = (
        pass_rate
        >= MIN_PASS_RATE
    )


    # -------------------------------------------------------------
    # ПРОВЕРКА EXPECTED PROPERTIES
    # -------------------------------------------------------------

    expected_properties_gate = (
        expected_properties_pass_rate
        >= MIN_EXPECTED_PROPERTIES_PASS_RATE
    )


    # -------------------------------------------------------------
    # ПРОВЕРКА FORBIDDEN BEHAVIOR
    # -------------------------------------------------------------

    forbidden_behavior_gate = (
        forbidden_behavior_violation_rate
        <= MAX_FORBIDDEN_BEHAVIOR_VIOLATION_RATE
    )


    # -------------------------------------------------------------
    # ПРОВЕРКА ERRORS
    # -------------------------------------------------------------

    errors_gate = (
        errors
        <= MAX_ERRORS
    )


    # =============================================================
    # OVERALL QUALITY GATE
    # =============================================================

    quality_gate_passed = all(
        [
            pass_rate_gate,
            expected_properties_gate,
            forbidden_behavior_gate,
            errors_gate
        ]
    )


    if quality_gate_passed:

        overall_status = "PASS"

    else:

        overall_status = "FAIL"


    # =============================================================
    # QUALITY GATE OUTPUT
    # =============================================================

    print()
    print("=" * 80)
    print("QUALITY GATE")
    print("=" * 80)


    print()

    print(
        f"Pass Rate >= {MIN_PASS_RATE:.1f}%: "
        f"{'PASS' if pass_rate_gate else 'FAIL'} "
        f"(actual: {pass_rate:.1f}%)"
    )


    print(
        f"Expected Properties >= "
        f"{MIN_EXPECTED_PROPERTIES_PASS_RATE:.1f}%: "
        f"{'PASS' if expected_properties_gate else 'FAIL'} "
        f"(actual: {expected_properties_pass_rate:.1f}%)"
    )


    print(
        f"Forbidden Behavior <= "
        f"{MAX_FORBIDDEN_BEHAVIOR_VIOLATION_RATE:.1f}%: "
        f"{'PASS' if forbidden_behavior_gate else 'FAIL'} "
        f"(actual: {forbidden_behavior_violation_rate:.1f}%)"
    )


    print(
        f"Errors <= {MAX_ERRORS}: "
        f"{'PASS' if errors_gate else 'FAIL'} "
        f"(actual: {errors})"
    )


    print()
    print(
        "QUALITY GATE STATUS:",
        overall_status
    )

    print("=" * 80)


    # =============================================================
    # СОХРАНЕНИЕ РЕЗУЛЬТАТОВ
    # =============================================================

    results_dir = (
        Path(__file__).parent
        / "results"
    )


    results_dir.mkdir(
        parents=True,
        exist_ok=True
    )


    results_file = args.output or (results_dir / "eval_results.json")
    results_file.parent.mkdir(parents=True, exist_ok=True)


    # =============================================================
    # JSON REPORT
    # =============================================================

    report = {
        "run": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "response_refs": response_refs,
            "replay": bool(args.responses),
            "dataset": str(dataset_path),
            "mode": args.mode,
            "case_ids": [case["id"] for case in eval_cases],
            "quality_gate_config": quality_gate,
        },

        # ---------------------------------------------------------
        # SUMMARY
        # ---------------------------------------------------------

        "summary": {

            "total": total,

            "passed": passed,

            "failed": failed,

            "errors": errors,

            "pass_rate": round(
                pass_rate,
                1
            ),

            "average_score": round(
                average_score,
                2
            ),

            "expected_properties_pass_rate": round(
                expected_properties_pass_rate,
                1
            ),

            "forbidden_behavior_violation_rate": round(
                forbidden_behavior_violation_rate,
                1
            ),

            "overall_status": overall_status
        },


        # ---------------------------------------------------------
        # METRICS
        # ---------------------------------------------------------

        "metrics": {

            "expected_properties": {

                "total":
                    total_expected_properties,

                "passed":
                    passed_expected_properties,

                "pass_rate": round(
                    expected_properties_pass_rate,
                    1
                )
            },


            "forbidden_behavior": {

                "total":
                    total_forbidden_behaviors,

                "violated":
                    violated_forbidden_behaviors,

                "violation_rate": round(
                    forbidden_behavior_violation_rate,
                    1
                )
            }
        },


        # ---------------------------------------------------------
        # QUALITY GATE
        # ---------------------------------------------------------

        "quality_gate": {

            "status": overall_status,

            "criteria": {

                "pass_rate": {
                    "threshold": MIN_PASS_RATE,
                    "actual": round(
                        pass_rate,
                        1
                    ),
                    "passed": pass_rate_gate
                },

                "expected_properties_pass_rate": {
                    "threshold":
                        MIN_EXPECTED_PROPERTIES_PASS_RATE,

                    "actual": round(
                        expected_properties_pass_rate,
                        1
                    ),

                    "passed":
                        expected_properties_gate
                },

                "forbidden_behavior_violation_rate": {
                    "threshold":
                        MAX_FORBIDDEN_BEHAVIOR_VIOLATION_RATE,

                    "actual": round(
                        forbidden_behavior_violation_rate,
                        1
                    ),

                    "passed":
                        forbidden_behavior_gate
                },

                "errors": {
                    "threshold": MAX_ERRORS,
                    "actual": errors,
                    "passed": errors_gate
                }
            }
        },


        # ---------------------------------------------------------
        # EVAL CASE RESULTS
        # ---------------------------------------------------------

        "results": eval_results
    }


    # =============================================================
    # ЗАПИСЬ JSON
    # =============================================================

    with open(
        results_file,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            mask_object(report),
            file,
            ensure_ascii=False,
            indent=2
        )


    print()

    print(
        f"Результаты сохранены: "
        f"{results_file}"
    )

    return 2 if errors else (0 if quality_gate_passed else 1)


def cli():
    try:
        return main()
    except KeyboardInterrupt:
        print('Запуск прерван пользователем (Ctrl+C).')
        return 2
    except (OSError, ValueError, RuntimeError) as error:
        print(f'Ошибка запуска: {mask_sensitive(error)}')
        return 2


if __name__ == "__main__":
    raise SystemExit(cli())
