import tempfile
import unittest
from pathlib import Path

from config import load_config


class ConfigTests(unittest.TestCase):
    def test_project_configuration_is_valid(self):
        config = load_config()
        self.assertEqual(config["integration"]["jira_issue"], "KAN-30")
        self.assertEqual(config["integration"]["qase_suite"], 16)

    def test_invalid_project_mapping_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                '{"integration":{"jira_project":"KAN","jira_issue":"QT-1",'
                '"issue_type":"Task","priority":"High","qase_project":"QT",'
                '"qase_suite":16},"quality_gate":{'
                '"min_pass_rate":100,"min_expected_properties_pass_rate":95,'
                '"max_forbidden_behavior_violation_rate":0,"max_errors":0}}',
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                load_config(path)


if __name__ == "__main__":
    unittest.main()
