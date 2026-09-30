import copy
import json
import subprocess
import unittest
from unittest.mock import patch

from evaluator import evaluate_responses_batch, validate_results


class EvaluatorTests(unittest.TestCase):
    def setUp(self):
        self.case = {'id': 'E1', 'input': {'source': 'confluence', 'page_id': '123'}, 'expected_properties': ['a', 'b'], 'forbidden_behavior': ['c']}
        self.result = {'eval_case_id': 'E1', 'expected_properties': [{'property': x, 'passed': True, 'reason': 'evidence'} for x in ['a', 'b']], 'forbidden_behavior': [{'rule': 'c', 'violated': False, 'reason': 'evidence'}], 'status': 'PASS', 'score': 1.0}

    def validate(self, result):
        return validate_results({'results': [result]}, [self.case])['E1']

    def test_valid_and_singleton(self):
        self.assertEqual(self.validate(self.result)['status'], 'PASS')
        self.assertEqual(validate_results(self.result, [self.case])['E1']['score'], 1)

    def test_local_verdict_overrides_false_pass(self):
        for field, key in [('expected_properties', 'passed'), ('forbidden_behavior', 'violated')]:
            result = copy.deepcopy(self.result)
            result[field][0][key] = key == 'violated'
            checked = self.validate(result)
            self.assertEqual(checked['status'], 'FAIL')
            self.assertEqual(checked['score'], 0)
            self.assertTrue(checked['aggregation_corrected'])

    def test_rejects_bad_criteria(self):
        for change in ['missing', 'duplicate', 'unknown', 'string_bool', 'int_bool', 'reason']:
            with self.subTest(change=change):
                result = copy.deepcopy(self.result)
                items = result['expected_properties']
                if change == 'missing': items.pop()
                if change == 'duplicate': items[1] = items[0]
                if change == 'unknown': items[0]['property'] = 'other'
                if change == 'string_bool': items[0]['passed'] = 'false'
                if change == 'int_bool': items[0]['passed'] = 1
                if change == 'reason': items[0]['reason'] = ' '
                with self.assertRaises(RuntimeError): self.validate(result)

    def test_rejects_bad_case_sets(self):
        for results in [[], [self.result, self.result], [None], [dict(self.result, eval_case_id='other')]]:
            with self.subTest(results=results), self.assertRaises(RuntimeError):
                validate_results({'results': results}, [self.case])

    @patch('evaluator.subprocess.Popen')
    def test_invalid_json(self, popen):
        popen.return_value.communicate.return_value = (json.dumps({'type': 'text', 'part': {'text': '{broken'}}), '')
        popen.return_value.returncode = 0
        with self.assertRaisesRegex(RuntimeError, 'невалидный JSON'):
            evaluate_responses_batch([self.case], 'answer')

    @patch('evaluator.subprocess.Popen')
    def test_timeout_kills_and_reaps(self, popen):
        process = popen.return_value
        process.communicate.side_effect = [subprocess.TimeoutExpired('opencode', 1), ('', '')]
        with patch('process_control.os.killpg') as kill, patch('process_control.time.monotonic', side_effect=[0, 0, 2]), self.assertRaisesRegex(RuntimeError, 'timeout'):
            evaluate_responses_batch([self.case], 'answer', timeout_seconds=1)
        kill.assert_called_once()
        self.assertEqual(process.communicate.call_count, 2)

    @patch('evaluator.subprocess.Popen')
    def test_nonzero_exit_preserves_stderr(self, popen):
        popen.return_value.communicate.return_value = ('', 'provider unavailable')
        popen.return_value.returncode = 1
        with self.assertRaisesRegex(RuntimeError, 'provider unavailable'):
            evaluate_responses_batch([self.case], 'answer')
