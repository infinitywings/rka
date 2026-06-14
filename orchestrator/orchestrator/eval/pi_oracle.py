"""Rubric-driven PI-oracle for reproducible end-to-end orchestrator runs.

The mission / Phase-O / onboarding graphs call an in-process
``interrupt_fn(payload) -> str`` at every PI gate to obtain the PI's response
(``pilot_t12.pilot_interrupt`` returns a hardcoded happy path;
``driver.py`` reads stdin). For a reproducible, gradeable end-to-end test we
need a PI that decides *correctly per the research subject's ground truth* —
ratifying good proposals, redirecting deviations with verbatim pushback, and
rejecting fundamentally-wrong ones — and that **records every decision** so the
grader can later check "did the system surface the right options and respond
to redirects."

This oracle is exactly that: a subject-parameterized ``interrupt_fn``. It
returns contract-correct tokens via ``runner.resume_token`` (accept →
type-specific token; correct → ``REDIRECT_SENTINEL`` + text; reject →
``"reject"``), so it plugs into ``graph.build_graph(interrupt_fn=oracle)`` with
the real SDK + ``RestMCPClient`` unchanged.

Design:
  - A ``Rubric`` is an ordered list of ``Rule``s. The first rule whose
    ``matches(payload)`` is True decides the action; if none match, the
    ``default_action`` applies (``accept`` → happy path, mirroring the pilot).
  - A ``Rule`` matches on interrupt ``type`` (+ optional ``node``) and an
    optional content predicate over the payload — ``contains_any`` /
    ``not_contains`` for JSON-spec'd rubrics, or a free ``predicate`` callable
    for richer logic (e.g. "does the proposed decision name the pivoted claim
    rather than the falsified original?").
  - Every call appends a ``Decision`` to ``oracle.log`` (type, node, action,
    token, matched-rule label, payload digest) — the grading substrate.

The oracle is the ground truth for the "did the PI gate behave correctly"
axis; the human-PI gold run (driver.py stdin) cross-checks that the oracle
isn't flattering the system.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Optional

from orchestrator.runner import resume_token

Action = Literal["accept", "reject", "correct"]


def _payload_text(payload: dict) -> str:
    """Flatten the human-readable fields of an interrupt payload to one
    lowercased string for content matching. Interrupt payloads vary by gate;
    we scan the common rendered fields plus a JSON fallback."""
    parts: list[str] = []
    for key in ("summary", "brief", "text", "rendered", "decision", "options",
                "proposal", "question", "description", "body", "content"):
        v = payload.get(key)
        if isinstance(v, str):
            parts.append(v)
        elif v is not None:
            parts.append(str(v))
    if not parts:
        # fall back to the whole payload minus the type discriminator
        parts.append(str({k: v for k, v in payload.items() if k != "type"}))
    return " ".join(parts).lower()


@dataclass
class Rule:
    """One rubric rule. ``type`` is the interrupt type it applies to (or "*"
    for any). At most one content matcher should be set; if several are, all
    must hold (AND)."""

    type: str
    action: Action
    label: str
    node: Optional[str] = None
    contains_any: Optional[list[str]] = None
    not_contains: Optional[list[str]] = None
    predicate: Optional[Callable[[dict], bool]] = None
    correct_text: Optional[str] = None  # required when action == "correct"

    def matches(self, payload: dict) -> bool:
        if self.type != "*" and payload.get("type") != self.type:
            return False
        if self.node is not None and payload.get("node") != self.node:
            return False
        text = _payload_text(payload)
        if self.contains_any is not None and not any(
            t.lower() in text for t in self.contains_any
        ):
            return False
        if self.not_contains is not None and any(
            t.lower() in text for t in self.not_contains
        ):
            return False
        if self.predicate is not None and not self.predicate(payload):
            return False
        return True


@dataclass
class Decision:
    interrupt_type: str
    node: Optional[str]
    action: Action
    token: str
    rule_label: str
    payload_digest: str


@dataclass
class Rubric:
    rules: list[Rule] = field(default_factory=list)
    default_action: Action = "accept"
    default_label: str = "default-accept"

    def decide(self, payload: dict) -> tuple[Action, str, Optional[str]]:
        """Return (action, rule_label, correct_text|None) for a payload."""
        for rule in self.rules:
            if rule.matches(payload):
                if rule.action == "correct" and not rule.correct_text:
                    raise ValueError(
                        f"rule {rule.label!r} is action=correct but has no correct_text")
                return rule.action, rule.label, rule.correct_text
        if self.default_action == "correct":
            raise ValueError("default_action cannot be 'correct' (no text)")
        return self.default_action, self.default_label, None


class PIOracle:
    """Callable PI responder: ``oracle(payload) -> token``.

    Pass ``oracle.interrupt_fn`` (or the instance itself — it is callable) to
    ``graph.build_graph(interrupt_fn=...)``.
    """

    def __init__(self, rubric: Optional[Rubric] = None):
        self.rubric = rubric or Rubric()
        self.log: list[Decision] = []

    def __call__(self, payload: dict) -> str:
        itype = payload.get("type", "")
        node = payload.get("node")
        action, label, correct_text = self.rubric.decide(payload)
        token = resume_token(
            interrupt_type=itype, action=action, response_text=correct_text
        )
        digest = re.sub(r"\s+", " ", _payload_text(payload))[:160]
        self.log.append(Decision(itype, node, action, token, label, digest))
        return token

    # convenience alias for readers who prefer an explicit attribute
    @property
    def interrupt_fn(self) -> Callable[[dict], str]:
        return self

    # --- grading helpers ---
    def decisions_of_type(self, interrupt_type: str) -> list[Decision]:
        return [d for d in self.log if d.interrupt_type == interrupt_type]

    def corrections(self) -> list[Decision]:
        return [d for d in self.log if d.action == "correct"]

    def as_dicts(self) -> list[dict[str, Any]]:
        return [
            {
                "interrupt_type": d.interrupt_type, "node": d.node,
                "action": d.action, "rule_label": d.rule_label,
                "payload_digest": d.payload_digest,
            }
            for d in self.log
        ]


def happy_path_oracle() -> PIOracle:
    """An oracle that accepts every gate — equivalent to pilot_t12's
    happy path, but with a decision log. Useful as the Phase-0 smoke baseline
    before subject rubrics are layered on."""
    return PIOracle(Rubric(default_action="accept"))
