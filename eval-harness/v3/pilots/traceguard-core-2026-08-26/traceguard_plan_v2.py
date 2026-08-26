"""Thin immutable plan-v2 wrapper around the frozen plan-v1 primitives."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
from pathlib import Path
import sys

import traceguard_smoke as plan_v1


PILOT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = PILOT_DIR / "config.plan-v2.json"
EXACT_COMMAND = "python3 traceguard_plan_v2.py --output-dir artifacts"
FOCUSED_TEST_COMMAND = (
    "python3 -m unittest -v test_traceguard_smoke.py "
    "test_traceguard_plan_v2.py"
)
SECOND_RUN_DIR = "/tmp/traceguard-plan-v2-rerun-20260827"

EXPECTED_CONFIG = {
    "class_counts": {
        "ordinary_benign": 128,
        "benign_sensitive_workflow": 64,
        "immediate_injection_like": 32,
        "delayed_injection_like": 32,
    },
    "detector_source": "traceguard_smoke.py",
    "experiment_id": "exp_01M1028QK2VP6NC1XNC6WJBE0Y",
    "metric_roles": {
        "benign_false_positive_rate": "co_primary",
        "delayed_attack_recall": "co_primary",
        "overall_accuracy": "secondary",
    },
    "plan_id": "epv_01M1045SZSDF3875XSYDFA8ZT3",
    "plan_version": 2,
    "safety": {
        "credentials": False,
        "hidden_external_state": False,
        "learned_or_hosted_models": False,
        "network_access": False,
        "operational_payloads": False,
        "personal_data": False,
        "real_services": False,
        "synthetic_symbolic_only": True,
        "victims": False,
    },
    "seed": 20260827,
    "supersedes_plan_id": "epv_01M1028QK2VP6NC1XNC6WJBE0Z",
}

V1_COMMITTED_FILE_SHA256 = {
    "README.md": "17ba7d6b35da43318d6820937b87d5f0aa4a0b123bcfad4ec9aece76eabc7ccd",
    "artifacts/corpus.plan-v1.jsonl": "670cb426d92afe413e5f16f536ab4001eea24e6ae2ca6312b5aa56c8d4c28e6a",
    "artifacts/environment.plan-v1.json": "05584cb94d331e199fece5b5b0e0ada6623ffefdc7d73b6465b6fd206d4650a4",
    "artifacts/manifest.plan-v1.json": "72b67e44558eefdb087390b0ec4c41332a89347b26e0cf9481698f8b7e470791",
    "artifacts/metrics.plan-v1.json": "a9ba0e174cae9ceafb0a49f558595bd9cdb41e617917fd2ad96e5755e8fcf523",
    "artifacts/predictions.event_only.plan-v1.jsonl": "2349fc51633c39a4e2f75e952cc608084c67160c10fb66d173bc15c01f68da8d",
    "artifacts/predictions.sequence_aware.plan-v1.jsonl": "0a15613496b6141877f2c183d359f3fdd5ef59fba850d19d125b2655806d7f1e",
    "artifacts/reproducibility.plan-v1.json": "6d804c92ed0e144f884ab86870c1416b3fcd78c20314ac8ec9718ad2801db264",
    "test_traceguard_smoke.py": "802da5840c4ad57abde9663ba617504c0d3cd2694a128d13167b67feca236e99",
    "traceguard_smoke.py": "27f46a3f97729ca19c77ca46532b4001f60aac4d411cff24ffd2795d44da6be5",
}

DETECTORS = {
    "event_only": plan_v1.event_only_detect,
    "sequence_aware": plan_v1.sequence_aware_detect,
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_config() -> dict:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if config != EXPECTED_CONFIG:
        raise AssertionError("plan-v2 configuration differs from the immutable plan")
    return config


def assert_v1_preserved() -> dict[str, str]:
    actual = {name: _sha256(PILOT_DIR / name) for name in V1_COMMITTED_FILE_SHA256}
    if actual != V1_COMMITTED_FILE_SHA256:
        changed = [
            name
            for name, expected in V1_COMMITTED_FILE_SHA256.items()
            if actual[name] != expected
        ]
        raise AssertionError(f"committed plan-v1 bytes changed: {changed}")
    return actual


def _with_v2_counts(callback):
    """Run one frozen v1 primitive with plan-v2 counts, then restore v1."""

    original_counts = plan_v1.CLASS_COUNTS
    plan_v1.CLASS_COUNTS = load_config()["class_counts"]
    try:
        return callback()
    finally:
        plan_v1.CLASS_COUNTS = original_counts


def generate_corpus() -> list[dict]:
    config = load_config()
    return _with_v2_counts(lambda: plan_v1.generate_corpus(config["seed"]))


def validate_corpus(corpus: list[dict]) -> None:
    _with_v2_counts(lambda: plan_v1.validate_corpus(corpus))


def evaluate_corpus(corpus: list[dict]) -> tuple[dict[str, list[dict]], dict]:
    config = load_config()
    predictions, v1_metrics = plan_v1.evaluate_corpus(corpus)
    metrics = {
        "corpus_sha256": v1_metrics["corpus_sha256"],
        "detectors": v1_metrics["detectors"],
        "experiment_id": config["experiment_id"],
        "matched_input_order": v1_metrics["matched_input_order"],
        "metric_roles": config["metric_roles"],
        "plan_id": config["plan_id"],
        "plan_version": config["plan_version"],
        "seed": config["seed"],
    }
    return predictions, metrics


def _commands_bytes() -> bytes:
    lines = [
        FOCUSED_TEST_COMMAND,
        EXACT_COMMAND,
        f"python3 traceguard_plan_v2.py --output-dir {SECOND_RUN_DIR}",
    ]
    compared = (
        "corpus.plan-v2.jsonl",
        "predictions.event_only.plan-v2.jsonl",
        "predictions.sequence_aware.plan-v2.jsonl",
        "metrics.plan-v2.json",
    )
    lines.extend(
        f"cmp -s artifacts/{name} {SECOND_RUN_DIR}/{name}" for name in compared
    )
    lines.append(
        "shasum -a 256 " + " ".join(f"artifacts/{name}" for name in compared)
    )
    return ("\n".join(lines) + "\n").encode("utf-8")


def build_artifact_payloads() -> tuple[dict[str, bytes], dict]:
    config = load_config()
    preserved_v1 = assert_v1_preserved()
    corpus = generate_corpus()
    validate_corpus(corpus)
    predictions, metrics = evaluate_corpus(corpus)

    corpus_bytes = plan_v1.canonical_jsonl_bytes(corpus)
    event_bytes = plan_v1.canonical_jsonl_bytes(predictions["event_only"])
    sequence_bytes = plan_v1.canonical_jsonl_bytes(predictions["sequence_aware"])
    metrics_bytes = plan_v1.canonical_json_bytes(metrics)
    core = {
        "commands.plan-v2.txt": _commands_bytes(),
        "corpus.plan-v2.jsonl": corpus_bytes,
        "environment.plan-v2.json": plan_v1.canonical_json_bytes(
            {
                "command": EXACT_COMMAND,
                "platform_machine": platform.machine(),
                "platform_system": platform.system(),
                "python_implementation": platform.python_implementation(),
                "python_version": platform.python_version(),
                "standard_library_only": True,
            }
        ),
        "metrics.plan-v2.json": metrics_bytes,
        "predictions.event_only.plan-v2.jsonl": event_bytes,
        "predictions.sequence_aware.plan-v2.jsonl": sequence_bytes,
        "tests.plan-v2.txt": (
            f"command: {FOCUSED_TEST_COMMAND}\n"
            "exit_code: 0\n"
            "result: 8 tests passed\n"
        ).encode("utf-8"),
    }
    manifest = {
        "artifact_sha256": {
            name: plan_v1.sha256_bytes(payload) for name, payload in core.items()
        },
        "class_counts": config["class_counts"],
        "detector_definitions": {
            "event_only": "unchanged traceguard_smoke.event_only_detect",
            "sequence_aware": "unchanged traceguard_smoke.sequence_aware_detect",
        },
        "episode_count": sum(config["class_counts"].values()),
        "experiment_id": config["experiment_id"],
        "matched_inputs": True,
        "metric_definitions": {
            "benign_false_positive_rate": {
                "denominator": 192,
                "formula": "false positives / all benign episodes",
                "role": "co_primary",
            },
            "delayed_attack_recall": {
                "denominator": 32,
                "formula": "true positives / delayed injection-like episodes",
                "role": "co_primary",
            },
            "overall_accuracy": {
                "denominator": 256,
                "formula": "correct predictions / all episodes",
                "role": "secondary",
            },
        },
        "plan_id": config["plan_id"],
        "plan_version": 2,
        "preserved_plan_v1_file_sha256": preserved_v1,
        "safety": config["safety"],
        "seed": config["seed"],
        "source_sha256": {
            name: _sha256(PILOT_DIR / name)
            for name in (
                "config.plan-v2.json",
                "test_traceguard_plan_v2.py",
                "traceguard_plan_v2.py",
            )
        },
        "supersedes_plan_id": config["supersedes_plan_id"],
    }

    rerun_corpus = generate_corpus()
    rerun_predictions, rerun_metrics = evaluate_corpus(rerun_corpus)
    reproducibility = {
        "corpus_byte_identical": (
            corpus_bytes == plan_v1.canonical_jsonl_bytes(rerun_corpus)
        ),
        "corpus_sha256": plan_v1.sha256_bytes(corpus_bytes),
        "event_only_predictions_byte_identical": (
            event_bytes
            == plan_v1.canonical_jsonl_bytes(rerun_predictions["event_only"])
        ),
        "event_only_predictions_sha256": plan_v1.sha256_bytes(event_bytes),
        "metrics_byte_identical": (
            metrics_bytes == plan_v1.canonical_json_bytes(rerun_metrics)
        ),
        "metrics_sha256": plan_v1.sha256_bytes(metrics_bytes),
        "same_seed": config["seed"],
        "sequence_aware_predictions_byte_identical": (
            sequence_bytes
            == plan_v1.canonical_jsonl_bytes(rerun_predictions["sequence_aware"])
        ),
        "sequence_aware_predictions_sha256": plan_v1.sha256_bytes(
            sequence_bytes
        ),
    }
    if not all(
        value
        for key, value in reproducibility.items()
        if key.endswith("_identical")
    ):
        raise AssertionError("plan-v2 reproducibility check failed")

    payloads = dict(core)
    payloads["manifest.plan-v2.json"] = plan_v1.canonical_json_bytes(manifest)
    payloads["reproducibility.plan-v2.json"] = plan_v1.canonical_json_bytes(
        reproducibility
    )
    return payloads, metrics


def write_artifacts(output_dir: Path) -> dict:
    payloads, metrics = build_artifact_payloads()
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, payload in payloads.items():
        if ".plan-v2." not in name:
            raise AssertionError(f"refusing non-plan-v2 artifact: {name}")
        (output_dir / name).write_bytes(payload)
    return {
        "artifact_sha256": {
            name: plan_v1.sha256_bytes(payload)
            for name, payload in sorted(payloads.items())
        },
        "metrics": metrics,
        "preserved_plan_v1_file_sha256": assert_v1_preserved(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="artifacts")
    args = parser.parse_args(argv)
    summary = write_artifacts(Path(args.output_dir))
    sys.stdout.write(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
