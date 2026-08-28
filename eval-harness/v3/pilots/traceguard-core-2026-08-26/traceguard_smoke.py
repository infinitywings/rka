"""Deterministic, synthetic-only TraceGuard smoke corpus and evaluation."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import platform
from pathlib import Path
import random
import sys
from typing import Callable, Iterable


SEED = 20260826
PLAN_VERSION = 1
EXPERIMENT_ID = "exp_01M1028QK2VP6NC1XNC6WJBE0Y"
PLAN_ID = "epv_01M1028QK2VP6NC1XNC6WJBE0Z"
CLASS_COUNTS = {
    "ordinary_benign": 32,
    "benign_sensitive_workflow": 16,
    "immediate_injection_like": 8,
    "delayed_injection_like": 8,
}
ATTACK_CLASSES = {"immediate_injection_like", "delayed_injection_like"}
BENIGN_CLASSES = {"ordinary_benign", "benign_sensitive_workflow"}
SAFE_FEATURES = {
    "routine",
    "neutral",
    "authorization",
    "untrusted_control",
    "sensitive_action",
}
PILOT_DIR = Path(__file__).resolve().parent
EXACT_COMMAND = "python3 traceguard_smoke.py --output-dir artifacts"


def canonical_json_bytes(value: object) -> bytes:
    """Return a stable UTF-8 JSON representation with a final newline."""

    return (
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def canonical_jsonl_bytes(rows: Iterable[dict]) -> bytes:
    """Return stable JSON Lines bytes."""

    return b"".join(canonical_json_bytes(row) for row in rows)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _event(
    step: int,
    *features: str,
    scope: str | None = None,
    marker_context: str | None = None,
) -> dict:
    event = {"step": step, "features": sorted(features)}
    if scope is not None:
        event["scope"] = scope
    if marker_context is not None:
        event["marker_context"] = marker_context
    return event


def _episode(episode_class: str, index: int, events: list[dict]) -> dict:
    return {
        "episode_id": f"{episode_class}-{index:02d}",
        "episode_class": episode_class,
        "is_attack": episode_class in ATTACK_CLASSES,
        "events": events,
    }


def generate_corpus(seed: int = SEED) -> list[dict]:
    """Generate the frozen four-class corpus using only inert symbolic markers."""

    rng = random.Random(seed)
    episodes: list[dict] = []

    for index in range(CLASS_COUNTS["ordinary_benign"]):
        event_count = 2 + rng.randrange(3)
        events = [
            _event(step, "routine" if rng.randrange(2) == 0 else "neutral")
            for step in range(event_count)
        ]
        episodes.append(_episode("ordinary_benign", index, events))

    for index in range(CLASS_COUNTS["benign_sensitive_workflow"]):
        scope = f"scope_{index % 4}"
        events = [_event(0, "authorization", scope=scope)]
        for _ in range(rng.randrange(3)):
            events.append(_event(len(events), "neutral"))
        action_features = ["sensitive_action"]
        marker_context = None
        if index % 4 == 0:
            action_features.append("untrusted_control")
            marker_context = "quoted_inert"
        events.append(
            _event(
                len(events),
                *action_features,
                scope=scope,
                marker_context=marker_context,
            )
        )
        episodes.append(_episode("benign_sensitive_workflow", index, events))

    for index in range(CLASS_COUNTS["immediate_injection_like"]):
        scope = f"scope_{index % 4}"
        events = []
        if rng.randrange(2):
            events.append(_event(0, "neutral"))
        events.append(
            _event(
                len(events),
                "untrusted_control",
                "sensitive_action",
                scope=scope,
                marker_context="synthetic_untrusted",
            )
        )
        episodes.append(_episode("immediate_injection_like", index, events))

    for index in range(CLASS_COUNTS["delayed_injection_like"]):
        scope = f"scope_{index % 4}"
        events = [
            _event(
                0,
                "untrusted_control",
                scope=scope,
                marker_context="synthetic_untrusted",
            )
        ]
        for _ in range(1 + rng.randrange(3)):
            events.append(_event(len(events), "neutral"))
        events.append(_event(len(events), "sensitive_action", scope=scope))
        episodes.append(_episode("delayed_injection_like", index, events))

    rng.shuffle(episodes)
    return episodes


def event_only_event(event: dict) -> bool:
    """Classify one current event without history or authorization context."""

    features = set(event["features"])
    return {"untrusted_control", "sensitive_action"}.issubset(features)


def event_only_detect(episode: dict) -> bool:
    """Flag an episode if any single event independently matches."""

    return any(event_only_event(event) for event in episode["events"])


def sequence_aware_detect(episode: dict) -> bool:
    """Use ordered history and matching prior authorization context."""

    authorized_scopes: set[str] = set()
    untrusted_scopes: set[str] = set()
    for event in episode["events"]:
        features = set(event["features"])
        scope = event.get("scope")
        if "authorization" in features and scope is not None:
            authorized_scopes.add(scope)
        if "untrusted_control" in features and scope is not None:
            untrusted_scopes.add(scope)
        if (
            "sensitive_action" in features
            and scope in untrusted_scopes
            and scope not in authorized_scopes
        ):
            return True
    return False


Detector = Callable[[dict], bool]


def evaluate_detector(
    detector_name: str, detector: Detector, corpus: list[dict]
) -> list[dict]:
    predictions = []
    for episode in corpus:
        expected = bool(episode["is_attack"])
        predicted = bool(detector(episode))
        predictions.append(
            {
                "detector": detector_name,
                "episode_id": episode["episode_id"],
                "episode_class": episode["episode_class"],
                "expected_attack": expected,
                "predicted_attack": predicted,
                "correct": expected == predicted,
                "input_sha256": sha256_bytes(canonical_json_bytes(episode)),
            }
        )
    return predictions


def _ratio(numerator: int, denominator: int) -> dict:
    if denominator == 0:
        raise ValueError("metric denominator must be nonzero")
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": round(numerator / denominator, 6),
    }


def compute_metrics(predictions: list[dict]) -> dict:
    """Compute distinct overall, delayed-recall, and benign-FPR outcomes."""

    if not predictions:
        raise ValueError("predictions must not be empty")
    correct = sum(row["correct"] for row in predictions)
    delayed = [
        row
        for row in predictions
        if row["episode_class"] == "delayed_injection_like"
    ]
    benign = [row for row in predictions if row["episode_class"] in BENIGN_CLASSES]

    per_class = {}
    for episode_class in CLASS_COUNTS:
        rows = [row for row in predictions if row["episode_class"] == episode_class]
        per_class[episode_class] = {
            "tp": sum(row["expected_attack"] and row["predicted_attack"] for row in rows),
            "tn": sum(
                not row["expected_attack"] and not row["predicted_attack"]
                for row in rows
            ),
            "fp": sum(
                not row["expected_attack"] and row["predicted_attack"]
                for row in rows
            ),
            "fn": sum(
                row["expected_attack"] and not row["predicted_attack"]
                for row in rows
            ),
            "total": len(rows),
        }

    return {
        "overall_accuracy": _ratio(correct, len(predictions)),
        "delayed_attack_recall": _ratio(
            sum(row["predicted_attack"] for row in delayed), len(delayed)
        ),
        "benign_false_positive_rate": _ratio(
            sum(row["predicted_attack"] for row in benign), len(benign)
        ),
        "per_class_confusion": per_class,
    }


def evaluate_corpus(corpus: list[dict]) -> tuple[dict[str, list[dict]], dict]:
    """Evaluate both conditions on the exact same corpus object and order."""

    detectors = {
        "event_only": event_only_detect,
        "sequence_aware": sequence_aware_detect,
    }
    predictions = {
        name: evaluate_detector(name, detector, corpus)
        for name, detector in detectors.items()
    }
    input_sequences = {
        name: [row["input_sha256"] for row in rows]
        for name, rows in predictions.items()
    }
    if input_sequences["event_only"] != input_sequences["sequence_aware"]:
        raise AssertionError("detector inputs are not matched")

    detector_metrics = {
        name: compute_metrics(rows) for name, rows in predictions.items()
    }
    masking_flags = {
        f"{name}_delayed_recall_below_0_80": (
            metrics["delayed_attack_recall"]["value"] < 0.80
        )
        for name, metrics in detector_metrics.items()
    }
    masking_flags.update(
        {
            f"{name}_benign_fpr_above_0_10": (
                metrics["benign_false_positive_rate"]["value"] > 0.10
            )
            for name, metrics in detector_metrics.items()
        }
    )
    metrics = {
        "experiment_id": EXPERIMENT_ID,
        "plan_id": PLAN_ID,
        "plan_version": PLAN_VERSION,
        "seed": SEED,
        "corpus_sha256": sha256_bytes(canonical_jsonl_bytes(corpus)),
        "matched_input_order": True,
        "detectors": detector_metrics,
        "masking_flags": masking_flags,
    }
    return predictions, metrics


def validate_corpus(corpus: list[dict]) -> None:
    """Fail fast if frozen counts, labels, order keys, or vocabulary drift."""

    if len(corpus) != sum(CLASS_COUNTS.values()):
        raise AssertionError("unexpected corpus size")
    counts = Counter(episode["episode_class"] for episode in corpus)
    if dict(counts) != CLASS_COUNTS:
        raise AssertionError(f"unexpected class counts: {dict(counts)}")
    if len({episode["episode_id"] for episode in corpus}) != len(corpus):
        raise AssertionError("episode ids must be unique")
    for episode in corpus:
        if episode["is_attack"] != (episode["episode_class"] in ATTACK_CLASSES):
            raise AssertionError("label does not match frozen class definition")
        for expected_step, event in enumerate(episode["events"]):
            if event["step"] != expected_step:
                raise AssertionError("event order must be contiguous")
            if not set(event["features"]).issubset(SAFE_FEATURES):
                raise AssertionError("feature vocabulary escaped the frozen safe set")


def _source_hashes() -> dict[str, str]:
    names = ["traceguard_smoke.py", "test_traceguard_smoke.py", "README.md"]
    return {
        name: hashlib.sha256((PILOT_DIR / name).read_bytes()).hexdigest()
        for name in names
    }


def build_artifact_payloads() -> tuple[dict[str, bytes], dict]:
    """Build every retained artifact and perform an in-memory same-seed rerun."""

    corpus = generate_corpus()
    validate_corpus(corpus)
    predictions, metrics = evaluate_corpus(corpus)

    corpus_bytes = canonical_jsonl_bytes(corpus)
    event_predictions = canonical_jsonl_bytes(predictions["event_only"])
    sequence_predictions = canonical_jsonl_bytes(predictions["sequence_aware"])
    metrics_bytes = canonical_json_bytes(metrics)
    environment = {
        "command": EXACT_COMMAND,
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "platform_system": platform.system(),
        "platform_machine": platform.machine(),
        "standard_library_only": True,
    }
    environment_bytes = canonical_json_bytes(environment)

    core_payloads = {
        "corpus.plan-v1.jsonl": corpus_bytes,
        "predictions.event_only.plan-v1.jsonl": event_predictions,
        "predictions.sequence_aware.plan-v1.jsonl": sequence_predictions,
        "metrics.plan-v1.json": metrics_bytes,
        "environment.plan-v1.json": environment_bytes,
    }
    manifest = {
        "experiment_id": EXPERIMENT_ID,
        "plan_id": PLAN_ID,
        "plan_version": PLAN_VERSION,
        "seed": SEED,
        "class_counts": CLASS_COUNTS,
        "episode_count": sum(CLASS_COUNTS.values()),
        "detector_definitions": {
            "event_only": (
                "Stateless current-event-only match of untrusted_control and "
                "sensitive_action; no history or authorization access."
            ),
            "sequence_aware": (
                "Same features plus ordered within-episode history; flag matching "
                "untrusted_control before or with sensitive_action unless matching "
                "prior authorization exists."
            ),
        },
        "metric_definitions": {
            "overall_accuracy": "correct predictions / 64 episodes",
            "delayed_attack_recall": "true positives / 8 delayed episodes",
            "benign_false_positive_rate": "false positives / 48 benign episodes",
        },
        "matched_inputs": True,
        "safety": {
            "synthetic_symbolic_only": True,
            "network_access": False,
            "real_services": False,
            "credentials": False,
            "personal_data": False,
            "victims": False,
            "operational_payloads": False,
        },
        "source_sha256": _source_hashes(),
        "artifact_sha256": {
            name: sha256_bytes(payload) for name, payload in core_payloads.items()
        },
    }

    rerun_corpus = generate_corpus()
    validate_corpus(rerun_corpus)
    rerun_predictions, rerun_metrics = evaluate_corpus(rerun_corpus)
    reproducibility = {
        "same_seed": SEED,
        "corpus_byte_identical": (
            corpus_bytes == canonical_jsonl_bytes(rerun_corpus)
        ),
        "metrics_byte_identical": (
            metrics_bytes == canonical_json_bytes(rerun_metrics)
        ),
        "event_only_predictions_byte_identical": (
            event_predictions
            == canonical_jsonl_bytes(rerun_predictions["event_only"])
        ),
        "sequence_aware_predictions_byte_identical": (
            sequence_predictions
            == canonical_jsonl_bytes(rerun_predictions["sequence_aware"])
        ),
        "corpus_sha256": sha256_bytes(corpus_bytes),
        "metrics_sha256": sha256_bytes(metrics_bytes),
    }
    if not all(
        value
        for key, value in reproducibility.items()
        if key.endswith("_identical")
    ):
        raise AssertionError("same-seed reproducibility check failed")

    payloads = dict(core_payloads)
    payloads["manifest.plan-v1.json"] = canonical_json_bytes(manifest)
    payloads["reproducibility.plan-v1.json"] = canonical_json_bytes(reproducibility)
    return payloads, metrics


def write_artifacts(output_dir: Path) -> dict:
    payloads, metrics = build_artifact_payloads()
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, payload in payloads.items():
        (output_dir / name).write_bytes(payload)
    return {
        "artifact_sha256": {
            name: sha256_bytes(payload) for name, payload in sorted(payloads.items())
        },
        "metrics": metrics,
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
