import argparse
import contextlib
import io
import subprocess
import unittest
from unittest.mock import MagicMock, patch
from scripts import grot
from tests.test_destination_workflow import FakeCluster, fixture


class BrowserAccessTests(unittest.TestCase):
    def setUp(self):
        infrastructure = patch.object(grot, 'setup_infrastructure')
        infrastructure.start(); self.addCleanup(infrastructure.stop)
        self.args = argparse.Namespace(destination='demo', context='test', namespace='grot-demo', port=8080,
            image_prefix='example.invalid/grot', image_tag='test', mode='quick', settings_stdin=False,
            pull_secret=None, no_open=False)

    def test_interactive_install_opens_browser_unless_disabled(self):
        for interactive, stdin_settings, disabled, expected in [
            (True, False, False, True), (True, False, True, False),
            (False, False, False, False), (True, True, False, False)]:
            self.args.settings_stdin, self.args.no_open = stdin_settings, disabled
            with patch.object(grot, 'verify_k8s') as verify, patch.object(grot, 'run', side_effect=FakeCluster()), patch.object(grot, 'settings', return_value=fixture()), patch.object(grot.sys.stdin, 'isatty', return_value=interactive), patch.object(grot, 'open_app') as opened, contextlib.redirect_stdout(io.StringIO()):
                grot.k8s(self.args)
            verify.assert_called_once_with(self.args, show_access=False)
            self.assertEqual(expected, opened.called)

    def test_verification_precedes_browser_access(self):
        sequence = []
        with patch.object(grot, 'run', side_effect=FakeCluster()), patch.object(grot, 'settings', return_value=fixture()), patch.object(grot.sys.stdin, 'isatty', return_value=True), patch.object(grot, 'verify_k8s', side_effect=lambda *a, **kw: sequence.append('verify')), patch.object(grot, 'open_app', side_effect=lambda *a, **kw: sequence.append('open')), contextlib.redirect_stdout(io.StringIO()):
            grot.k8s(self.args)
        self.assertEqual(['verify', 'open'], sequence)

    def test_verification_failure_prevents_browser_and_success_summary(self):
        with patch.object(grot, 'run', side_effect=FakeCluster()), patch.object(grot, 'settings', return_value=fixture()), patch.object(grot.sys.stdin, 'isatty', return_value=True), patch.object(grot, 'verify_k8s', side_effect=grot.SafeError('probe failed')), patch.object(grot, 'open_app') as opened, contextlib.redirect_stdout(io.StringIO()) as output, self.assertRaisesRegex(grot.SafeError, 'Deployed, but verification failed'):
            grot.k8s(self.args)
        opened.assert_not_called()
        self.assertNotIn('Ready: destination=', output.getvalue())

    def test_ready_tunnel_opens_browser_and_ctrl_c_cleans_up(self):
        process = MagicMock()
        process.poll.return_value = None
        process.wait.side_effect = [KeyboardInterrupt, 0]
        response = MagicMock()
        response.__enter__.return_value.status = 200
        with patch.object(grot.socket, 'socket'), patch.object(grot.subprocess, 'Popen', return_value=process) as start, patch.object(grot, 'urlopen', return_value=response), patch.object(grot.webbrowser, 'open', return_value=True) as browser, contextlib.redirect_stdout(io.StringIO()) as output:
            grot.open_app(self.args, verified=True)
        self.assertIn('Verification: PASSED', output.getvalue())
        self.assertIn('App URL: http://localhost:8080 — port-forward is running.', output.getvalue())
        browser.assert_called_once_with('http://localhost:8080')
        self.assertIn('--address=127.0.0.1', start.call_args.args[0])
        process.terminate.assert_called_once()
        self.assertIn('Grot is still running', output.getvalue())

    def test_busy_port_never_starts_tunnel_or_opens_browser(self):
        sock = MagicMock()
        sock.__enter__.return_value.bind.side_effect = OSError('private detail')
        with patch.object(grot.socket, 'socket', return_value=sock), patch.object(grot.subprocess, 'Popen') as start, patch.object(grot.webbrowser, 'open') as browser, self.assertRaisesRegex(grot.SafeError, 'already in use'):
            grot.open_app(self.args)
        start.assert_not_called(); browser.assert_not_called()

    def test_failed_tunnel_does_not_open_browser(self):
        process = MagicMock(); process.poll.return_value = 1
        with patch.object(grot.socket, 'socket'), patch.object(grot.subprocess, 'Popen', return_value=process), patch.object(grot.webbrowser, 'open') as browser, contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(grot.SafeError, 'tunnel failed'):
            grot.open_app(self.args)
        browser.assert_not_called()

    def test_invalid_port_is_rejected(self):
        self.args.port = 65536
        with self.assertRaises(grot.SafeError): grot.open_app(self.args)


if __name__ == '__main__': unittest.main()
