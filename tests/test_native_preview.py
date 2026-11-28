"""Local native bootstrap verifies only selected bytes and publishes a new home."""

import hashlib
import json
import os
import platform
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from unittest.mock import patch

from fidelis.studio.native_preview import _rename_exclusive, bootstrap_native_preview


def digest(data):
    return hashlib.sha256(data).hexdigest()


class NativePreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / "repo"
        self.archives = self.base / "archives"
        self.cache = self.base / "cache"
        self.home = self.base / "new-home"
        for folder in (self.repo, self.archives, self.cache):
            folder.mkdir()
        self.catalog = {"schema_version": 1, "runtimes": [], "models": []}
        self.add_runtime("realsr-ncnn-vulkan-20220728", "realsr.zip", "root/realsr", b"realSR fixture")
        self.add_runtime("realesrgan-ncnn-vulkan-20220424", "realesrgan.zip", "realesrgan", b"ESRGAN fixture")
        self.add_model("RealeSR-general-v3", True)
        self.add_model("RealSR-DF2K", False)
        self.write("scripts/ncnn-preview-runtime.sh", b"#!/bin/sh\nexit 0\n")
        self.save_catalog()
        self.patch_platform = patch.multiple(platform, system=lambda: "Darwin", machine=lambda: "arm64")
        self.patch_platform.start()
        self.addCleanup(self.patch_platform.stop)

    def write(self, relative, data):
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def add_runtime(self, identity, name, member, binary):
        archive = self.archives / name
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr(member, binary)
            bundle.writestr("models-DF2K/unlicensed.bin", b"must never be extracted")
            bundle.writestr("../../unsafe-unselected", b"must never be extracted")
        notice = b"fixture runtime MIT notice " + identity.encode()
        notice_path = "config/runtime-licenses/" + identity + ".txt"
        self.write(notice_path, notice)
        self.catalog["runtimes"].append({
            "runtime_id": identity, "download_url": "https://example.test/releases/" + name,
            "archive_sha256": digest(archive.read_bytes()), "archive_member": member,
            "macos_binary_sha256": digest(binary), "license_notice_path": notice_path,
            "license_notice_sha256": digest(notice), "commercial_status": "cleared_permissive",
            "license": "MIT",
        })

    def add_model(self, identity, cleared):
        folder = "models-RealeSR-general-v3" if cleared else "models-DF2K"
        target = self.cache / folder
        target.mkdir()
        weights = {}
        for name in ("x4.param", "x4.bin"):
            data = (identity + name).encode()
            (target / name).write_bytes(data)
            weights[name] = digest(data)
        self.write("config/model-licenses/" + identity + ".txt", b"fixture BSD model notice")
        self.catalog["models"].append({
            "model_id": identity, "local_relative_dir": "runtime/" + folder,
            "weights": weights, "source": {"folder": folder, "revision": "pinned-fixture"},
            "terms": {"production_terms_cleared": cleared, "license": "BSD-3-Clause",
                      "packaged_notice_sha256": digest(b"fixture BSD model notice")},
        })

    def save_catalog(self):
        self.write("config/model-provenance-v1.json", json.dumps(self.catalog).encode())

    def publish_fixture(self, staging, target):
        if target.exists() or target.is_symlink():
            raise FileExistsError(str(target))
        os.rename(staging, target)

    def bootstrap(self):
        with patch("fidelis.studio.native_preview._rename_exclusive", side_effect=self.publish_fixture):
            return bootstrap_native_preview(self.repo, archive_dir=self.archives,
                                            model_cache=self.cache, app_home=self.home)

    def assert_failed_clean(self):
        self.assertFalse(self.home.exists())
        self.assertEqual(list(self.base.glob(".new-home.staging-*")), [])

    def test_selected_bytes_not_archive_models_are_staged_with_honest_receipt(self):
        receipt = self.bootstrap()
        self.assertEqual(receipt["scope"], "byte_verified_not_quality_or_release")
        self.assertFalse(receipt["native_execution_verified"])
        self.assertEqual(receipt["release_approval"], "not_granted")
        self.assertEqual([m["model_id"] for m in receipt["models"]["included"]], ["RealeSR-general-v3"])
        self.assertEqual(receipt["models"]["excluded"][0]["folder"], "models-DF2K")
        self.assertEqual((self.home / "runtime/realsr-binary").read_bytes(), b"realSR fixture")
        self.assertEqual((self.home / "runtime/realesrgan-binary").read_bytes(), b"ESRGAN fixture")
        self.assertTrue((self.home / "runtime/realsr-binary").stat().st_mode & 0o111)
        self.assertFalse((self.home / "runtime/models-DF2K").exists())
        self.assertFalse((self.base / "unsafe-unselected").exists())
        registration = json.loads((self.home / "runtime/models-RealeSR-general-v3/fidelis-model.json").read_text())
        self.assertEqual(registration["sha256"]["bin"], self.catalog["models"][0]["weights"]["x4.bin"])
        self.assertEqual(json.loads((self.home / "install.json").read_text()), receipt)
        self.assertEqual(json.loads((self.home / "native-preview-receipt.json").read_text()), receipt)

    def test_archive_or_binary_hash_failure_publishes_nothing(self):
        self.catalog["runtimes"][0]["archive_sha256"] = "0" * 64
        self.save_catalog()
        with self.assertRaisesRegex(ValueError, "archive checksum"):
            self.bootstrap()
        self.assert_failed_clean()
        self.catalog["runtimes"][0]["archive_sha256"] = digest((self.archives / "realsr.zip").read_bytes())
        self.catalog["runtimes"][0]["macos_binary_sha256"] = "0" * 64
        self.save_catalog()
        with self.assertRaisesRegex(ValueError, "binary checksum"):
            self.bootstrap()
        self.assert_failed_clean()

    def test_selected_member_traversal_and_missing_are_rejected(self):
        for member in ("../realsr", "/absolute", "root/./realsr", "missing"):
            with self.subTest(member=member):
                self.catalog["runtimes"][0]["archive_member"] = member
                self.save_catalog()
                with self.assertRaises(ValueError):
                    self.bootstrap()
                self.assert_failed_clean()

    def test_duplicate_or_symlink_selected_zip_member_is_rejected(self):
        entry = self.catalog["runtimes"][0]
        archive = self.archives / "realsr.zip"
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr(entry["archive_member"], b"realSR fixture")
                bundle.writestr(entry["archive_member"], b"duplicate fixture")
        entry["archive_sha256"] = digest(archive.read_bytes())
        self.save_catalog()
        with self.assertRaisesRegex(ValueError, "unique regular"):
            self.bootstrap()
        self.assert_failed_clean()
        info = zipfile.ZipInfo(entry["archive_member"])
        info.create_system = 3
        info.external_attr = 0o120777 << 16
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr(info, b"link-target")
        entry["archive_sha256"] = digest(archive.read_bytes())
        self.save_catalog()
        with self.assertRaisesRegex(ValueError, "unique regular"):
            self.bootstrap()
        self.assert_failed_clean()

    def test_additional_cleared_model_cannot_expand_preview_scope(self):
        self.catalog["models"][1]["terms"]["production_terms_cleared"] = True
        self.save_catalog()
        with self.assertRaisesRegex(ValueError, "exactly the cleared"):
            self.bootstrap()
        self.assert_failed_clean()

    def test_license_notice_missing_changed_or_escaped_is_rejected(self):
        entry = self.catalog["runtimes"][0]
        notice = self.repo / entry["license_notice_path"]
        notice.unlink()
        with self.assertRaisesRegex(ValueError, "repository file"):
            self.bootstrap()
        self.assert_failed_clean()
        notice.write_bytes(b"altered notice")
        with self.assertRaisesRegex(ValueError, "notice checksum"):
            self.bootstrap()
        entry["license_notice_path"] = "../outside.txt"
        self.save_catalog()
        with self.assertRaises(ValueError):
            self.bootstrap()
        self.assert_failed_clean()

    def test_selected_model_notice_is_confined_and_pinned(self):
        notice = self.repo / "config/model-licenses/RealeSR-general-v3.txt"
        outside = self.base / "outside-notice.txt"
        outside.write_bytes(b"fixture BSD model notice")
        notice.unlink()
        notice.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "unsafe model license notice"):
            self.bootstrap()
        self.assert_failed_clean()
        self.assertEqual(outside.read_bytes(), b"fixture BSD model notice")
        notice.unlink()
        notice.write_bytes(b"different non-license text")
        with self.assertRaisesRegex(ValueError, "notice checksum"):
            self.bootstrap()
        self.assert_failed_clean()
        notice.write_bytes(b"fixture BSD model notice")
        del self.catalog["models"][0]["terms"]["packaged_notice_sha256"]
        self.save_catalog()
        with self.assertRaisesRegex(ValueError, "notice checksum"):
            self.bootstrap()
        self.assert_failed_clean()

    def test_uncleared_required_model_or_weight_mismatch_is_rejected(self):
        self.catalog["models"][0]["terms"]["production_terms_cleared"] = False
        self.save_catalog()
        with self.assertRaisesRegex(ValueError, "cleared terms"):
            self.bootstrap()
        self.catalog["models"][0]["terms"]["production_terms_cleared"] = True
        self.save_catalog()
        (self.cache / "models-RealeSR-general-v3/x4.bin").write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "checksum"):
            self.bootstrap()
        self.assert_failed_clean()

    def test_existing_home_and_dangling_symlink_are_never_overwritten(self):
        self.home.mkdir()
        owner = self.home / "owner.txt"
        owner.write_bytes(b"owner data")
        with self.assertRaises(FileExistsError):
            self.bootstrap()
        self.assertEqual(owner.read_bytes(), b"owner data")
        owner.unlink()
        self.home.rmdir()
        self.home.symlink_to(self.base / "absent")
        with self.assertRaises(FileExistsError):
            self.bootstrap()
        self.assertTrue(self.home.is_symlink())

    def test_platform_archive_symlink_and_wrapper_symlink_fail_closed(self):
        with patch.object(platform, "machine", return_value="x86_64"):
            with self.assertRaisesRegex(ValueError, "macOS arm64"):
                self.bootstrap()
        archive = self.archives / "realsr.zip"
        source = self.base / "outside.zip"
        archive.rename(source)
        archive.symlink_to(source)
        with self.assertRaisesRegex(ValueError, "unsafe local"):
            self.bootstrap()
        self.assert_failed_clean()
        archive.unlink()
        source.rename(archive)
        wrapper = self.repo / "scripts/ncnn-preview-runtime.sh"
        wrapper.unlink()
        wrapper.symlink_to(self.repo / self.catalog["runtimes"][0]["license_notice_path"])
        with self.assertRaisesRegex(ValueError, "unsafe repository"):
            self.bootstrap()
        self.assert_failed_clean()

    def test_publication_failure_cleans_only_owned_stage(self):
        def concurrent_home(staging, target):
            target.mkdir()
            (target / "owner.txt").write_bytes(b"concurrent owner data")
            raise FileExistsError("concurrent target")

        with patch("fidelis.studio.native_preview._rename_exclusive", side_effect=concurrent_home):
            with self.assertRaises(FileExistsError):
                bootstrap_native_preview(self.repo, archive_dir=self.archives,
                                         model_cache=self.cache, app_home=self.home)
        self.assertEqual((self.home / "owner.txt").read_bytes(), b"concurrent owner data")
        self.assertEqual(list(self.base.glob(".new-home.staging-*")), [])


@unittest.skipUnless(platform.system() == "Darwin", "Darwin exclusive rename primitive")
class DarwinExclusivePublicationTests(unittest.TestCase):
    def test_real_rename_excl_keeps_existing_empty_target(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            staging, target = root / "stage", root / "home"
            staging.mkdir()
            target.mkdir()
            with self.assertRaises(FileExistsError):
                _rename_exclusive(staging, target)
            self.assertTrue(staging.is_dir())
            self.assertTrue(target.is_dir())
            target.rmdir()
            _rename_exclusive(staging, target)
            self.assertFalse(staging.exists())
            self.assertTrue(target.is_dir())


if __name__ == "__main__":
    unittest.main()
