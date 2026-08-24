#!/usr/bin/env python3
"""Sanitize an RKA knowledge pack so it can be published as a public sample.

The knowledge pack exported by ``GET /api/projects/export`` is a faithful dump
of one project: every journal entry, decision rationale, mission report and tag
exactly as it was written. That is what makes it a useful sample — and also why
it cannot be published unread. A working research log accumulates absolute
paths, LAN addresses, references to the researcher's *other* projects, and the
occasional third-party name.

This script applies a fixed, auditable rule set to every string in the manifest
and reports what it changed. It is deliberately conservative: each rule targets
an *identifier* (a path, an address, a project name) rather than prose, so the
research content — which is the point of the sample — survives intact.

What it does NOT do, by design:

* It does not touch the live database. Run it on an exported pack.
* It does not redact the project owner's own name or affiliation. Those are
  already public in the repository's commit history; blanking them here would
  be theatre.
* It does not blanket-replace ambiguous words. ``TRACE`` is a proposal codename
  in some entries and plain provenance vocabulary in tags like
  ``trace-provenance``; ``canvas`` is a UI surface in most entries and an LMS in
  one. Rules that cannot separate the two are scoped to the specific records
  that need them (see ``TARGETED``).

Usage::

    python scripts/sanitize_knowledge_pack.py in.rka-pack.zip out.rka-pack.zip
    python scripts/sanitize_knowledge_pack.py in.zip out.zip --report report.md
    python scripts/sanitize_knowledge_pack.py in.zip --check   # scan only
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

MANIFEST_NAME = "manifest.json"

# The project this pack belongs to. Its own id is expected throughout and is
# never rewritten; any *other* project id is a cross-project reference.
SELF_PROJECT_ID = "prj_01KKQM9JFG67GT5FGWTAHD9YE4"

# Cross-project references are aliased rather than deleted so that entries that
# say "unlike what we did in X" still read coherently. Aliases are ordered by
# corpus size and match the labels used in the eval-harness reports, so a reader
# of both sees the same names.
PROJECT_ALIASES: dict[str, str] = {
    "prj_01KN51HD73DSY9ZR9C56JYRNYZ": "project-B",
    "prj_01KMJTPHW2KR7JR9SP3GRB9210": "project-C",
    "prj_01KS8EQ8J1J0EZPF5T1Z65W7RC": "project-D",
    "prj_01KZVF35ESDGKZKTG1D1J59TCF": "project-E",
    "prj_01KPVB7NHJ0N33C024TD0E6CZ6": "project-F",
    "prj_01KWFRG2TZGHV1A8G4MXVDFPJ5": "project-G",
    "prj_01M0BWM7MBPH9W9Z8KDD25651H": "project-H",
    "prj_01KPB91SAX28Z2KFE5EHPSGR01": "project-I",
    "prj_01KT7HB5PQC76Z5NJGVGRCJ3BB": "project-K",
    # Ids seen only in prose; these projects have since been deleted.
    "prj_01KMJQZXPZW0VZV5483QEJPNRN": "project-L",
    "prj_01KP4D83G1F0TN209J258RZ0D6": "project-M",
    "prj_01KMKREC3JKSJVPYR6KHEKWVN7": "project-N",
}

# Only names distinctive enough to alias safely. Two sibling projects are
# deliberately absent:
#
#   CAREER        — every occurrence in this corpus is the NSF CAREER *award
#                   program*, not the project of that name. Aliasing it turned
#                   "NSF PAPPG/CAREER support" into "NSF PAPPG/project-G
#                   support", which is simply wrong.
#   detectability — an ordinary English noun ("the detectability of the
#                   attack"). A word-bounded rule cannot tell the project from
#                   the concept.
#
# Neither name currently appears as a project reference in this corpus, so
# omitting them costs nothing; including them would corrupt prose the moment
# either word were used in its ordinary sense.
PROJECT_NAME_ALIASES: dict[str, str] = {
    "Invarllm": "project-B",
    "INVARLLM": "project-B",
    "rka-education": "project-C",
    "delaysteer": "project-E",
    "CPSEval": "project-F",
    "PESOSE": "project-H",
    "new_cybersecurity_course": "project-I",
    "NIST_curriculum": "project-K",
}


# Crockford base32, the ULID alphabet. It deliberately omits I, L, O and U to
# avoid visual confusion with 1 and 0 — which is why an alias letter cannot be
# used directly as an id suffix.
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _alias_id(alias: str) -> str:
    """Build a syntactically valid ULID-shaped id for an aliased project.

    Import validates the ``prj_`` + 26-char Crockford-base32 shape, so the
    placeholder has to keep it even though these ids only ever appear in prose.
    The suffix is derived from a digest rather than from the alias letter:
    ``project-L`` would otherwise produce a literal ``L``, which is not in the
    alphabet and would fail that validation.

    The leading zero run makes a placeholder obvious on sight and lets the
    residual scan tell placeholders apart from ids it has not yet aliased.
    """
    digest = hashlib.sha256(alias.encode()).digest()
    code = "".join(_CROCKFORD[b % 32] for b in digest[:4])
    return "prj_" + "0" * 22 + code


# --- Global rules -----------------------------------------------------------
# (name, compiled pattern, replacement). Applied to every string in the
# manifest, in order. Replacements may be callables.

GLOBAL_RULES: list[tuple[str, re.Pattern[str], object]] = [
    # Absolute paths leak the account name and the machine's directory layout.
    ("home_path", re.compile(r"/Users/[A-Za-z0-9._-]+"), "/Users/researcher"),
    ("home_path", re.compile(r"/home/[A-Za-z0-9._-]+"), "/home/researcher"),
    # The workspace volume is named after the researcher. Other /Volumes paths
    # (a mounted DMG, for instance) carry no identity and are left alone.
    ("workspace_path", re.compile(r"/Volumes/FuSpace\b"), "/Volumes/Workspace"),
    # Private-range addresses map into RFC 5737 TEST-NET-1, which exists for
    # documentation and can never route anywhere real.
    (
        "lan_ip",
        re.compile(r"\b(?:192\.168|10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b"),
        None,  # filled in by _make_ip_replacer
    ),
    # Every project id other than this pack's own. A single callable handles
    # both the mapped ids and any id the map has not seen — a hand-maintained
    # list would silently go stale the next time the pack is re-exported, and
    # an unmapped id is exactly the case that must not slip through.
    ("foreign_project_id", re.compile(r"\bprj_[0-9A-HJKMNP-TV-Z]{26}\b"), None),
    # Cross-project names. Word-bounded and case-sensitive except where the
    # corpus uses both cases.
    *[
        ("foreign_project_name", re.compile(rf"\b{re.escape(name)}\b"), alias)
        for name, alias in PROJECT_NAME_ALIASES.items()
    ],
    # Third parties who never agreed to appear in a public corpus.
    ("third_party", re.compile(r"\bSunshine\b"), "[collaborator]"),
    ("third_party", re.compile(r"\bNCSSM\b"), "[a regional high school]"),
    # Teaching identifiers: a course code plus an LMS course id together
    # identify a specific offering and its enrolled students.
    ("course_identifier", re.compile(r"\b(?:ITIS|ITCS|CSC|ECGR)\s?\d{4}\b"), "[course]"),
    ("course_identifier", re.compile(r"\bcourse ID \d+\b"), "course ID [redacted]"),
    # The NSF solicitation itself is public — its number, name and terms are
    # published. What was private is the assessment of how an internal research
    # direction fit it, and that is removed by TARGETED below. Rewriting the
    # solicitation number here as well produced the incoherent heading
    # "NSF FINDERS FOUNDRY (solicitation-analysis) Solicitation Analysis"
    # while still naming the program two words later, so the rule was dropped.
    ("course_identifier", re.compile(r"\bcanvas-analysis\b"), "course-content-analysis"),
]


def _replace_project_id(match: re.Match[str]) -> str:
    """Alias any project id that is not this pack's own.

    Mapped ids get their readable ``project-B`` style label so entries that
    reference a sibling project still read sensibly. An id absent from the map
    is aliased from a digest of itself: stable across runs, unlinkable to the
    original, and impossible to forget to add.
    """
    project_id = match.group(0)
    if project_id == SELF_PROJECT_ID:
        return project_id
    alias = PROJECT_ALIASES.get(project_id)
    if alias is None:
        digest = hashlib.sha256(project_id.encode()).hexdigest()[:6].upper()
        alias = f"project-{digest}"
    return _alias_id(alias)


def _make_ip_replacer() -> object:
    """Map each distinct private address to a stable TEST-NET-1 address."""
    seen: dict[str, str] = {}

    def repl(match: re.Match[str]) -> str:
        ip = match.group(0)
        if ip not in seen:
            seen[ip] = f"192.0.2.{len(seen) + 1}"
        return seen[ip]

    return repl


# --- Targeted rules ---------------------------------------------------------
# Redactions that must not be applied corpus-wide. Each entry is
# (name, anchor pattern that identifies the record, cut pattern, replacement).
# The cut is applied only to strings that contain the anchor.

FINDERS_REDACTION = (
    "\n\n### Key Fit Assessment\n\n"
    "_[Redacted for publication: this section assessed how a specific internal "
    "research direction fit the solicitation above, and named collaborators and "
    "an institution. The public solicitation summary is retained because it "
    "shows how RKA records external constraints; the internal assessment is "
    "removed.]_\n"
)

TARGETED: list[tuple[str, re.Pattern[str], re.Pattern[str], str]] = [
    (
        "grant_strategy",
        re.compile(r"NSF FINDERS FOUNDRY .* Solicitation Analysis"),
        re.compile(r"\n#+ Key Fit Assessment.*\Z", re.S),
        FINDERS_REDACTION,
    ),
]


def walk_strings(node, path=""):
    """Yield (container, key, path, value) for every string in the manifest."""
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(value, str):
                yield node, key, f"{path}.{key}", value
            else:
                yield from walk_strings(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            if isinstance(value, str):
                yield node, index, f"{path}[]", value
            else:
                yield from walk_strings(value, f"{path}[]")


def sanitize(manifest: dict) -> collections.Counter:
    """Rewrite the manifest in place. Returns per-rule replacement counts."""
    rules = []
    for name, pattern, replacement in GLOBAL_RULES:
        if replacement is None:
            replacement = _make_ip_replacer() if name == "lan_ip" else _replace_project_id
        rules.append((name, pattern, replacement))

    counts: collections.Counter = collections.Counter()
    for container, key, _path, value in walk_strings(manifest):
        original = value
        for name, pattern, replacement in rules:
            # Count real edits, not matches: the project-id rule matches this
            # pack's own id thousands of times and returns it untouched, which
            # would otherwise dominate the report with a number that means
            # nothing.
            before = value
            value = pattern.sub(replacement, value)
            if value != before:
                counts[name] += sum(
                    1 for m in pattern.finditer(before) if m.group(0) not in value
                ) or 1
        for name, anchor, cut, replacement in TARGETED:
            if anchor.search(value):
                value, n = cut.subn(replacement, value)
                if n:
                    counts[name] += n
        if value != original:
            container[key] = value
    return counts


# --- Verification -----------------------------------------------------------
# Run against the *output*. Anything that still matches is a leak the rules
# missed, so this is the check that actually gates publication.

RESIDUAL_CHECKS: dict[str, str] = {
    "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    "api_key": r"\b(?:sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{12,}"
    r"|xox[baprs]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{30,})\b",
    "secret_assignment": r"(?i)\b(?:api[_-]?key|secret|password|passwd|access[_-]?token)"
    r"\s*[:=]\s*[\"']?[A-Za-z0-9_\-]{12,}",
    "url_credentials": r"://[^/\s:@]+:[^/\s@]+@",
    "home_path": r"/Users/(?!researcher\b)[A-Za-z0-9._-]+|/home/(?!researcher\b)[A-Za-z0-9._-]+",
    "workspace_path": r"/Volumes/FuSpace\b",
    "private_ip": r"\b(?:192\.168|10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b",
    "foreign_project_id": rf"\bprj_(?!{SELF_PROJECT_ID[4:]})(?!0{{20,}})[0-9A-HJKMNP-TV-Z]{{26}}\b",
    "foreign_project_name": r"\b(?:" + "|".join(PROJECT_NAME_ALIASES) + r")\b",
    "third_party": r"\bSunshine\b|\bNCSSM\b",
    "course_identifier": r"\b(?:ITIS|ITCS|CSC|ECGR)\s?\d{4}\b|course ID \d+",
    "phone": r"\b(?:\+1[-. ]?)?\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}\b",
    "orcid": r"\b\d{4}-\d{4}-\d{4}-\d{3}[\dX]\b",
    "mac_address": r"\b(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\b",
    "grant_strategy": r"Key Fit Assessment\n\n(?!_\[Redacted)",
}


def verify(manifest: dict) -> dict[str, list[str]]:
    """Return {check_name: [sample matches]} for every residual hit."""
    findings: dict[str, list[str]] = {}
    for name, pattern in RESIDUAL_CHECKS.items():
        compiled = re.compile(pattern)
        samples: list[str] = []
        for _c, _k, path, value in walk_strings(manifest):
            for match in compiled.finditer(value):
                if len(samples) < 5:
                    samples.append(f"{match.group(0)!r} @ {path}")
        if samples:
            findings[name] = samples
    return findings


def load_pack(path: Path) -> dict:
    with zipfile.ZipFile(path) as zf:
        with zf.open(MANIFEST_NAME) as fh:
            return json.load(fh)


def write_pack(manifest: dict, path: Path) -> None:
    payload = json.dumps(manifest, ensure_ascii=False, indent=2)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(MANIFEST_NAME, payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("source", type=Path, help="input .rka-pack.zip")
    parser.add_argument("dest", type=Path, nargs="?", help="output .rka-pack.zip")
    parser.add_argument("--check", action="store_true", help="scan only, do not write")
    parser.add_argument("--report", type=Path, help="write a markdown change report")
    args = parser.parse_args(argv)

    if not args.check and args.dest is None:
        parser.error("dest is required unless --check is given")

    manifest = load_pack(args.source)

    if args.check:
        findings = verify(manifest)
        for name, samples in findings.items():
            print(f"FAIL {name}: {len(samples)}+ matches")
            for sample in samples:
                print(f"       {sample}")
        if not findings:
            print("PASS — no residual matches")
        return 1 if findings else 0

    counts = sanitize(manifest)
    findings = verify(manifest)

    print("replacements:")
    for name, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {name:24}{count:>6}")
    print(f"  {'TOTAL':24}{sum(counts.values()):>6}")

    if findings:
        print("\nRESIDUAL MATCHES — not writing output:")
        for name, samples in findings.items():
            print(f"  {name}:")
            for sample in samples:
                print(f"    {sample}")
        return 1

    write_pack(manifest, args.dest)
    print(f"\nverification: PASS\nwrote {args.dest}")

    if args.report:
        lines = [
            "# Knowledge-pack sanitization report",
            "",
            f"Source: `{args.source.name}`",
            f"Output: `{args.dest.name}`",
            "",
            "| Rule | Replacements |",
            "|---|---|",
        ]
        lines += [f"| `{n}` | {c} |" for n, c in sorted(counts.items(), key=lambda kv: -kv[1])]
        lines += [f"| **total** | **{sum(counts.values())}** |", "",
                  f"Residual scan: **PASS** ({len(RESIDUAL_CHECKS)} checks, 0 matches)."]
        args.report.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"wrote {args.report}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
