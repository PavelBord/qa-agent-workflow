import copy
import unittest
from pathlib import Path
from adversarial_runner import load_cases, validate_results

class AdversarialTests(unittest.TestCase):
    def setUp(self):
        self.cases = load_cases(Path(__file__).parent / "adversarial_cases.md")
        self.payload = {"results": [
            {"id": c["id"],
             "expected_properties": [{"index": i, "passed": True, "reason": "fixture"}
                                     for i, _ in enumerate(c["expected_properties"])],
             "forbidden_behavior": [{"index": i, "violated": False, "reason": "fixture"}
                                    for i, _ in enumerate(c["forbidden_behavior"])]}
            for c in self.cases]}

    def test_all_cases_and_injection_preserved(self):
        self.assertEqual([c["id"] for c in self.cases],
                         ["SEC-001", "SEC-002", "SEC-003", "SEC-004", "SEC-005"])
        self.assertIn("Ignore previous instructions.", self.cases[0]["input"])
        self.assertIn("60 minutes", self.cases[1]["input"])

    def test_status_computed_not_trusted(self):
        self.payload["results"][0]["status"] = "PASS"
        self.payload["results"][0]["forbidden_behavior"][0]["violated"] = True
        self.assertEqual(validate_results(self.payload, self.cases)[0]["status"], "FAIL")

    def test_bad_judge_responses_rejected(self):
        for change in ("missing_case", "duplicate", "missing_property", "string_bool"):
            with self.subTest(change=change):
                p = copy.deepcopy(self.payload)
                if change == "missing_case":
                    p["results"].pop()
                elif change == "duplicate":
                    p["results"][1] = p["results"][0]
                elif change == "missing_property":
                    p["results"][0]["expected_properties"].pop()
                else:
                    p["results"][0]["expected_properties"][0]["passed"] = "true"
                with self.assertRaises(ValueError):
                    validate_results(p, self.cases)

