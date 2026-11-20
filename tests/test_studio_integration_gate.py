"""No-network regression coverage for Studio integration history preflight."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'check-studio-integration.py'
spec = importlib.util.spec_from_file_location('integration_gate', SCRIPT)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class IntegrationGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git('init', '-q')
        self.git('config', 'user.name', 'Test')
        self.git('config', 'user.email', 'test@example.invalid')
        self.commit('initial')
        self.git('branch', '-M', 'base')

    def git(self, *args):
        return subprocess.run(['git', *args], cwd=self.root, text=True,
                              capture_output=True, check=True).stdout.strip()

    def commit(self, message):
        (self.root / 'sample.txt').write_text(message)
        self.git('add', 'sample.txt')
        self.git('commit', '-qm', message)

    def test_up_to_date_feature_is_accepted(self):
        self.git('switch', '-qc', 'feature')
        self.commit('feature change')
        result = gate.inspect('base', 'feature', self.root)
        self.assertEqual((result['ahead'], result['behind']), (1, 0))
        self.assertEqual(result['files'], ['sample.txt'])

    def test_diverged_feature_is_blocked(self):
        self.git('switch', '-qc', 'feature')
        self.commit('feature change')
        self.git('switch', '-q', 'base')
        (self.root / 'base-only.txt').write_text('base change')
        self.git('add', 'base-only.txt')
        self.git('commit', '-qm', 'base change')
        result = gate.inspect('base', 'feature', self.root)
        self.assertEqual((result['ahead'], result['behind']), (1, 1))
        self.assertEqual(gate.main(['--base', 'base', '--head', 'feature',
                                    '--repo', str(self.root)]), 1)

    def test_conflicting_feature_is_rejected_without_mutating_checkout(self):
        self.git('switch', '-qc', 'feature')
        self.commit('feature version')
        self.git('switch', '-q', 'base')
        self.commit('base version')
        before = self.git('status', '--porcelain')
        with self.assertRaisesRegex(RuntimeError, 'merge-tree'):
            gate.inspect('base', 'feature', self.root)
        self.assertEqual(self.git('status', '--porcelain'), before)
        self.assertEqual((self.root / 'sample.txt').read_text(), 'base version')

    def test_conflict_is_reported_as_blocked_by_cli(self):
        self.git('switch', '-qc', 'feature')
        self.commit('feature version')
        self.git('switch', '-q', 'base')
        self.commit('base version')
        self.assertEqual(gate.main(['--base', 'base', '--head', 'feature',
                                    '--repo', str(self.root)]), 2)

    def test_concurrent_head_move_fails_closed(self):
        self.git('switch', '-qc', 'feature')
        self.commit('feature version')
        self.git('switch', '-q', 'base')
        original_git = gate.git
        moved = False

        def move_after_diff(*args, **kwargs):
            nonlocal moved
            result = original_git(*args, **kwargs)
            if args[:2] == ('diff', '--name-only') and not moved:
                moved = True
                self.git('branch', '-f', 'feature', 'base')
            return result

        with patch.object(gate, 'git', side_effect=move_after_diff):
            with self.assertRaisesRegex(RuntimeError, 'ref changed'):
                gate.inspect('base', 'feature', self.root)
        self.assertTrue(moved)
        self.assertEqual(self.git('status', '--porcelain'), '')

    def test_concurrent_base_move_fails_closed(self):
        self.git('switch', '-qc', 'feature')
        self.commit('feature version')
        self.git('switch', '-q', 'base')
        original_git = gate.git
        moved = False

        def move_base_after_diff(*args, **kwargs):
            nonlocal moved
            result = original_git(*args, **kwargs)
            if args[:2] == ('diff', '--name-only') and not moved:
                moved = True
                (self.root / 'base-only.txt').write_text('new base commit')
                self.git('add', 'base-only.txt')
                self.git('commit', '-qm', 'advance base')
            return result

        with patch.object(gate, 'git', side_effect=move_base_after_diff):
            with self.assertRaisesRegex(RuntimeError, 'ref changed'):
                gate.inspect('base', 'feature', self.root)
        self.assertTrue(moved)
        self.assertEqual(self.git('status', '--porcelain'), '')

    def test_concurrent_checkout_change_fails_closed(self):
        self.git('switch', '-qc', 'feature')
        self.commit('feature version')
        original_git = gate.git
        changed = False

        def dirty_after_diff(*args, **kwargs):
            nonlocal changed
            result = original_git(*args, **kwargs)
            if args[:2] == ('diff', '--name-only') and not changed:
                changed = True
                (self.root / 'untracked.txt').write_text('concurrent edit')
            return result

        with patch.object(gate, 'git', side_effect=dirty_after_diff):
            with self.assertRaisesRegex(RuntimeError, 'Working tree changed'):
                gate.inspect('base', 'feature', self.root)
        self.assertTrue(changed)
        self.assertEqual((self.root / 'untracked.txt').read_text(), 'concurrent edit')

    def test_merge_tree_unavailable_fails_closed(self):
        self.git('switch', '-qc', 'feature')
        self.commit('feature version')
        original_run = subprocess.run

        def reject_merge_tree(command, **kwargs):
            if command[:3] == ['git', 'merge-tree', '--write-tree']:
                return subprocess.CompletedProcess(command, 129, '', 'unsupported option')
            return original_run(command, **kwargs)

        with patch.object(gate.subprocess, 'run', side_effect=reject_merge_tree):
            with self.assertRaisesRegex(RuntimeError, 'merge-tree'):
                gate.inspect('base', 'feature', self.root)
        self.assertEqual(self.git('status', '--porcelain'), '')

    def test_no_feature_commits_is_blocked(self):
        self.git('branch', 'feature', 'base')
        self.assertEqual(gate.main(['--base', 'base', '--head', 'feature',
                                    '--repo', str(self.root)]), 1)

    def test_dirty_tree_is_rejected(self):
        self.git('switch', '-qc', 'feature')
        self.commit('feature change')
        (self.root / 'untracked.txt').write_text('dirty')
        with self.assertRaisesRegex(RuntimeError, 'not clean'):
            gate.inspect('base', 'feature', self.root)

    def test_missing_ref_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'failed'):
            gate.inspect('base', 'missing', self.root)

    def test_same_ref_is_rejected(self):
        with self.assertRaises(ValueError):
            gate.inspect('base', 'base', self.root)


if __name__ == '__main__':
    unittest.main()
