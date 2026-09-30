import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import eval_runner
from response_store import load_response, save_response


class ResponseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.case = {'id': 'EVAL-001', 'input': {'source': 'confluence', 'page_id': '123', 'task': 'Review'}, 'expected_properties': ['a'], 'forbidden_behavior': ['b']}

    def test_masks_and_preserves_history(self):
        first = save_response(self.root, '123', [self.case], 'user@example.com token=private')
        second = save_response(self.root, '123', [self.case], 'second')
        self.assertNotEqual(first, second)
        self.assertNotIn('private', first.read_text())
        self.assertNotIn('user@example.com', load_response(first, [self.case]))

    def test_rejects_changed_case_or_corrupt_response(self):
        path = save_response(self.root, '123', [self.case], 'answer')
        changed = dict(self.case, expected_properties=['changed'])
        with self.assertRaises(ValueError):
            load_response(path, [changed])
        payload = json.loads(path.read_text())
        payload['response'] = 'tampered'
        path.write_text(json.dumps(payload))
        with self.assertRaises(ValueError):
            load_response(path, [self.case])

    def test_replay_calls_only_evaluator_and_reports_failure(self):
        path = save_response(self.root, '123', [self.case], 'answer')
        dataset = self.root / 'dataset.json'
        dataset.write_text(json.dumps([self.case]))
        report = self.root / 'report.json'
        argv = ['eval_runner', '--dataset', str(dataset), '--responses', str(path), '--output', str(report)]
        with patch('sys.argv', argv), patch('eval_runner.subprocess.Popen') as agent, patch('eval_runner.evaluate_responses_batch', side_effect=RuntimeError('judge timeout')) as judge, contextlib.redirect_stdout(io.StringIO()):
            eval_runner.main()
        agent.assert_not_called()
        judge.assert_called_once()
        result = json.loads(report.read_text())
        self.assertTrue(result['run']['replay'])
        self.assertEqual(result['summary']['errors'], 1)
        self.assertEqual(load_response(path, [self.case]), 'answer')

    def test_live_answer_saved_before_evaluator_failure(self):
        dataset = self.root / 'dataset.json'
        dataset.write_text(json.dumps([self.case]))
        report = self.root / 'report.json'
        argv = ['eval_runner', '--dataset', str(dataset), '--output', str(report)]
        def save_locally(directory, page_id, cases, response):
            return save_response(self.root / 'responses', page_id, cases, response)
        def failed_judge(*args, **kwargs):
            self.assertEqual(len(list((self.root / 'responses').glob('*.json'))), 1)
            raise RuntimeError('timeout')
        with patch('sys.argv', argv), patch('eval_runner.subprocess.Popen') as agent, patch('eval_runner.save_response', side_effect=save_locally), patch('eval_runner.evaluate_responses_batch', side_effect=failed_judge), contextlib.redirect_stdout(io.StringIO()):
            agent.return_value.communicate.return_value = (json.dumps({'type': 'text', 'part': {'text': 'answer'}}), '')
            agent.return_value.returncode = 0
            eval_runner.main()
        result = json.loads(report.read_text())
        self.assertEqual(result['summary']['errors'], 1)
        self.assertEqual(load_response(result['run']['response_refs'][0], [self.case]), 'answer')

    def test_exit_codes_for_pass_fail_and_interruption(self):
        from process_control import RunInterrupted
        checkpoint = save_response(self.root, '123', [self.case], 'answer')
        dataset = self.root / 'dataset.json'
        dataset.write_text(json.dumps([self.case]))
        for status, expected_code in [('PASS', 0), ('FAIL', 1), ('interrupt', 2)]:
            with self.subTest(status=status):
                report = self.root / f'{status}.json'
                argv = ['runner', '--dataset', str(dataset), '--responses', str(checkpoint), '--output', str(report)]
                result = {'EVAL-001': {'status': status, 'score': 1 if status == 'PASS' else 0, 'expected_properties': [{'passed': status == 'PASS'}], 'forbidden_behavior': [{'violated': False}]}}
                with patch('sys.argv', argv), patch('eval_runner.evaluate_responses_batch') as judge, contextlib.redirect_stdout(io.StringIO()):
                    if status == 'interrupt':
                        judge.side_effect = RunInterrupted('Ctrl+C')
                    else:
                        judge.return_value = result
                    self.assertEqual(eval_runner.cli(), expected_code)
                self.assertTrue(report.exists())

    def test_agent_interruption_saved_in_report(self):
        from process_control import RunInterrupted
        dataset = self.root / 'dataset.json'
        dataset.write_text(json.dumps([self.case]))
        report = self.root / 'interrupt.json'
        with patch('sys.argv', ['runner', '--dataset', str(dataset), '--output', str(report)]), patch('eval_runner.subprocess.Popen'), patch('eval_runner.wait_for_process', side_effect=RunInterrupted('Ctrl+C')), patch('eval_runner.evaluate_responses_batch') as judge, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(eval_runner.cli(), 2)
        judge.assert_not_called()
        self.assertIn('Ctrl+C', json.loads(report.read_text())['results'][0]['error'])


if __name__ == '__main__':
    unittest.main()
