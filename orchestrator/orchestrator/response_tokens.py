"""Resume-token primitives shared by the runner + graph routing helpers.

Lives in its own module to break the circular import between
runner.py (which imports graph for compile factories) and the
routing functions in graph.py / onboarding_graph.py / phase_b_graph.py
/ phase_o_graph.py / nodes/pi.py — all of which need to detect the
redirect sentinel BEFORE running their substring approve/accept check.

Background — closes the substring-routing-smuggling class bug
surfaced by the design-and-code review (workflow w69b6e8kg). Before
this module, a PI correction like "I cannot approve this — redo"
sent via orchestrator_correct would have its raw text reach the
routing helpers, which substring-matched "approve" and silently
routed to the accept branch, bypassing the TWO-TAP ratification gate
on pi_decision_select / pi_greenlight / pi_acceptance / etc. The
fix: runner.resume_token() now prefixes the freeform correction text
with REDIRECT_SENTINEL; every routing helper and every is_accept
check first calls is_redirect_token() and short-circuits to the
escalation/redirect branch.
"""

from __future__ import annotations

from typing import Optional

REDIRECT_SENTINEL = "__RKA_REDIRECT__::"
"""Prefix attached to action='correct' resume tokens.

Chosen to be non-natural-language so no legitimate PI text can
collide. The substring `__RKA_REDIRECT__::` would have to appear in
the PI's correction verbatim for the sentinel check to false-positive
— deliberate construction, never accidental.

The literal `::` pair is rejected by every documented accept token
("approve", "accept") so the sentinel is forward-compatible with any
new interrupt type that uses one of those literals.
"""


def is_redirect_token(response_text: Optional[str]) -> bool:
    """True if the resume string carries the redirect sentinel — i.e., the
    PI's response is a freeform correction, not a literal accept/reject
    token. Routing functions short-circuit on this BEFORE running their
    substring approve/accept check.

    Case-insensitive because the graph's _latest_interrupt_response
    helper lowercases the response before routing — the sentinel must
    survive that normalization. Leading whitespace stripped so the
    check is robust against ` REDIRECT_SENTINEL+text` shapes a future
    caller might construct.
    """
    if not response_text:
        return False
    return response_text.lstrip().upper().startswith(REDIRECT_SENTINEL)
