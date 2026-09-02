from pathlib import Path
from unittest import TestCase

from scripts.validate_container_release import project_version, validate_release_tag

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "publish-container.yml"


class ContainerReleaseTests(TestCase):
    def test_current_core_version_has_an_exact_release_tag(self) -> None:
        version = project_version(ROOT / "pyproject.toml")
        self.assertEqual(validate_release_tag(f"v{version}", version), version)

    def test_container_release_rejects_noncanonical_or_mismatched_tags(self) -> None:
        cases = [
            ("3.0.0", "3.0.0"),
            ("v3.0", "3.0.0"),
            ("v3.0.1", "3.0.0"),
            ("v3.0.0-rc1", "3.0.0-rc1"),
            ("v03.0.0", "03.0.0"),
        ]
        for tag, version in cases:
            with self.subTest(tag=tag, version=version), self.assertRaises(ValueError):
                validate_release_tag(tag, version)

    def test_publication_workflow_is_release_only_digest_first_and_multi_arch(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("types: [published]", workflow)
        self.assertNotIn("workflow_dispatch", workflow)
        self.assertIn("github.event.release.prerelease == false", workflow)
        self.assertIn("python scripts/validate_container_release.py", workflow)
        self.assertIn("git merge-base --is-ancestor", workflow)
        self.assertIn("platforms: linux/amd64,linux/arm64", workflow)
        self.assertIn("subject-digest: ${{ steps.publish.outputs.digest }}", workflow)
        self.assertIn("push-to-registry: true", workflow)
        self.assertEqual(workflow.count("scripts/container_image_smoke.py"), 2)

        action_lines = [line.strip() for line in workflow.splitlines() if "uses:" in line]
        self.assertTrue(action_lines)
        for line in action_lines:
            revision = line.rsplit("@", 1)[-1]
            self.assertEqual(len(revision), 40)
            self.assertTrue(all(character in "0123456789abcdef" for character in revision))
