"""Fixture-only F06 checks for the RealeSR-general-v3 qualification workflow.

These tests use stand-in weights and a stand-in engine. They do not download
the pinned checkpoint and they do not claim live inference.
"""
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / 'scripts' / 'qualify-realesr-general-v3.py'
VERIFIER = REPO / 'scripts' / 'verify-protected-export.py'
COMMITTED_PARAM = 'ce766e261369b911c3f3f607266380e6e6133e82699fed5e3b3afa07482c34c1'
COMMITTED_BIN = '01450f4a79b81c0f1f3eeefc31121167886125c25e41a6d4773e8ec8062528a1'

SPEC = importlib.util.spec_from_file_location('qualify_realesr_general_v3', SCRIPT)
qualify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qualify)

VERIFIER_SPEC = importlib.util.spec_from_file_location('verify_protected_export', VERIFIER)
verify_export = importlib.util.module_from_spec(VERIFIER_SPEC)
VERIFIER_SPEC.loader.exec_module(verify_export)


def write_png(path: Path, pixels: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(pixels, mode='RGB').save(path, format='PNG')


def write_catalog(path: Path, param_sha: str, bin_sha: str, revision: str = 'fixture') -> None:
    path.write_text(
        '# name\trole\trevision\tfolder\tparam_sha256\tbin_sha256\tlicense_note\n'
        'RealeSR-general-v3\tmobile-general\t'
        f'{revision}\tmodels-RealeSR-general-v3\t{param_sha}\t{bin_sha}\tBSD-3-Clause fixture\n',
        encoding='utf-8',
    )


def write_executable(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    path.chmod(0o755)


class RealeSRQualificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / 'home'
        self.catalog = self.root / 'catalog.tsv'
        self.log = self.root / 'commands.log'
        self.param = b'fixture-param\n'
        self.bin = b'fixture-bin\n'
        self.param_sha = hashlib.sha256(self.param).hexdigest()
        self.bin_sha = hashlib.sha256(self.bin).hexdigest()
        write_catalog(self.catalog, self.param_sha, self.bin_sha)
        write_executable(self.home / 'runtime' / 'realsr-ncnn', '#!/usr/bin/env bash\nexit 0\n')
        self.cli = self.root / 'fidelis'
        write_executable(self.cli, self.cli_script('scale'))
        self.installer = self.root / 'install.sh'
        write_executable(
            self.installer,
            '#!/usr/bin/env bash\nprintf \'installer\\n\' >> "$FIDELIS_TEST_LOG"\nexit 1\n',
        )
        self.pixels = np.zeros((3, 2, 3), dtype=np.uint8)
        self.pixels[0, 0] = (1, 2, 3)
        self.pixels[1, 0] = (4, 5, 6)
        self.input = self.root / 'input.png'
        write_png(self.input, self.pixels)
        self.mask = self.root / 'mask.npz'
        protect = np.zeros(self.pixels.shape[:2], dtype=np.float32)
        protect[0, 0] = 1
        protect[1, 0] = 0.5
        np.savez(self.mask, protect=protect)
        self.output = self.root / 'out' / 'export.png'
        self.receipt = self.root / 'out' / 'export.receipt.json'

    def cli_script(self, mode: str) -> str:
        return f"""#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "$FIDELIS_TEST_LOG"
[[ "${{1:-}}" == upscale ]] || {{ printf 'unexpected command\\n' >&2; exit 2; }}
exec "{sys.executable}" - "$2" "$3" "{mode}" <<'PY'
import sys
from PIL import Image
source, target, mode = sys.argv[1:]
with Image.open(source) as image:
    if mode == "bad-size":
        output = Image.new("RGB", (1, 1), (9, 9, 9))
    else:
        output = Image.new("RGB", (image.width * 4, image.height * 4), (200, 200, 200))
output.save(target, format="PNG")
PY
"""

    def environment(self) -> dict:
        env = os.environ.copy()
        env.update({
            'FIDELIS_HOME': str(self.home),
            'FIDELIS_CANDIDATE_CATALOG': str(self.catalog),
            'FIDELIS_CLI': str(self.cli),
            'FIDELIS_CANDIDATE_INSTALLER': str(self.installer),
            'FIDELIS_TEST_LOG': str(self.log),
        })
        env.pop('FIDELIS_ENGINE', None)
        return env

    def install_weights(self) -> None:
        directory = self.home / 'runtime' / 'models-RealeSR-general-v3'
        directory.mkdir(parents=True, exist_ok=True)
        (directory / 'x4.param').write_bytes(self.param)
        (directory / 'x4.bin').write_bytes(self.bin)

    def run_qualifier(self, *extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCRIPT), str(self.input), str(self.output), str(self.mask), *extra,
             '--receipt', str(self.receipt)],
            capture_output=True,
            text=True,
            env=self.environment(),
            check=False,
        )

    def test_committed_catalog_pin_is_the_documented_realesr_pair(self):
        committed = qualify.load_candidate(qualify.COMMITTED_CATALOG)
        self.assertEqual(committed['param_sha256'], COMMITTED_PARAM)
        self.assertEqual(committed['bin_sha256'], COMMITTED_BIN)
        self.assertEqual(committed['role'], 'mobile-general')
        self.assertNotEqual(self.param_sha, COMMITTED_PARAM)

    def test_missing_weights_fail_closed(self):
        self.receipt.parent.mkdir(parents=True)
        self.receipt.write_text('{"evidence_level":"E2"}\n', encoding='utf-8')
        proc = self.run_qualifier()
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('weights missing', proc.stderr)
        self.assertIn('installer', self.log.read_text(encoding='utf-8'))
        self.assertNotIn('upscale', self.log.read_text(encoding='utf-8'))
        self.assertFalse(self.output.exists())
        self.assertFalse(self.receipt.exists())

    def test_sha_mismatch_fail_closed(self):
        self.install_weights()
        write_catalog(self.catalog, 'a' * 64, 'b' * 64)
        before = (self.home / 'runtime' / 'models-RealeSR-general-v3' / 'x4.bin').read_bytes()
        proc = self.run_qualifier()
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('Candidate checksum mismatch: RealeSR-general-v3', proc.stderr)
        self.assertFalse(self.log.exists())
        self.assertEqual((self.home / 'runtime' / 'models-RealeSR-general-v3' / 'x4.bin').read_bytes(), before)
        self.assertFalse(self.output.exists())
        self.assertFalse(self.receipt.exists())

    def test_missing_engine_fail_closed(self):
        self.install_weights()
        engine = self.home / 'runtime' / 'realsr-ncnn'
        engine.unlink()
        proc = self.run_qualifier()
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('Fidelis runtime is not installed', proc.stderr)
        self.assertFalse(self.log.exists())
        self.assertFalse(self.receipt.exists())

    def test_dimension_mismatch_is_rejected_without_resize(self):
        self.install_weights()
        write_executable(self.cli, self.cli_script('bad-size'))
        self.receipt.parent.mkdir(parents=True)
        self.receipt.write_text('{"evidence_level":"E4","pass":true}\n', encoding='utf-8')
        proc = self.run_qualifier()
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('refusing to resize', proc.stderr)
        self.assertIn('1x1', proc.stderr)
        self.assertIn('8x12', proc.stderr)
        self.assertFalse(self.output.exists())
        self.assertFalse(self.receipt.exists())
        self.assertNotIn('.resize(', SCRIPT.read_text(encoding='utf-8'))

    def test_fixture_run_keeps_locked_pixels_and_records_e1(self):
        self.install_weights()
        proc = self.run_qualifier()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        receipt = json.loads(self.receipt.read_text(encoding='utf-8'))
        export = np.asarray(Image.open(self.output))
        self.assertEqual(export.shape, (12, 8, 3))
        self.assertTrue(np.all(export[0:4, 0:4] == np.array([1, 2, 3], dtype=np.uint8)))
        self.assertTrue(np.all(export[4:8, 0:4] == np.array([200, 200, 200], dtype=np.uint8)))
        self.assertTrue(np.all(export[0:4, 4:8] == np.array([200, 200, 200], dtype=np.uint8)))
        self.assertEqual(receipt['evidence_level'], 'E1')
        self.assertFalse(receipt['live_inference'])
        self.assertEqual(receipt['e3_visual_device'], 'not_run')
        self.assertEqual(receipt['e4_released'], 'not_run')
        self.assertNotEqual(receipt['hardware']['target_m1_8gb'], 'accepted')
        self.assertNotEqual(receipt['hardware']['target_android'], 'accepted')
        self.assertEqual(receipt['hardware']['system'], qualify.platform.system())
        self.assertEqual(receipt['model']['param_sha256'], self.param_sha)
        self.assertEqual(receipt['model']['bin_sha256'], self.bin_sha)
        self.assertFalse(receipt['model']['matches_committed_pin'])
        self.assertEqual(receipt['input']['width'], 2)
        self.assertEqual(receipt['input']['height'], 3)
        self.assertEqual(receipt['output']['width'], 8)
        self.assertEqual(receipt['output']['height'], 12)
        self.assertTrue(receipt['output']['dimensions_match_scale'])
        self.assertEqual(receipt['protection']['changed_protected_pixels'], 0)
        self.assertEqual(receipt['protection']['protected_pixels'], 16)
        self.assertEqual(receipt['postprocess'], 'none')
        self.assertFalse(receipt['cloud_fallback'])
        self.assertFalse(receipt['paid_service'])
        self.assertEqual(receipt['api_fee'], 0)
        self.assertEqual(receipt['output_image_count'], 1)
        self.assertEqual(list(self.output.parent.glob('*.png')), [self.output])
        self.assertGreaterEqual(receipt['runtime']['wall_elapsed_ms'], 0)
        checked = verify_export.verify(self._replicated_base(), self.output, self._output_mask())
        self.assertTrue(checked['pass'])

    def test_record_live_without_committed_pin_stays_e1(self):
        self.install_weights()
        proc = self.run_qualifier('--record-live')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('receipt stays at E1', proc.stderr)
        receipt = json.loads(self.receipt.read_text(encoding='utf-8'))
        self.assertEqual(receipt['evidence_level'], 'E1')
        self.assertFalse(receipt['live_inference'])

    def test_installer_then_validated_run_stays_e1(self):
        write_executable(
            self.installer,
            f"""#!/usr/bin/env bash
set -euo pipefail
mkdir -p "$FIDELIS_HOME/runtime/models-{qualify.MODEL_NAME}"
cp "{self.root / 'param.src'}" "$FIDELIS_HOME/runtime/models-{qualify.MODEL_NAME}/x4.param"
cp "{self.root / 'bin.src'}" "$FIDELIS_HOME/runtime/models-{qualify.MODEL_NAME}/x4.bin"
""",
        )
        (self.root / 'param.src').write_bytes(self.param)
        (self.root / 'bin.src').write_bytes(self.bin)
        proc = self.run_qualifier()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        receipt = json.loads(self.receipt.read_text(encoding='utf-8'))
        self.assertTrue(receipt['installer_invoked'])
        self.assertEqual(receipt['evidence_level'], 'E1')

    def test_supplied_base_with_wrong_dimensions_is_rejected(self):
        self.install_weights()
        base = self.root / 'base.png'
        write_png(base, np.zeros((4, 4, 3), dtype=np.uint8))
        proc = self.run_qualifier('--base', str(base))
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('base dimensions', proc.stderr)
        self.assertIn('refusing to resize', proc.stderr)
        self.assertFalse(self.log.exists())
        self.assertFalse(self.output.exists())

    def test_untouched_locked_pixel_passes_verifier(self):
        base, export, mask = self._pair(changed=False)
        result = verify_export.verify(base, export, mask)
        self.assertTrue(result['pass'])
        self.assertEqual(result['changed_protected_pixels'], 0)
        self.assertEqual(verify_export.main([str(base), str(export), str(mask)]), 0)

    def test_changed_locked_pixel_fails_verifier(self):
        base, export, mask = self._pair(changed=True)
        result = verify_export.verify(base, export, mask)
        self.assertFalse(result['pass'])
        self.assertEqual(result['changed_protected_pixels'], 1)
        self.assertEqual(verify_export.main([str(base), str(export), str(mask)]), 1)

    def test_receipt_never_claims_e2_without_a_real_pinned_run(self):
        for level in ('E3', 'E4', 'E5'):
            with self.assertRaises(qualify.QualificationError):
                qualify.assert_receipt_honest({'evidence_level': level, 'e3_visual_device': 'not_run', 'e4_released': 'not_run'})
        forged = {
            'evidence_level': 'E2',
            'live_inference': False,
            'e3_visual_device': 'not_run',
            'e4_released': 'not_run',
            'hardware': {'target_m1_8gb': 'not_run', 'target_android': 'not_run'},
            'model': {'matches_committed_pin': True},
            'output': {'dimensions_match_scale': True},
            'protection': {'pass': True, 'changed_protected_pixels': 0},
        }
        with self.assertRaisesRegex(qualify.QualificationError, 'without a real run'):
            qualify.assert_receipt_honest(forged)
        self.assertEqual(qualify.select_evidence_level(
            record_live=False,
            weights_match_committed_pin=True,
            engine_executed=True,
            dimensions_match=True,
            protection_pass=True,
        ), 'E1')
        self.assertEqual(qualify.select_evidence_level(
            record_live=True,
            weights_match_committed_pin=False,
            engine_executed=True,
            dimensions_match=True,
            protection_pass=True,
        ), 'E1')
        with self.assertRaises(qualify.QualificationError):
            qualify.select_evidence_level(
                record_live=True,
                weights_match_committed_pin=True,
                engine_executed=False,
                dimensions_match=True,
                protection_pass=True,
            )
        self.assertEqual(qualify.select_evidence_level(
            record_live=True,
            weights_match_committed_pin=True,
            engine_executed=True,
            dimensions_match=True,
            protection_pass=True,
        ), 'E2')
        accepted = dict(forged)
        accepted['live_inference'] = True
        accepted['hardware'] = {'target_m1_8gb': 'accepted', 'target_android': 'not_run'}
        with self.assertRaisesRegex(qualify.QualificationError, 'device acceptance'):
            qualify.assert_receipt_honest(accepted)

    def test_help_has_no_evidence_override(self):
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), '--help'],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn('--evidence', proc.stdout)

    def _pair(self, changed: bool):
        base_pixels = np.full((4, 4, 3), 9, dtype=np.uint8)
        texture = np.full_like(base_pixels, 3)
        mask = np.zeros((4, 4), dtype=np.float32)
        mask[1, 1] = 1
        export = qualify.composite_protected(base_pixels, texture, mask)
        if changed:
            export = export.copy()
            export[1, 1, 0] = 0
        base = self.root / f'base-{changed}.png'
        output = self.root / f'export-{changed}.png'
        mask_path = self.root / f'mask-{changed}.npz'
        write_png(base, base_pixels)
        write_png(output, export)
        np.savez(mask_path, protect=mask)
        return base, output, mask_path

    def _replicated_base(self) -> Path:
        path = self.root / 'expected-base.png'
        write_png(path, np.repeat(np.repeat(self.pixels, 4, axis=0), 4, axis=1))
        return path

    def _output_mask(self) -> Path:
        protect = np.zeros(self.pixels.shape[:2], dtype=np.float32)
        protect[0, 0] = 1
        protect[1, 0] = 0.5
        path = self.root / 'expected-mask.npz'
        np.savez(path, protect=np.repeat(np.repeat(protect, 4, axis=0), 4, axis=1))
        return path


if __name__ == '__main__':
    unittest.main()
