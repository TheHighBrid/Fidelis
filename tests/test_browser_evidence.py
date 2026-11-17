import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from fidelis.studio.browser_evidence import publish_evidence


class BrowserEvidenceTest(unittest.TestCase):
    def test_binary_payload_and_atomic_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'nested' / 'receipt.png'
            payload = b'\x89PNG\x00\xff'
            publish_evidence(target, payload)
            self.assertEqual(target.read_bytes(), payload)
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            publish_evidence(target, b'updated')
            self.assertEqual(target.read_bytes(), b'updated')
            self.assertEqual(list(target.parent.iterdir()), [target])

    def test_symlink_and_nonregular_destinations_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = root / 'original'
            original.write_bytes(b'original')
            link = root / 'receipt'
            link.symlink_to(original)
            with self.assertRaisesRegex(ValueError, 'regular file'):
                publish_evidence(link, b'changed')
            self.assertEqual(original.read_bytes(), b'original')
            self.assertTrue(link.is_symlink())
            with self.assertRaisesRegex(ValueError, 'regular file'):
                publish_evidence(root, b'changed')

    def test_directory_rename_cannot_redirect_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            selected, moved, outside = (root / name for name in ('selected', 'moved', 'outside'))
            selected.mkdir()
            outside.mkdir()
            real_replace = os.replace

            def swap_parent(source, target, **kwargs):
                selected.rename(moved)
                selected.symlink_to(outside, target_is_directory=True)
                return real_replace(source, target, **kwargs)

            with patch('fidelis.studio.browser_evidence.os.replace', side_effect=swap_parent):
                publish_evidence(selected / 'receipt', b'pinned')
            self.assertEqual((moved / 'receipt').read_bytes(), b'pinned')
            self.assertEqual(list(outside.iterdir()), [])
            self.assertEqual(list(moved.iterdir()), [moved / 'receipt'])

    def test_failed_publication_removes_private_staging(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'receipt'
            target.write_bytes(b'previous')
            with patch('fidelis.studio.browser_evidence.os.replace', side_effect=OSError('injected')):
                with self.assertRaisesRegex(OSError, 'injected'):
                    publish_evidence(target, b'new')
            self.assertEqual(target.read_bytes(), b'previous')
            self.assertEqual(list(target.parent.iterdir()), [target])


if __name__ == '__main__':
    unittest.main()
