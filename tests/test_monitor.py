import os
import signal
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

import monitor


class ProcessTests(unittest.TestCase):
    def test_name_with_parentheses_and_spaces(self):
        fields = ['S'] + ['0'] * 21
        fields[11], fields[12], fields[19], fields[21] = '17', '3', '123456', '10'
        process = monitor.parse_process('42 (worker (pool)) ' + ' '.join(fields), 1000)
        self.assertEqual(process.name, 'worker (pool)')
        self.assertEqual(process.identity, (42, 123456))
        self.assertEqual(process.ticks, 20)
        self.assertEqual(process.rss, 10 * os.sysconf('SC_PAGE_SIZE'))

    def test_reused_pid_is_rejected_and_descriptor_closed(self):
        original = monitor.Process(123, 'old', 'S', 0, 10, 0, 1000)
        replacement = monitor.Process(123, 'new', 'S', 0, 20, 0, 1000)
        with patch('os.pidfd_open', return_value=99), patch('os.close') as close, \
                patch('monitor.read_process', return_value=replacement), \
                patch('signal.pidfd_send_signal') as send:
            with self.assertRaises(ProcessLookupError):
                monitor.send_action(original, 't')
            send.assert_not_called()
            close.assert_called_once_with(99)

    def test_protected_processes(self):
        for pid in (1, os.getpid()):
            with self.assertRaises(ValueError):
                monitor.send_action(monitor.Process(pid, 'protected', 'S', 0, 1, 0, 0), 'K')

    def test_permission_failure_propagates_and_closes_descriptor(self):
        process = monitor.Process(123, 'worker', 'S', 0, 10, 0, 1000)
        with patch('os.pidfd_open', return_value=99), patch('os.close') as close, \
                patch('monitor.read_process', return_value=process), \
                patch('signal.pidfd_send_signal', side_effect=PermissionError('Denied')):
            with self.assertRaises(PermissionError):
                monitor.send_action(process, 's')
            close.assert_called_once_with(99)

    def test_real_child_suspend_resume_terminate(self):
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
        try:
            process = monitor.read_process(child.pid)
            monitor.send_action(process, 's')
            self.wait_state(child.pid, {'T', 't'})
            monitor.send_action(process, 'r')
            self.wait_state(child.pid, {'R', 'S'})
            monitor.send_action(process, 't')
            self.assertEqual(child.wait(timeout=3), -signal.SIGTERM)
        finally:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=3)

    def wait_state(self, pid, states):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if monitor.read_process(pid).state in states:
                return
            time.sleep(0.01)
        self.fail(f'PID {pid} did not enter {states}')


class SamplerTests(unittest.TestCase):
    def test_real_samples(self):
        sampler = monitor.Sampler()
        first = sampler.sample()
        time.sleep(0.05)
        second = sampler.sample()
        self.assertTrue(first['processes'])
        self.assertTrue(second['storage'])
        self.assertGreater(second['memory']['MemTotal'], 0)
        self.assertTrue(all(0 <= value <= 100 for value in second['cpus'].values()))
        self.assertTrue(any(process.pid == os.getpid() for process in second['processes']))
        self.assertEqual(second['errors'], [])

    def test_terminal_controls_are_not_rendered(self):
        self.assertEqual(monitor.safe_text('name\x1b[31m\n'), 'name?[31m?')


class ConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.dashboard = monitor.Dashboard(None, 1)
        self.process = monitor.Process(123, 'worker', 'S', 0, 10, 0, 1000)
        self.dashboard.tab = 1
        self.dashboard.filtered = [self.process]

    def test_action_requires_confirmation_and_stays_bound_to_target(self):
        with patch('monitor.send_action') as send:
            self.dashboard.key('t')
            send.assert_not_called()
            self.dashboard.filtered = [monitor.Process(456, 'other', 'S', 0, 20, 0, 1000)]
            self.dashboard.key('y')
            send.assert_called_once_with(self.process, 't')
            self.assertIsNone(self.dashboard.pending)

    def test_cancel_does_not_send_signal(self):
        with patch('monitor.send_action') as send:
            self.dashboard.key('K')
            self.dashboard.key('q')
            send.assert_not_called()
            self.assertIsNone(self.dashboard.pending)

    def test_action_failure_is_visible(self):
        with patch('monitor.send_action', side_effect=PermissionError('Denied')):
            self.dashboard.key('s')
            self.dashboard.key('y')
            self.assertEqual(self.dashboard.message, 'Action failed: Denied')


if __name__ == '__main__':
    unittest.main()
