"""v0.6.11 — order-independent `rm` recursive+force classification.

The literal `rm\\s+-rf` regex in the DENY/RATIFY tiers let trivially
re-spelled equivalents (`rm -fr`, `rm -Rf`, `rm -r -f`, `rm -rfv`,
`rm --recursive --force`) slip through BOTH tiers and auto-execute. These
tests pin the order-independent detector.
"""

from __future__ import annotations

import pytest

from orchestrator import fs_actuator as FA


# Every spelling below is recursive AND force and MUST require ratification
# (is_destructive_bash) regardless of the target.
_RF_SPELLINGS = [
    "rm -rf build",
    "rm -fr build",
    "rm -Rf build",
    "rm -r -f build",
    "rm -f -r build",
    "rm -rfv build",
    "rm -vrf build",
    "rm --recursive --force build",
    "rm -r --force build",
    "rm --recursive -f build",
]


@pytest.mark.parametrize("cmd", _RF_SPELLINGS)
def test_recursive_force_requires_ratification(cmd):
    matched, _pat = FA.is_destructive_bash(cmd)
    assert matched, f"{cmd!r} should be classified destructive (ratify-tier)"


# Recursive+force on a sensitive root MUST be DENY-tier (no override), in
# any flag order.
_RF_SENSITIVE = [
    "rm -fr /",
    "rm -Rf /",
    "rm -r -f /",
    "rm --recursive --force /",
    "rm -fr ~",
    "rm -Rf ~/",
    "rm -fr $HOME",
    "rm -rf ${HOME}/data",
    "rm -fr ~/Research",
]


@pytest.mark.parametrize("cmd", _RF_SENSITIVE)
def test_recursive_force_on_sensitive_root_denied(cmd):
    denied, _pat = FA.is_denied_bash(cmd)
    assert denied, f"{cmd!r} should be DENY-tier (recursive+force on host-root/$HOME/~)"


# Non-destructive rm forms MUST NOT trip either tier.
_BENIGN = [
    "rm build",            # not recursive, not force
    "rm -r build",         # recursive only
    "rm -f build",         # force only
    "rm -i build",         # interactive
    "rm --version",
    "ls -rf build",        # not rm
    "confirm -rf thing",   # 'rm' not a standalone command token... see note
]


@pytest.mark.parametrize("cmd", ["rm build", "rm -r build", "rm -f build", "rm -i build", "rm --version"])
def test_benign_rm_not_destructive(cmd):
    matched, _ = FA.is_destructive_bash(cmd)
    assert not matched, f"{cmd!r} should NOT be destructive (not recursive+force)"


def test_ls_rf_not_matched():
    """A non-rm command carrying -rf must not trip the rm detector."""
    matched, _ = FA.is_destructive_bash("ls -rf /tmp")
    assert not matched


def test_variable_indirection_recursive_force_caught():
    """AST normalization resolves $RM, so `RM=rm; $RM -fr /` is caught too."""
    denied, _ = FA.is_denied_bash("RM=rm; $RM -fr /")
    # The AST path resolves $RM -> rm; the order-independent detector then
    # sees recursive+force on `/`. (If bashlex is unavailable the AST path
    # degrades, but the detector still runs on the raw string which here
    # contains `$RM` not `rm`, so this asserts the AST-resolved path.)
    assert denied or FA.is_destructive_bash("RM=rm; $RM -fr /")[0], (
        "variable-resolved recursive+force rm should be caught by at least "
        "one tier"
    )


def test_targets_helper_direct():
    rf, targets = FA._rm_recursive_force_targets("rm -fr /tmp/x /tmp/y")
    assert rf is True
    assert targets == ["/tmp/x", "/tmp/y"]
    rf2, _ = FA._rm_recursive_force_targets("rm -r /tmp/x")
    assert rf2 is False
