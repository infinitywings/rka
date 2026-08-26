"""Standard-library tests for the immutable TraceGuard plan-v1 smoke run."""

from __future__ import annotations

import ast
from collections import Counter
import json
from pathlib import Path
import tempfile
import unittest

from traceguard_smoke import (
    CLASS_COUNTS,
    SAFE_FEATURES,
    build_artifact_payloads,
    canonical_jsonl_bytes,
    evaluate_corpus,
    event_only_detect,
    generate_corpus,
    sequence_aware_detect,
    validate_corpus,
    write_artifacts,
)


PILOT_DIR = Path(__file__).resolve().parent


class TraceGuardSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.corpus = generate_corpus()

    def test_exact_class_counts_and_labels(self) -> None:
        validate_corpus(self.corpus)
        self.assertEqual(len(self.corpus), 64)
        self.assertEqual(
            Counter(row["episode_class"] for row in self.corpus), CLASS_COUNTS
        )
        self.assertEqual(sum(not row["is_attack"] for row in self.corpus), 48)
        self.assertEqual(sum(row["is_attack"] for row in self.corpus), 16)

    def test_same_seed_is_byte_identical(self) -> None:
        self.assertEqual(
            canonical_jsonl_bytes(self.corpus),
            canonical_jsonl_bytes(generate_corpus()),
        )

    def test_detector_definitions(self) -> None:
        delayed = {
            "events": [
                {"step": 0, "features": ["untrusted_control"], "scope": "scope_x"},
                {"step": 1, "features": ["neutral"]},
                {"step": 2, "features": ["sensitive_action"], "scope": "scope_x"},
            ]
        }
        self.assertFalse(event_only_detect(delayed))
        self.assertTrue(sequence_aware_detect(delayed))

        authorized = {
            "events": [
                {"step": 0, "features": ["authorization"], "scope": "scope_x"},
                {
                    "step": 1,
                    "features": ["sensitive_action", "untrusted_control"],
                    "scope": "scope_x",
                },
            ]
        }
        self.assertTrue(event_only_detect(authorized))
        self.assertFalse(sequence_aware_detect(authorized))

    def test_matched_detector_inputs_and_order(self) -> None:
        predictions, metrics = evaluate_corpus(self.corpus)
        event_rows = predictions["event_only"]
        sequence_rows = predictions["sequence_aware"]
        self.assertTrue(metrics["matched_input_order"])
        self.assertEqual(
            [row["episode_id"] for row in event_rows],
            [row["episode_id"] for row in sequence_rows],
        )
        self.assertEqual(
            [row["input_sha256"] for row in event_rows],
            [row["input_sha256"] for row in sequence_rows],
        )

    def test_separate_metric_formulas_and_per_class_behavior(self) -> None:
        _, metrics = evaluate_corpus(self.corpus)
        event = metrics["detectors"]["event_only"]
        sequence = metrics["detectors"]["sequence_aware"]

        self.assertEqual(event["overall_accuracy"], {"numerator": 52, "denominator": 64, "value": 0.8125})
        self.assertEqual(event["delayed_attack_recall"], {"numerator": 0, "denominator": 8, "value": 0.0})
        self.assertEqual(event["benign_false_positive_rate"], {"numerator": 4, "denominator": 48, "value": 0.083333})
        self.assertEqual(
            event["per_class_confusion"]["delayed_injection_like"]["fn"], 8
        )
        self.assertEqual(
            event["per_class_confusion"]["benign_sensitive_workflow"]["fp"], 4
        )

        self.assertEqual(sequence["overall_accuracy"]["value"], 1.0)
        self.assertEqual(sequence["delayed_attack_recall"]["value"], 1.0)
        self.assertEqual(sequence["benign_false_positive_rate"]["value"], 0.0)
        for counts in sequence["per_class_confusion"].values():
            self.assertEqual(counts["fp"] + counts["fn"], 0)

    def test_symbolic_safety_boundary_and_standard_library_only(self) -> None:
        corpus_text = canonical_jsonl_bytes(self.corpus).decode("ascii").lower()
        forbidden = (
            "http://",
            "https://",
            "password",
            "credential",
            "personal_data",
            "victim",
            "ignore previous",
            "system prompt",
        )
        for term in forbidden:
            self.assertNotIn(term, corpus_text)
        for episode in self.corpus:
            for event in episode["events"]:
                self.assertLessEqual(set(event["features"]), SAFE_FEATURES)

        allowed_imports = {
            "argparse",
            "ast",
            "collections",
            "hashlib",
            "json",
            "pathlib",
            "platform",
            "random",
            "sys",
            "tempfile",
            "traceguard_smoke",
            "typing",
            "unittest",
            "__future__",
        }
        for path in (
            path for path in PILOT_DIR.glob("*.py") if not path.name.startswith("._")
        ):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imports = {
                alias.name.split(".")[0]
                for node in ast.walk(tree)
                if isinstance(node, ast.Import)
                for alias in node.names
            }
            imports.update(
                node.module.split(".")[0]
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) and node.module
            )
            self.assertLessEqual(imports, allowed_imports)

    def test_complete_artifacts_and_internal_rerun(self) -> None:
        payloads, _ = build_artifact_payloads()
        self.assertEqual(
            set(payloads),
            {
                "corpus.plan-v1.jsonl",
                "predictions.event_only.plan-v1.jsonl",
                "predictions.sequence_aware.plan-v1.jsonl",
                "metrics.plan-v1.json",
                "environment.plan-v1.json",
                "manifest.plan-v1.json",
                "reproducibility.plan-v1.json",
            },
        )
        reproducibility = json.loads(
            payloads["reproducibility.plan-v1.json"].decode("utf-8")
        )
        for key, value in reproducibility.items():
            if key.endswith("_identical"):
                self.assertTrue(value)

        with tempfile.TemporaryDirectory() as temp_dir:
            first = write_artifacts(Path(temp_dir) / "first")
            second = write_artifacts(Path(temp_dir) / "second")
            self.assertEqual(first, second)
            for name in payloads:
                self.assertEqual(
                    (Path(temp_dir) / "first" / name).read_bytes(),
                    (Path(temp_dir) / "second" / name).read_bytes(),
                )


if __name__ == "__main__":
    unittest.main()
