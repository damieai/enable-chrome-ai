from contextlib import redirect_stdout, redirect_stderr
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import main


VERSION = '154.0.8037.98'


def sample_state():
    # Synthetic data: never embed real Local State credentials or identifiers.
    return {
        'profile': {'info_cache': {
            'Default': {'is_glic_eligible': False, 'is_managed': 0},
            'Profile 1': {'is_glic_eligible': False, 'is_managed': 1},
            'Profile 2': {'is_glic_eligible': True, 'is_managed': 0},
        }},
        'variations_country': 'cn',
        'variations_permanent_consistency_country': [VERSION, 'us'],
        'variations_safe_seed_permanent_consistency_country': 'cn',
        'variations_safe_seed_session_consistency_country': 'cn',
        'variations_seed_signature': 'synthetic-signature',
        'intl': {'app_locale': 'zh-CN'},
        'os_crypt': {'encrypted_key': 'synthetic-only'},
        'browser': {'enabled_labs_experiments': ['unrelated-flag@2']},
        'unrelated': {'is_glic_eligible': False},
    }


class PatchTests(unittest.TestCase):
    def test_user_configuration_shape_and_unrelated_data(self):
        state = sample_state()
        original = deepcopy(state)
        result, changes = main.build_patch(state, VERSION)
        self.assertEqual(state, original)
        self.assertEqual(len(changes), 4)
        self.assertEqual(result['variations_permanent_overridden_country'], 'us')
        self.assertEqual(result['variations_country'], 'us')
        for entry in result['profile']['info_cache'].values():
            self.assertIs(entry['is_glic_eligible'], True)
        for key in ('intl', 'os_crypt', 'browser', 'unrelated', 'variations_seed_signature',
                    'variations_safe_seed_permanent_consistency_country',
                    'variations_safe_seed_session_consistency_country'):
            self.assertEqual(result[key], original[key])
        self.assertEqual(result['profile']['info_cache']['Profile 1']['is_managed'], 1)
        self.assertEqual(main.build_patch(result, VERSION), (result, []))

    def test_missing_and_malformed_country_cache_is_repaired(self):
        for old in (None, [], 'cn', [VERSION], [VERSION, 'cn', 'extra'], 123):
            with self.subTest(old=old):
                result, _ = main.build_patch({'variations_permanent_consistency_country': old}, VERSION)
                self.assertEqual(result['variations_permanent_consistency_country'], [VERSION, 'us'])
        result, _ = main.build_patch({}, VERSION)
        self.assertEqual(result['variations_permanent_consistency_country'], [VERSION, 'us'])

    def test_missing_profile_eligibility_added_and_numeric_true_corrected(self):
        result, _ = main.build_patch({'profile': {'info_cache': {'Default': {},
            'Profile 1': {'is_glic_eligible': 1}}}}, VERSION)
        for entry in result['profile']['info_cache'].values():
            self.assertIs(entry['is_glic_eligible'], True)

    def test_missing_version_still_sets_permanent_override(self):
        result, _ = main.build_patch({}, None)
        self.assertEqual(result['variations_permanent_overridden_country'], 'us')
        self.assertNotIn('variations_permanent_consistency_country', result)

    def test_invalid_profile_structure_rejected(self):
        for state in ({'profile': []}, {'profile': {'info_cache': []}},
                      {'profile': {'info_cache': {'Default': None}}}):
            with self.subTest(state=state), self.assertRaises(ValueError):
                main.build_patch(state, VERSION)


class FileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'Local State'
        self.original = json.dumps(sample_state(), indent=2).encode()
        self.path.write_bytes(self.original)
        (self.root / 'Last Version').write_text(VERSION + '\r\n')
        self.output = io.StringIO()
        self.out = redirect_stdout(self.output)
        self.out.__enter__()
        self.addCleanup(self.out.__exit__, None, None, None)
        self.err = redirect_stderr(self.output)
        self.err.__enter__()
        self.addCleanup(self.err.__exit__, None, None, None)

    def test_version_whitespace_and_invalid_version(self):
        self.assertEqual(main.get_last_version(self.root), VERSION)
        (self.root / 'Last Version').write_text('invalid')
        self.assertIsNone(main.get_last_version(self.root))
        (self.root / 'Last Version').unlink()
        self.assertIsNone(main.get_last_version(self.root))

    @patch('main.chrome_processes', return_value=[])
    def test_backup_exact_bytes_verification_and_idempotence(self, _):
        self.assertTrue(main.patch_local_state(self.root, VERSION))
        backups = list(self.root.glob('Local State.backup-*'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), self.original)
        self.assertEqual(main.read_local_state(self.path)[1]['variations_country'], 'us')
        self.assertFalse(main.patch_local_state(self.root, VERSION))
        self.assertEqual(len(list(self.root.glob('Local State.backup-*'))), 1)
        self.assertFalse(list(self.root.glob('.Local-State-*')))

    @patch('main.os.replace', side_effect=PermissionError('locked'))
    def test_replace_failure_preserves_original_and_cleans_temp(self, _):
        with self.assertRaises(PermissionError):
            main.write_local_state(self.path, self.original, {'new': True})
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertFalse(list(self.root.glob('.Local-State-*')))
        self.assertEqual(len(list(self.root.glob('Local State.backup-*'))), 1)

    def test_concurrent_write_is_not_overwritten(self):
        self.path.write_bytes(b'{"updated_by_chrome":true}')
        with self.assertRaisesRegex(RuntimeError, 'changed during patching'):
            main.write_local_state(self.path, self.original, {'new': True})
        self.assertEqual(self.path.read_bytes(), b'{"updated_by_chrome":true}')
        self.assertFalse(list(self.root.glob('Local State.backup-*')))

    def test_write_during_backup_is_detected(self):
        real_copymode = main.shutil.copymode

        def changed(source, target):
            real_copymode(source, target)
            self.path.write_bytes(b'{"newer":true}')

        with patch('main.shutil.copymode', side_effect=changed):
            with self.assertRaisesRegex(RuntimeError, 'changed during patching'):
                main.write_local_state(self.path, self.original, {'new': True})
        self.assertEqual(self.path.read_bytes(), b'{"newer":true}')
        self.assertFalse(list(self.root.glob('.Local-State-*')))

    @patch('main.shutdown_chrome')
    @patch('main.subprocess.Popen')
    def test_read_only_modes_do_not_close_launch_or_write(self, launch, close):
        for option, expected in (('--dry-run', 0), ('--check', 1)):
            self.assertEqual(main.main(['--user-data-dir', str(self.root), option]), expected)
        close.assert_not_called()
        launch.assert_not_called()
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertFalse(list(self.root.glob('Local State.backup-*')))

    @patch('main.chrome_processes', return_value=[])
    def test_apply_then_check_cli_and_missing_version(self, _):
        (self.root / 'Last Version').unlink()
        args = ['--user-data-dir', str(self.root)]
        self.assertEqual(main.main([*args, '--no-close']), 0)
        self.assertEqual(main.main([*args, '--check']), 0)

    @patch('main.chrome_processes', return_value=[Mock()])
    def test_no_close_refuses_running_browser(self, _):
        self.assertEqual(main.main(['--user-data-dir', str(self.root), '--no-close']), 1)
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertFalse(list(self.root.glob('Local State.backup-*')))

    @patch('main.shutdown_chrome')
    def test_malformed_file_rejected_before_browser_shutdown(self, close):
        for content in (b'{broken', b'[]', b'\xff'):
            self.path.write_bytes(content)
            self.assertEqual(main.main(['--user-data-dir', str(self.root)]), 1)
            self.assertEqual(self.path.read_bytes(), content)
        close.assert_not_called()

    @patch('main.chrome_processes', return_value=[])
    @patch('main.subprocess.Popen')
    def test_restart_even_after_patch_failure_and_retain_arguments(self, launch, _):
        argv = ['chrome.exe', '--user-data-dir=custom', '--profile-directory=Profile 1']
        def close(commands):
            commands.append(main.ChromeCommand(argv, str(self.root)))
        with patch('main.shutdown_chrome', side_effect=close), \
             patch('main.patch_local_state', side_effect=PermissionError('locked')):
            self.assertEqual(main.main(['--user-data-dir', str(self.root), '--restart-country']), 1)
        self.assertEqual(launch.call_args.args[0], [argv[0], '--variations-override-country=us', *argv[1:]])
        self.assertEqual(launch.call_args.kwargs['cwd'], str(self.root))


class ProcessTests(unittest.TestCase):
    def process(self, pid, parent, args, name='chrome.exe', owner='test-user'):
        result = Mock(pid=pid)
        result.ppid.return_value = parent
        result.cmdline.return_value = args
        result.name.return_value = name
        result.username.return_value = owner
        result.exe.return_value = args[0]
        result.cwd.return_value = '/tmp'
        return result

    def test_shutdown_waits_for_children_and_only_restarts_browser(self):
        browser = self.process(101, 1, ['chrome.exe', '--profile-directory=Default'])
        helper = self.process(102, 101, ['chrome.exe', '--type=renderer'])
        commands = []
        with patch('main.chrome_processes', side_effect=[[browser, helper], []]), \
             patch('main.psutil.wait_procs', side_effect=[([browser], [helper]), ([helper], [])]) as wait:
            main.shutdown_chrome(commands)
        browser.terminate.assert_called_once()
        helper.terminate.assert_not_called()
        helper.kill.assert_called_once()
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0].argv, browser.cmdline())
        self.assertEqual(wait.call_count, 2)

    def test_shutdown_timeout_aborts(self):
        browser = self.process(101, 1, ['chrome.exe'])
        with patch('main.chrome_processes', return_value=[browser]), \
             patch('main.psutil.wait_procs', return_value=([], [browser])), \
             self.assertRaisesRegex(RuntimeError, 'did not exit'):
            main.shutdown_chrome([])

    def test_other_users_and_other_browsers_excluded(self):
        owned = self.process(101, 1, ['chrome.exe'])
        foreign = self.process(102, 1, ['chrome.exe'], owner='other-user')
        edge = self.process(103, 1, ['msedge.exe'], name='msedge.exe')
        current = Mock()
        current.username.return_value = 'test-user'
        with patch('main.psutil.Process', return_value=current), \
             patch('main.psutil.process_iter', return_value=[owned, foreign, edge]):
            self.assertEqual(main.chrome_processes(), [owned])

    def test_restart_override_replaces_both_syntaxes_without_losing_other_args(self):
        argv = ['chrome.exe', '--variations-override-country', 'cn', '--user-data-dir=C:/Custom',
                '--variations-override-country=gb', '--profile-directory=Profile 1']
        self.assertEqual(main.restart_argv(argv, True), ['chrome.exe', '--variations-override-country=us',
                         '--user-data-dir=C:/Custom', '--profile-directory=Profile 1'])
        self.assertEqual(main.restart_argv(argv), argv)

    def test_windows_uses_localappdata(self):
        with tempfile.TemporaryDirectory() as folder:
            expected = Path(folder) / 'Google/Chrome/User Data'
            expected.mkdir(parents=True)
            with patch.object(main.sys, 'platform', 'win32'), \
                 patch.dict(os.environ, {'LOCALAPPDATA': folder}):
                self.assertEqual(main.get_version_and_user_data_path(), {'stable': str(expected.resolve())})


if __name__ == '__main__':
    unittest.main()
