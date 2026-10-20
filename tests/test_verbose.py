import contextlib
import io
import subprocess
import unittest
from unittest.mock import patch
from scripts import grot


class VerboseTests(unittest.TestCase):
    def test_all_commands_report_start_and_finish_without_private_data(self):
        for tool, action in [('kubectl', 'get'), ('helm', 'upgrade'), ('docker', 'compose'), ('gcx', 'metrics')]:
            result = subprocess.CompletedProcess([], 0, 'private-output', 'private-error')
            with patch.object(grot, 'VERBOSE', True), patch.object(grot.subprocess, 'run', return_value=result), contextlib.redirect_stderr(io.StringIO()) as output:
                self.assertEqual('private-output', grot.run([tool, action, 'private-argument'], data='private-input'))
            text = output.getvalue()
            self.assertIn(tool + ' ' + action + ' — starting', text)
            self.assertIn('exit 0', text)
            for private in ('private-output', 'private-error', 'private-argument', 'private-input'):
                self.assertNotIn(private, text)

    def test_default_has_no_verbose_output(self):
        with patch.object(grot, 'VERBOSE', False), patch.object(grot.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')), contextlib.redirect_stderr(io.StringIO()) as output:
            grot.run(['kubectl', 'get', 'pods'])
        self.assertEqual('', output.getvalue())

    def test_verbose_flag_before_or_after_subcommand(self):
        for argv in [['grot', '--verbose', 'verify', 'demo'], ['grot', 'verify', 'demo', '-v']]:
            with patch.object(grot, 'VERBOSE', False), patch.object(grot.sys, 'argv', argv), patch.object(grot, 'profile_path'), patch.object(grot, 'verify') as verify, contextlib.redirect_stderr(io.StringIO()):
                grot.main()
                self.assertTrue(grot.VERBOSE)
                verify.assert_called_once()

    def test_failure_is_reported_without_captured_output(self):
        with patch.object(grot, 'VERBOSE', True), patch.object(grot.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, 'private-output', 'private-error')), contextlib.redirect_stderr(io.StringIO()) as output, self.assertRaises(grot.SafeError):
            grot.run(['kubectl', 'get', 'secret'])
        self.assertIn('exit 1', output.getvalue())
        self.assertNotIn('private-error', output.getvalue())


if __name__ == '__main__': unittest.main()
