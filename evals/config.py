"""Shared, validated configuration for evaluation and integration runners."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"


def load_config(path: Path = CONFIG_PATH) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    integration = data.get("integration")
    gate = data.get("quality_gate")
    if not isinstance(integration, dict) or not isinstance(gate, dict):
        raise ValueError("config.json должен содержать integration и quality_gate")
    required_integration = {
        "jira_project", "jira_issue", "issue_type", "priority",
        "qase_project", "qase_suite",
    }
    missing = required_integration - integration.keys()
    if missing:
        raise ValueError(f"В integration отсутствуют поля: {sorted(missing)}")
    required_gate = {
        "min_pass_rate", "min_expected_properties_pass_rate",
        "max_forbidden_behavior_violation_rate", "max_errors",
        "evaluator_timeout_seconds",
    }
    missing = required_gate - gate.keys()
    if missing:
        raise ValueError(f"В quality_gate отсутствуют поля: {sorted(missing)}")
    if not str(integration["jira_issue"]).startswith(f"{integration['jira_project']}-"):
        raise ValueError("jira_issue не соответствует jira_project")
    if int(integration["qase_suite"]) <= 0:
        raise ValueError("qase_suite должен быть положительным числом")
    if int(gate["evaluator_timeout_seconds"]) <= 0:
        raise ValueError("evaluator_timeout_seconds должен быть положительным числом")
    return data
