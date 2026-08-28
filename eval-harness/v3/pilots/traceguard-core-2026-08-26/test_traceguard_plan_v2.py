"""One focused contract test for immutable TraceGuard plan v2."""

from __future__ import annotations

import ast
from collections import Counter
import json
from pathlib import Path
import tempfile
import unittest

import traceguard_smoke as plan_v1


plan_v2 = __import__("traceguard_plan_v2")
PILOT_DIR = Path(__file__).resolve().parent


class TraceGuardPlanV2Test(unittest.TestCase):
    def test_complete_plan_v2_contract(self) -> None:
        config = plan_v2.load_config()
        self.assertEqual(config, plan_v2.EXPECTED_CONFIG)
        self.assertEqual(config["seed"], 20260827)
        self.assertEqual(config["class_counts"], {
            "ordinary_benign": 128,
            "benign_sensitive_workflow": 64,
            "immediate_injection_like": 32,
            "delayed_injection_like": 32,
        })

        preserved = plan_v2.assert_v1_preserved()
        self.assertEqual(preserved, plan_v2.V1_COMMITTED_FILE_SHA256)
        self.assertIs(plan_v2.DETECTORS["event_only"], plan_v1.event_only_detect)
        self.assertIs(
            plan_v2.DETECTORS["sequence_aware"], plan_v1.sequence_aware_detect
        )

        corpus = plan_v2.generate_corpus()
        plan_v2.validate_corpus(corpus)
        self.assertEqual(len(corpus), 256)
        self.assertEqual(
            Counter(row["episode_class"] for row in corpus),
            config["class_counts"],
        )
        self.assertEqual(sum(not row["is_attack"] for row in corpus), 192)
        self.assertEqual(sum(row["is_attack"] for row in corpus), 64)
        self.assertEqual(
            plan_v1.canonical_jsonl_bytes(corpus),
            plan_v1.canonical_jsonl_bytes(plan_v2.generate_corpus()),
        )
        self.assertEqual(len(plan_v1.generate_corpus()), 64)

        predictions, metrics = plan_v2.evaluate_corpus(corpus)
        event_rows = predictions["event_only"]
        sequence_rows = predictions["sequence_aware"]
        self.assertTrue(metrics["matched_input_order"])
        for key in ("episode_id", "episode_class", "expected_attack", "input_sha256"):
            self.assertEqual(
                [row[key] for row in event_rows],
                [row[key] for row in sequence_rows],
            )
        self.assertEqual(metrics["metric_roles"], config["metric_roles"])
        event = metrics["detectors"]["event_only"]
        sequence = metrics["detectors"]["sequence_aware"]
        self.assertEqual(event["delayed_attack_recall"], {
            "numerator": 0, "denominator": 32, "value": 0.0
        })
        self.assertEqual(event["benign_false_positive_rate"], {
            "numerator": 16, "denominator": 192, "value": 0.083333
        })
        self.assertEqual(event["overall_accuracy"], {
            "numerator": 208, "denominator": 256, "value": 0.8125
        })
        self.assertEqual(sequence["delayed_attack_recall"], {
            "numerator": 32, "denominator": 32, "value": 1.0
        })
        self.assertEqual(sequence["benign_false_positive_rate"], {
            "numerator": 0, "denominator": 192, "value": 0.0
        })
        self.assertEqual(sequence["overall_accuracy"], {
            "numerator": 256, "denominator": 256, "value": 1.0
        })
        for detector_metrics in (event, sequence):
            self.assertEqual(
                {
                    name: counts["total"]
                    for name, counts in detector_metrics[
                        "per_class_confusion"
                    ].items()
                },
                config["class_counts"],
            )

        corpus_text = plan_v1.canonical_jsonl_bytes(corpus).decode("ascii").lower()
        for term in (
            "http://", "https://", "password", "credential", "personal_data",
            "victim", "ignore previous", "system prompt",
        ):
            self.assertNotIn(term, corpus_text)
        self.assertTrue(config["safety"].pop("synthetic_symbolic_only"))
        self.assertFalse(any(config["safety"].values()))

        allowed_imports = {
            "argparse", "ast", "collections", "hashlib", "json", "pathlib",
            "platform", "random", "sys", "tempfile", "traceguard_smoke",
            "typing", "unittest", "__future__",
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

        payloads, _ = plan_v2.build_artifact_payloads()
        expected_names = {
            "commands.plan-v2.txt", "corpus.plan-v2.jsonl",
            "environment.plan-v2.json", "manifest.plan-v2.json",
            "metrics.plan-v2.json", "predictions.event_only.plan-v2.jsonl",
            "predictions.sequence_aware.plan-v2.jsonl",
            "reproducibility.plan-v2.json", "tests.plan-v2.txt",
        }
        self.assertEqual(set(payloads), expected_names)
        self.assertTrue(all(".plan-v2." in name for name in payloads))
        reproducibility = json.loads(
            payloads["reproducibility.plan-v2.json"].decode("utf-8")
        )
        self.assertTrue(all(
            value for key, value in reproducibility.items()
            if key.endswith("_identical")
        ))

        with tempfile.TemporaryDirectory() as temp_dir:
            first_dir = Path(temp_dir) / "first"
            second_dir = Path(temp_dir) / "second"
            first_dir.mkdir()
            sentinel = first_dir / "corpus.plan-v1.jsonl"
            sentinel.write_bytes(b"immutable-v1-sentinel\n")
            first = plan_v2.write_artifacts(first_dir)
            second = plan_v2.write_artifacts(second_dir)
            self.assertEqual(first, second)
            self.assertEqual(sentinel.read_bytes(), b"immutable-v1-sentinel\n")
            for name in (
                "corpus.plan-v2.jsonl",
                "predictions.event_only.plan-v2.jsonl",
                "predictions.sequence_aware.plan-v2.jsonl",
                "metrics.plan-v2.json",
            ):
                self.assertEqual(
                    (first_dir / name).read_bytes(),
                    (second_dir / name).read_bytes(),
                )


if __name__ == "__main__":
    unittest.main()
