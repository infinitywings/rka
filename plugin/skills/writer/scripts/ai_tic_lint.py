#!/usr/bin/env python3
"""ai_tic_lint.py: Anti-AI-tic linter for the Writer skill.

Phase 1 implementation per dec_01KS12H9KT1T03DHX2Q6FKTXHH (Option C disposition;
no third-party content vendored). Sources cited directly: PI verbatim list (per
dec_01KS0BKJ5ZJKJ4R19GYAK3QN9D Q4), Kobak et al. 2025 (Science Advances
11(27):eadt3813, doi:10.1126/sciadv.adt3813), Matsui 2025 (Perspectives on
Medical Education 14(1):882-890).

Tiers:
  CRITICAL (block any hit; no override): ChatGPT artifacts and refusal stems.
  HIGH (block by default; per-project override via ai_tic_config.yaml):
    PI list + Kobak 2025 + Matsui 2025.
  MEDIUM (warn): structural and stylistic LLM patterns.

Absolute bans (no override): em-dash U+2014 and en-dash U+2013 in prose;
bullet density (at most two lists per section; 3 to 5 items each).

Structural detectors complement the lexical layer (Matsui 2025: pure lexical
over-flags legitimate academic prose):
  - Sentence-length variance: flag paragraphs where std dev under 5 words.
  - Transition-word ratio: at or below 0.5 percent.
  - Parallel-triplet density: at or below 1 per 500 words.
  - Bridge repetition: delegated to bridge_repetition_check.py.

CLI:
    python ai_tic_lint.py <files>...
    python ai_tic_lint.py --config /path/to/ai_tic_config.yaml <files>...
    python ai_tic_lint.py --output report.json --section sections/03-method.tex

Exit codes:
    0: all PASS
    1: WARN-only verdicts present
    2: BLOCK verdict present (CRITICAL, HIGH without override, absolute ban,
       or structural detector BLOCK)
    3: usage error

See references/ai_tics.md for the full tier table and replacement guidance.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

try:
    import yaml  # type: ignore
    _yaml_available = True
except ImportError:
    yaml = None  # type: ignore
    _yaml_available = False


# Absolute-ban characters. Built from codepoints via chr() so this source
# file does not itself contain the literal em-dash or en-dash characters
# the Writer prose rule bans (dogfood discipline).
EM_DASH = chr(0x2014)  # U+2014 EM DASH
EN_DASH = chr(0x2013)  # U+2013 EN DASH

# Tier 1: CRITICAL (compile-blocking on any hit; no per-project override).
# Sources: empirical observation of ChatGPT/OpenAI output artifacts and refusal
# language in published manuscripts.
CRITICAL_PATTERNS: dict[str, str] = {
    r"\bturn\d+search\d*\b": "ChatGPT browsing-tool token",
    r"\boaicite\b": "OpenAI citation marker",
    r"\bcontentReference\b": "OpenAI internal reference",
    r"\battribution\":": "OpenAI grounding metadata JSON",
    r"\bAs an AI language model\b": "model refusal stem",
    r"\bI cannot help with that\b": "model refusal stem",
    r"\bAs of my last knowledge update\b": "knowledge-cutoff disclaimer",
}

# Tier 2: HIGH (block by default; per-project override via ai_tic_config.yaml).
# Per dec_01KS12H9KT1T03DHX2Q6FKTXHH PATCH 2: cite primaries directly.
HIGH_PATTERNS: dict[str, str] = {
    # PI verbatim list (dec_01KS0BKJ5ZJKJ4R19GYAK3QN9D Q4).
    r"\bfacilitate\b": "PI verbatim list",
    r"\bfacilitates\b": "PI verbatim list",
    r"\bdelves\b": "PI verbatim list",
    r"\bleverage\b": "PI verbatim list",
    r"\bleverages\b": "PI verbatim list",
    r"\bleveraging\b": "PI verbatim list",
    r"\bcomprehensive\b": "PI verbatim list",
    r"\bfurthermore\b": "PI verbatim list",
    r"\bmoreover\b": "PI verbatim list",
    r"\badditionally\b": "PI verbatim list",
    r"\bimportantly\b": "PI verbatim list",
    r"\bin conclusion\b": "PI verbatim list",
    r"\bit is important to note\b": "PI verbatim list",
    # Kobak et al. 2025 (Science Advances 11(27):eadt3813).
    r"\bdelving\b": "Kobak 2025",
    r"\bunderscore\b": "Kobak 2025",
    r"\bunderscores\b": "Kobak 2025",
    r"\bunderscoring\b": "Kobak 2025",
    r"\bshowcasing\b": "Kobak 2025",
    r"\bshowcase\b": "Kobak 2025",
    r"\bshowcases\b": "Kobak 2025",
    r"\bpivotal\b": "Kobak 2025",
    r"\bintricate\b": "Kobak 2025",
    r"\bintricately\b": "Kobak 2025",
    r"\bmeticulous\b": "Kobak 2025",
    r"\bmeticulously\b": "Kobak 2025",
    r"\brealm\b": "Kobak 2025",
    r"\baligns\b": "Kobak 2025",
    r"\baligning\b": "Kobak 2025",
    r"\bunderpins\b": "Kobak 2025",
    r"\bgarnered\b": "Kobak 2025",
    r"\bbolstering\b": "Kobak 2025",
    r"\bnotably\b": "Kobak 2025",
    r"\bsurpass\b": "Kobak 2025",
    r"\bintricacies\b": "Kobak 2025",
    r"\bunwavering\b": "Kobak 2025",
    # Matsui 2025 (Perspectives on Medical Education 14(1):882-890).
    r"\benhance\b": "Matsui 2025",
    r"\belevate\b": "Matsui 2025",
    r"\butilize\b": "Matsui 2025",
    r"\bboast\b": "Matsui 2025",
    r"\bcommendable\b": "Matsui 2025",
    r"\btapestry\b": "Matsui 2025",
    r"\bunlocking\b": "Matsui 2025",
}

# Tier 3: MEDIUM (warn; do not block).
MEDIUM_PATTERNS: dict[str, str] = {
    r"^\s*Importantly,": "Importantly sentence-starter",
    r"^\s*It should be noted that": "It should be noted that sentence-starter",
    r"^\s*In summary,": "In summary paragraph-closer",
}

# Transition-word set for ratio computation.
TRANSITION_WORDS = {
    "however", "nevertheless", "furthermore", "moreover", "additionally",
    "consequently", "thus", "therefore", "hence", "accordingly",
}


@dataclass
class Hit:
    """A single linter hit (lexical or absolute-ban)."""
    term: str
    line: int
    tier: str
    source: str


@dataclass
class StructuralVerdict:
    """Result of a single structural detector."""
    detector: str
    value: float
    threshold: float
    verdict: str  # PASS, WARN, BLOCK


@dataclass
class FileReport:
    """Linter result for a single file."""
    path: str
    total_lines: int
    total_sentences: int
    total_words: int
    critical: list[Hit] = field(default_factory=list)
    high: list[Hit] = field(default_factory=list)
    medium: list[Hit] = field(default_factory=list)
    absolute_bans: list[Hit] = field(default_factory=list)
    structural: list[StructuralVerdict] = field(default_factory=list)
    style_score: float = 1.0
    verdict: str = "PASS"


def load_config(config_path: Optional[Path]) -> dict:
    """Load ai_tic_config.yaml if present.

    Returns a dict mapping each banned term to a verdict (enable, disable,
    downgrade) and project-specific custom blocks. If PyYAML is unavailable
    or the config does not exist, returns an empty dict (default behavior:
    all HIGH terms block).
    """
    if config_path is None or not config_path.exists():
        return {}
    if not _yaml_available:
        print(
            "ai_tic_lint: PyYAML not installed; ai_tic_config.yaml ignored. "
            "Install PyYAML for per-project overrides.",
            file=sys.stderr,
        )
        return {}
    with config_path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_venue_config(venue: Optional[str]) -> dict:
    """Load a venue-default ai-tic config from
    references/venue_aitic_defaults/<venue>.yaml.

    P5 recalibration: the lexical blocklist (well-sourced from Kobak 2025 /
    Matsui 2025) over-flags terms that are domain-legitimate in some venues
    (e.g. "enhance throughput", "comprehensive evaluation" in systems/security
    writing); detector-style blocking carries a 61.3% false-positive rate on
    non-native English (Liang 2023), so context-aware downgrades matter.
    Venue defaults are merged UNDER the per-project config (project wins),
    using the same enable/disable/downgrade verdicts as ai_tic_config.yaml.
    """
    if not venue:
        return {}
    if not _yaml_available:
        return {}
    base = Path(__file__).resolve().parent.parent / "references" / "venue_aitic_defaults"
    path = base / f"{venue}.yaml"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def merge_configs(venue_cfg: dict, project_cfg: dict) -> dict:
    """Merge venue defaults under a project config. Project entries win."""
    merged = dict(venue_cfg)
    merged.update(project_cfg or {})
    return merged


def apply_config_to_term(term: str, default_tier: str, config: dict) -> Optional[str]:
    """Resolve the effective tier for a term given a per-project config.

    Returns:
        The effective tier (CRITICAL, HIGH, MEDIUM), or None if the term is
        disabled for this project.
    """
    entry = config.get(term, None)
    if entry is None:
        return default_tier
    verdict = entry.get("verdict", "enable")
    if verdict == "disable":
        return None
    if verdict == "downgrade":
        return "MEDIUM" if default_tier == "HIGH" else default_tier
    return default_tier


def find_lexical_hits(
    text: str,
    patterns: dict[str, str],
    tier: str,
    config: Optional[dict] = None,
) -> list[Hit]:
    """Scan text for any pattern match; return list of Hit records.

    Per-line tracking via splitlines(). Patterns are case-insensitive regex.
    Per-project config (if provided) can disable or downgrade a hit.
    """
    hits: list[Hit] = []
    lines = text.splitlines()
    for line_num, line in enumerate(lines, start=1):
        for pattern, source in patterns.items():
            for match in re.finditer(pattern, line, flags=re.IGNORECASE):
                term = match.group(0)
                effective_tier = (
                    apply_config_to_term(term.lower(), tier, config or {})
                    if config is not None
                    else tier
                )
                if effective_tier is None:
                    continue
                hits.append(
                    Hit(
                        term=term,
                        line=line_num,
                        tier=effective_tier,
                        source=source,
                    )
                )
    return hits


def find_em_dash(text: str) -> list[Hit]:
    """Detect U+2014 em-dash and U+2013 en-dash. Absolute ban; no override."""
    hits: list[Hit] = []
    for line_num, line in enumerate(text.splitlines(), start=1):
        for ch in line:
            if ch == EM_DASH:
                hits.append(
                    Hit(term="U+2014 EM DASH", line=line_num,
                        tier="ABSOLUTE_BAN", source="em-dash absolute ban")
                )
            elif ch == EN_DASH:
                hits.append(
                    Hit(term="U+2013 EN DASH", line=line_num,
                        tier="ABSOLUTE_BAN", source="en-dash absolute ban")
                )
    return hits


def find_bullet_violations(text: str) -> list[Hit]:
    """Detect bullet density violations.

    Rules: at most 2 bulleted lists per section; each list 3 to 5 items.
    "Section" is delimited by markdown H2 (## ) or LaTeX \\section{}.
    """
    hits: list[Hit] = []
    lines = text.splitlines()

    section_starts = [
        i for i, line in enumerate(lines)
        if line.startswith("## ") or line.lstrip().startswith("\\section{")
    ]
    if not section_starts:
        section_starts = [0]
    section_ends = section_starts[1:] + [len(lines)]

    bullet_re = re.compile(r"^\s*[-*+]\s")

    for s_start, s_end in zip(section_starts, section_ends):
        lists: list[list[int]] = []
        current: list[int] = []
        for i in range(s_start, s_end):
            line = lines[i]
            if bullet_re.match(line):
                current.append(i + 1)
            else:
                if current:
                    lists.append(current)
                    current = []
        if current:
            lists.append(current)

        if len(lists) > 2:
            hits.append(
                Hit(
                    term=f"section has {len(lists)} bulleted lists",
                    line=s_start + 1,
                    tier="ABSOLUTE_BAN",
                    source="bullet-density cap: max 2 lists per section",
                )
            )

        for lst in lists:
            if len(lst) < 3:
                hits.append(
                    Hit(
                        term=f"list with {len(lst)} items (under 3)",
                        line=lst[0],
                        tier="ABSOLUTE_BAN",
                        source="bullet-density cap: 3 to 5 items per list",
                    )
                )
            elif len(lst) > 5:
                hits.append(
                    Hit(
                        term=f"list with {len(lst)} items (over 5)",
                        line=lst[0],
                        tier="ABSOLUTE_BAN",
                        source="bullet-density cap: 3 to 5 items per list",
                    )
                )

    return hits


def split_sentences(text: str) -> list[str]:
    """Split text into sentences via end-of-sentence punctuation."""
    cleaned = re.sub(r"%.*$", "", text, flags=re.MULTILINE)
    cleaned = re.sub(r"\\(cite|ref|eqref)\{[^}]*\}", "", cleaned)
    parts = re.split(r"(?<=[.!?])\s+", cleaned)
    return [p.strip() for p in parts if p.strip()]


def split_paragraphs(text: str) -> list[str]:
    """Split text into paragraphs on blank lines."""
    paras = re.split(r"\n\s*\n", text)
    return [p.strip() for p in paras if p.strip()]


def count_words(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


def sentence_length_variance(text: str) -> StructuralVerdict:
    """Flag paragraphs where the standard deviation of sentence length is under 5 words.

    Reports the minimum across all paragraphs with at least 5 sentences. Short
    paragraphs (under 5 sentences) inherently have low variance and would
    over-flag; the empirical signal in Matsui 2025 and Kobak 2025 is about
    uniform rhythm across substantive paragraphs, not over 3-sentence excerpts.

    Verdict is WARN rather than BLOCK: structural detectors contribute to the
    style score (which can BLOCK via the auto-revise loop), but a low variance
    on its own is suggestive evidence, not a hard violation.
    """
    paragraphs = split_paragraphs(text)
    paragraph_stds: list[float] = []
    for para in paragraphs:
        sentences = split_sentences(para)
        if len(sentences) < 5:
            continue
        lengths = [count_words(s) for s in sentences]
        try:
            paragraph_stds.append(statistics.stdev(lengths))
        except statistics.StatisticsError:
            continue
    if not paragraph_stds:
        return StructuralVerdict(
            detector="sentence_length_variance",
            value=0.0,
            threshold=5.0,
            verdict="PASS",
        )
    min_std = min(paragraph_stds)
    verdict = "WARN" if min_std < 5.0 else "PASS"
    return StructuralVerdict(
        detector="sentence_length_variance",
        value=min_std,
        threshold=5.0,
        verdict=verdict,
    )


def transition_word_ratio(text: str) -> StructuralVerdict:
    """Ratio of transition-word occurrences to total words. Threshold 0.5%."""
    words = re.findall(r"\b\w+\b", text.lower())
    total = len(words)
    if total == 0:
        return StructuralVerdict(
            detector="transition_word_ratio",
            value=0.0,
            threshold=0.005,
            verdict="PASS",
        )
    transitions = sum(1 for w in words if w in TRANSITION_WORDS)
    ratio = transitions / total
    verdict = "WARN" if ratio > 0.005 else "PASS"
    return StructuralVerdict(
        detector="transition_word_ratio",
        value=ratio,
        threshold=0.005,
        verdict=verdict,
    )


def parallel_triplet_density(text: str) -> StructuralVerdict:
    """Density of "X, Y, and Z" parallel-triplet constructions per 500 words.

    Threshold: at or below 1.0 per 500 words.
    """
    triplet_re = re.compile(r"\b\w+\b\s*,\s*\b\w+\b\s*,\s+and\s+\b\w+\b", re.IGNORECASE)
    matches = triplet_re.findall(text)
    total_words = count_words(text)
    if total_words == 0:
        return StructuralVerdict(
            detector="parallel_triplet_density",
            value=0.0,
            threshold=1.0,
            verdict="PASS",
        )
    density = (len(matches) / total_words) * 500
    verdict = "WARN" if density > 1.0 else "PASS"
    return StructuralVerdict(
        detector="parallel_triplet_density",
        value=density,
        threshold=1.0,
        verdict=verdict,
    )


def compute_style_score(report: FileReport) -> float:
    """style_score = 1 - (critical * 3 + high + 0.3 * medium) / total_sentences.

    Clipped to [0, 1]. Sections under 0.85 trigger auto-revise.
    """
    if report.total_sentences == 0:
        return 1.0
    numerator = (
        len(report.critical) * 3
        + len(report.high)
        + 0.3 * len(report.medium)
    )
    raw = 1.0 - (numerator / report.total_sentences)
    return max(0.0, min(1.0, raw))


def lint_file(path: Path, config: Optional[dict] = None) -> FileReport:
    """Lint a single file. Returns a FileReport."""
    text = path.read_text(encoding="utf-8")
    sentences = split_sentences(text)
    words = count_words(text)
    config = config or {}

    report = FileReport(
        path=str(path),
        total_lines=len(text.splitlines()),
        total_sentences=len(sentences),
        total_words=words,
    )

    report.critical = find_lexical_hits(text, CRITICAL_PATTERNS, "CRITICAL", config=None)
    high_raw = find_lexical_hits(text, HIGH_PATTERNS, "HIGH", config=config)
    medium_raw = find_lexical_hits(text, MEDIUM_PATTERNS, "MEDIUM", config=config)
    # Re-bucket by EFFECTIVE tier: a config/venue `downgrade` relabels a HIGH
    # hit to MEDIUM, so it must move to the medium bucket to actually lower the
    # style score (HIGH weight 1.0 -> MEDIUM weight 0.3); `disable` already
    # dropped the hit inside find_lexical_hits.
    report.high = [h for h in high_raw if h.tier == "HIGH"]
    report.medium = medium_raw + [h for h in high_raw if h.tier == "MEDIUM"]
    report.absolute_bans = find_em_dash(text) + find_bullet_violations(text)

    report.structural = [
        sentence_length_variance(text),
        transition_word_ratio(text),
        parallel_triplet_density(text),
    ]

    report.style_score = compute_style_score(report)

    if (
        report.critical
        or report.absolute_bans
        or any(s.verdict == "BLOCK" for s in report.structural)
    ):
        report.verdict = "BLOCK"
    elif (
        report.high
        or any(s.verdict == "WARN" for s in report.structural)
    ):
        report.verdict = "WARN" if not report.high else "BLOCK"
    elif report.medium:
        report.verdict = "WARN"
    else:
        report.verdict = "PASS"

    if report.style_score < 0.85 and report.verdict == "PASS":
        report.verdict = "WARN"

    return report


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Anti-AI-tic linter for Writer skill.")
    parser.add_argument("files", nargs="+", type=Path, help="Files to lint")
    parser.add_argument("--config", type=Path, default=None,
                        help="Path to ai_tic_config.yaml (per-project overrides)")
    parser.add_argument("--venue", type=str, default=None,
                        help="Venue id; loads references/venue_aitic_defaults/<venue>.yaml "
                             "(merged under --config; project entries win)")
    parser.add_argument("--output", type=Path, default=None,
                        help="Write JSON report to file (default: stdout)")
    args = parser.parse_args(argv)

    config = merge_configs(load_venue_config(args.venue), load_config(args.config))
    reports = [lint_file(f, config=config) for f in args.files]

    output = {
        "version": "1.0",
        "files": [asdict(r) for r in reports],
        "summary": {
            "total_files": len(reports),
            "blocks": sum(1 for r in reports if r.verdict == "BLOCK"),
            "warns": sum(1 for r in reports if r.verdict == "WARN"),
            "passes": sum(1 for r in reports if r.verdict == "PASS"),
        },
    }

    json_text = json.dumps(output, indent=2)
    if args.output:
        args.output.write_text(json_text, encoding="utf-8")
    else:
        print(json_text)

    if output["summary"]["blocks"] > 0:
        return 2
    if output["summary"]["warns"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
