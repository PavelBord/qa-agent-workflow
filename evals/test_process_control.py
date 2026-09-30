import contextlib
import io
import signal
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

from process_control import RunInterrupted, wait_for_process


class ProcessTests(unittest.TestCase):
    def test_real_timeout(self):
        process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        with self.assertRaisesRegex(RuntimeError, 'timeout'):
            wait_for_process(process, 0.1, 'test')
        self.assertIsNotNone(process.poll())

    def test_ctrl_c_stops_group_and_reaps(self):
        process = Mock(pid=123)
        process.communicate.side_effect = [KeyboardInterrupt(), ('', '')]
        with patch('process_control.os.killpg') as kill, self.assertRaises(RunInterrupted):
            wait_for_process(process, 20, 'test')
        kill.assert_called_once_with(123, signal.SIGKILL)
        self.assertEqual(process.communicate.call_count, 2)

    def test_progress_then_success(self):
        process = Mock()
        process.communicate.side_effect = [subprocess.TimeoutExpired('test', 15), ('answer', '')]
        output = io.StringIO()
        with patch('process_control.time.monotonic', side_effect=[0, 0, 15, 15]), contextlib.redirect_stdout(output):
            result = wait_for_process(process, 30, 'Evaluator')
        self.assertEqual(result, ('answer', ''))
        self.assertIn('15 с / 30 с', output.getvalue())
