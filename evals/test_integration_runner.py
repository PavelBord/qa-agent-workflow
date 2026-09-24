import unittest

from integration_runner import allowed_real_tool, is_mutating_tool


class IntegrationRunnerTests(unittest.TestCase):
    def test_mutation_detection(self):
        self.assertTrue(is_mutating_tool("qase_create_case"))
        self.assertTrue(is_mutating_tool("jira_create_issue"))
        self.assertFalse(is_mutating_tool("jira_get_issue"))

    def test_real_allowlist_only_qase_case(self):
        self.assertTrue(allowed_real_tool("qase_create_case"))
        self.assertFalse(allowed_real_tool("qase_create_suite"))
        self.assertFalse(allowed_real_tool("jira_create_issue"))


if __name__ == "__main__":
    unittest.main()
