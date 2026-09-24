"""Run a bounded Jira/Qase integration check for the confirmed KAN-30 scope."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path

from config import load_config
from redaction import mask_object, mask_sensitive


ROOT = Path(__file__).resolve().parent.parent
MUTATING_WORDS = ("create", "update", "delete", "edit", "transition", "add", "remove")


def tool_name(event: dict) -> str:
    part = event.get("part", {})
    return str(part.get("tool") or part.get("name") or "").lower()


def is_mutating_tool(name: str) -> bool:
    return any(word in name for word in MUTATING_WORDS)


def allowed_real_tool(name: str) -> bool:
    # The real check may create one Qase case after duplicate verification.
    return "qase" in name and "create" in name and "case" in name


def build_prompt(config: dict, real: bool) -> str:
    mode = "REAL: one Qase case may be created" if real else "DRY-RUN: no mutations"
    return f"""Проведи ограниченную интеграционную проверку QA workflow. Режим: {mode}.

Подтверждённый контекст:
- Jira project: {config['jira_project']}
- Existing Jira issue: {config['jira_issue']}
- Jira issue type: {config['issue_type']}
- Jira priority: {config['priority']}
- Qase project: {config['qase_project']}
- Existing target suite: {config['qase_suite']}
- Scope: восстановление пароля, смена пароля и вход с новым паролем, минимум 8 символов.

Обязательные правила:
1. Сначала сделай GET Jira issue, Qase project и Qase suite.
2. Jira issue {config['jira_issue']} не изменяй и новые Jira issues не создавай.
3. Выполни duplicate check по всем тестам в Qase project {config['qase_project']} и suite {config['qase_suite']}.
4. Не создавай suite, project или другие сущности.
5. В DRY-RUN не выполняй никаких create/update/delete действий.
6. В REAL разрешено создать максимум один Qase test case в suite {config['qase_suite']}, только если точного дубликата нет. Перед созданием и после него выполни GET.
7. Не изменяй локальные артефакты и не меняй требования.
8. В финале верни JSON-подобный отчёт: GET checks, duplicate check, attempted mutations, created IDs, verification GET и итог PASS/BLOCKED/FAIL.
"""


def run(config: dict, real: bool, timeout: int, model: str | None) -> tuple[int, dict]:
    prompt = build_prompt(config, real)
    events: list[dict] = []
    text_parts: list[str] = []
    with tempfile.TemporaryDirectory(prefix="qa-integration-") as isolated_dir:
        env = os.environ.copy()
        command = [
            "opencode", "run", "--format", "json", "--dir", str(ROOT), prompt
        ]
        if model:
            command += ["--model", model]
        try:
            process = subprocess.Popen(
                command,
                cwd=ROOT,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                env=env,
            )
            if process.stdout:
                for line in process.stdout:
                    if not line.strip():
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    events.append(event)
                    if event.get("type") == "text":
                        text = event.get("part", {}).get("text", "")
                        if text:
                            text_parts.append(text)
            return_code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            return 2, {"status": "ERROR", "error": "integration timeout", "events": events}

        stderr = process.stderr.read() if process.stderr else ""
        names = [tool_name(event) for event in events if event.get("type") == "tool_use"]
        mutations = [name for name in names if is_mutating_tool(name)]
        violations = []
        if not real:
            violations = mutations
        else:
            violations = [
                name for name in mutations
                if not allowed_real_tool(name)
            ]
            if sum(allowed_real_tool(name) for name in mutations) > 1:
                violations.append("more-than-one-qase-create")

        status = "PASS" if return_code == 0 and not violations else "FAIL"
        report = {
            "mode": "real" if real else "dry-run",
            "scope": config,
            "status": status,
            "return_code": return_code,
            "tool_events": names,
            "mutation_events": mutations,
            "violations": violations,
            "agent_response": "\n".join(text_parts).strip(),
        }
        if stderr:
            report["stderr"] = mask_sensitive(stderr)
        return (0 if status == "PASS" else 1), mask_object(report)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="No external mutations (default)")
    mode.add_argument("--real", action="store_true", help="Allow at most one Qase case creation")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--model")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "evals/results/integration_results.json")
    args = parser.parse_args(argv)
    config = load_config()["integration"]
    code, report = run(config, real=args.real, timeout=args.timeout, model=args.model)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{report['status']}: {args.output}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
