"""Guard active contributor entrypoints against obsolete Studio checkout advice.

Historical checkpoints may retain their original dates and branch references.
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CurrentMainHandoffTests(unittest.TestCase):
    def test_active_entrypoints_identify_integrated_main(self):
        for name in ("README.md", "AGENTS.md", "ONBOARDING.md", "docs/project/HANDOFF.md"):
            with self.subTest(path=name):
                text = (ROOT / name).read_text(encoding="utf-8")
                self.assertIn("7310aa6", text)
                self.assertIn("main", text)

    def test_onboarding_and_readme_do_not_checkout_obsolete_feature_branch(self):
        for name in ("README.md", "ONBOARDING.md"):
            with self.subTest(path=name):
                text = (ROOT / name).read_text(encoding="utf-8")
                self.assertNotIn("git switch feat/region-aware-studio", text)
                self.assertIn("git switch main", text)

    def test_entrypoints_do_not_conflate_merge_with_release(self):
        for name in ("README.md", "AGENTS.md", "docs/project/HANDOFF.md"):
            with self.subTest(path=name):
                text = (ROOT / name).read_text(encoding="utf-8")
                self.assertTrue(any(
                    phrase in text for phrase in (
                        "not deployment", "not released", "not deployment,",
                    )
                ))


if __name__ == "__main__":
    unittest.main()
