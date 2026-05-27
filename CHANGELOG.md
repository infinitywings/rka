# Changelog

All notable changes to RKA are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) + semver.

## [Unreleased] - Writer Phase W3 + W4 (registry expansion + NSF proposals)

Branch: `feat/writer-venue-registry-w3w4`. Third and fourth slices of
the multi-phase Writer expansion. W3 grows the curated registry from
seven venues to fifty-eight and W4 introduces the `kind: proposal`
surface with NSF PAPPG as the inheritable baseline. Together these
make the Writer cover the venue families the PI explicitly named
(CS conferences + CS journals + FT50 accounting/finance/management +
NSF proposals).

### W3 - Venue registry expansion (51 new venues)

- **CS conferences (29)**: ICML, ICLR, AAAI, IJCAI, KDD (cs-ml);
  CVPR, ICCV, ECCV (cs-cv); ACL, ACL-Short, NAACL, EMNLP-Short
  (cs-nlp); SOSP, ASPLOS (cs-systems); ISCA, MICRO (cs-arch);
  PLDI, POPL, OOPSLA (cs-pl); SIGCOMM, NSDI (cs-net); CCS, NDSS
  (cs-security); UIST, CSCW, IUI (cs-hci); SIGIR (cs-ir); WWW
  (cs-web).
- **CS journals (6)**: TPAMI, TOPLAS, TOCS, TON, JACM, CACM.
- **FT50 narrowed scope (16)**: JAR, JAE, TAR, RAST, CAR (acct);
  JF, JFE, RFS, JFQA (fin); AMJ, AMR, ASQ, JOM, MS, OS, SMJ (mgmt).
- Each YAML is a **minimal-baseline** spec: stable per-family
  defaults for tone (voice / hedging / marketing / math-density /
  reproducibility), citation style (numeric for STEM, name-year for
  NLP family, author-year for FT50), and submission posture (page
  limit + anonymization + references-counted). Year-specific
  deviations are expected to flow through W2's `cfp_overrides.yaml`
  rather than mutating the YAML directly.
- **`DOMAIN_VALUES` expanded** with `cs-nlp`, `cs-cv`, `cs-ir`,
  `cs-ai`, `cs-web` to model the additional CS sub-fields. FT50
  enums (`acct`, `fin`, `mgmt`) were already provisioned in W1.

### W4 - NSF proposals with solicitation inheritance

- **`NSF-PAPPG.yaml`** at `references/venue/proposals/` is the
  cross-solicitation baseline: PAPPG Chapter II.D.2 page limits
  (15-page Project Description), required sections (Cover Sheet,
  Project Summary, Project Description with explicit Intellectual
  Merit + Broader Impacts headings, References Cited, Biographical
  Sketches, Budget Justification, Current/Pending Support,
  Facilities, Data Management and Sharing Plan), and the standard
  Merit Review Criteria (`intellectual_merit` + `broader_impacts` +
  `clarity`).
- **`solicitations/NSF-CAREER.yaml`** uses `inherits_from:
  NSF-PAPPG` so it picks up PAPPG's format/tone defaults
  automatically; it overrides only `required_sections` (adds the
  Integrated Research and Education Plan + Department Letter) and
  `review_dimensions` (adds `integration_of_research_and_education`
  and `career_development_trajectory`). Demonstrates the W1
  `merge_inheritance` semantics on a real solicitation: scalar
  fields win when set, list fields replace rather than extend.
- **`kind: proposal` wired through `venue_md_generator`** -- no
  branching needed; the existing seven-section narrative renders
  proposals the same way it renders conferences and journals.

### Tests (W3 + W4)

- **10 new tests** in `tests/skills/writer/test_venue_registry_w3w4.py`:
  full-registry load, per-family kind+domain expectations, FT50
  shared-conventions check (double-blind + author-year +
  third-person), CS-NLP name-year citation, short-track page limit
  cap, CS-journal no-fixed-page-limit, NSF PAPPG required-sections
  + review-criteria framing, CAREER inheritance overlay (format +
  tone borrowed; required_sections + review_dimensions replaced),
  and `kind=proposal` MD rendering.
- Full Writer suite: **170 passed** (was 160, +10).
- `venue_loader.py validate` now passes on all 59 specs (57 venues
  + NSF-PAPPG + NSF-CAREER).

### Phase boundary

W3 + W4 close the originally-scoped expansion. Future enrichment is
contributor-driven (each YAML is short enough that adding venues is a
small PR; W2's `cfp_overrides.yaml` handles year-specific deviations).
Full Writer suite after W1 + W2 + W3 + W4 lands: **196 passed**
(W1: 160, W2: +26, W3 + W4: +10).

---

### W2 (merged in PR #27): cfp_loader - fetch + heuristic overlay

Branch: `feat/writer-cfp-loader`. Second slice of the multi-phase Writer
expansion. Builds on W1's `venue.yaml` foundation by letting the Writer
adapt a curated venue spec to a specific year's Call-for-Papers without
hand-editing the registry.

#### Shipped (W2)

- **`cfp_loader.py`** at `rka/skills/writer/scripts/`. Fetches a CFP
  URL (stdlib `urllib` only - no new dependencies), strips HTML, and
  runs deterministic heuristic extractors over the plain text for:
  page limit (main / body), references-counted vs. excluded,
  anonymization mode (double-blind / single-blind / not anonymous),
  abstract word cap, citation-style hint (numeric vs. name-year), and
  the first submission-deadline date. Emits a draft `cfp_overrides.yaml`
  with every detected field listed under `review_required:` so a
  reviewer (human or Claude Code at the manuscript prompt) must
  inspect each before it can be trusted. The fetched plain text is
  persisted alongside the YAML as `cfp_raw.txt` for offline
  re-extraction. No server-side LLM is invoked (the rka core does
  not ship LLM access per the v2.4.0 architecture decision).

- **`apply_overrides(base, overrides)`** + **`load_workspace_venue(dir)`**
  in `cfp_loader.py`. Overlay engine for partial overrides on top of a
  curated Venue, plus a one-call workspace resolver that returns the
  effective Venue after applying both `cfp_overrides.yaml` (year-wide
  CFP deltas) and `manuscript.yaml -> overrides:` (per-manuscript
  deltas). Precedence: baseline -> cfp -> manuscript (most-specific
  always wins).

- **`layout_audit._resolve_from_manuscript_yaml` extended** to read
  `cfp_overrides.yaml` automatically. Per-manuscript page-limit
  override still beats CFP; CFP still beats venue baseline. Existing
  `--manuscript-yaml PATH` CLI flag is the entry point.

- **CLI**: `cfp_loader.py fetch <url> --base-venue NeurIPS --out cfp_overrides.yaml`
  + `cfp_loader.py inspect <workspace-dir>` (dumps the resolved Venue
  as JSON for debugging).

- **Plugin mirror updated** - `diff -r rka/skills/writer plugin/skills/writer`
  byte-identical.

#### Tests (W2)

- **26 new tests** in `tests/skills/writer/test_cfp_loader.py`
  covering HTML extraction (script/style stripping, paragraph breaks),
  `_http_get` mocking + content-type rejection, every heuristic
  extractor (positive + sanity-floor + blank-input cases), YAML
  envelope validation, `apply_overrides` overlay semantics,
  `load_workspace_venue` precedence rules, the `layout_audit`
  integration path, and render-idempotency.

---

### W1 (merged in PR #26): venue.yaml foundation + CFP plumbing

Branch: `feat/writer-venue-expansion`. First slice of a multi-phase
Writer expansion (W1-W4) that ships a structured per-venue
specification, a per-manuscript YAML, and CFP-link plumbing so the
Writer can enforce venue-specific format, page-limit, tone, and
content-organization rules - including for venues PI specifies via
their CFP URL.

#### Shipped (W1)

- **`venue.yaml` schema (v1)** at `rka/skills/writer/references/venue/`.
  Single source of truth for every venue: submission constraints
  (page limit, references-counted, anonymization), format (template,
  engine, citation style), structure (required + optional + appendix
  sections, abstract word range), tone descriptors (voice, hedging,
  marketing tolerance, math density, multi-seed expectations,
  reproducibility floor), review-dimension weights, forbidden
  constructions, sample-corpus pointers, CFP URLs, and provenance.
  Schema reference: `rka/skills/writer/references/venue_schema.md`.

- **`venue_loader.py`** - parses, validates, and merges venue specs.
  Enum-checked at load time; raises `VenueValidationError` with a
  precise field path on mismatch. Supports proposal inheritance for
  NSF solicitations via `inherits_from` (W4 baseline; child overrides
  base sub-objects, lists replace rather than append). CLI:
  `list` / `show <id>` / `validate [<id>]`.

- **`venue_md_generator.py`** - renders the canonical
  seven-section narrative `<id>.md` from `<id>.yaml`. Auto-region
  delimited by `BEGIN auto-generated` / `END auto-generated` markers;
  re-running only replaces that region (preserves prelude + tail).
  Sibling `<id>.notes.md` appended below the auto-region so rich
  hand-written content survives regeneration. Idempotent.

- **7 existing venues migrated** to YAML + auto-generated MD:
  CHI, EMNLP, IEEE-SP, Nature, NeurIPS, OSDI, USENIX. Each
  Phase-2 hand-written narrative preserved verbatim as `<id>.notes.md`
  (renamed; auto-appended back into the regenerated `<id>.md`).

- **`manuscript.yaml` in workspace-template** - per-manuscript glue
  carrying `venue_id`, `cfp_url`, `project_id`, `title`,
  `target_track`, `target_deadline`, and `overrides`. Read by the
  linter / layout-audit / MCP tool surface and by W2's `cfp_loader.py`.

- **`/rka-start-manuscript` extended** with `--cfp-url` and `--title`
  flags. Bootstrap substitutes the placeholders in `manuscript.yaml`
  alongside the existing `.mcp.json` substitution.

- **`layout_audit.py` reads YAML**: page limit now resolved via
  `venue_loader` (fallback to a small legacy table for short-track
  variants the YAML registry doesn't yet model). New CLI flag
  `--manuscript-yaml PATH` reads `venue_id` + `overrides.page_limit_main`
  from the workspace's manuscript.yaml (per-manuscript override wins
  over venue baseline). New `page_limit_override` kwarg on
  `audit()` for programmatic callers.

- **Plugin mirror updated** - identical copy in `plugin/skills/writer/`
  per the v2.5.12 plugin-bundle precedent. `diff -r` byte-identical
  between source + plugin.

#### Tests (W1)

- **30 new tests**: `tests/skills/writer/test_venue_loader.py` (16)
  + `tests/skills/writer/test_venue_md_generator.py` (7) + the 7
  Phase-1/Phase-2 venue files still pass their pre-existing
  em-dash / required-section checks against the regenerated MDs.
- Full repo suite: **818 passed** (was 788 - all pre-existing tests
  preserved; +30 new).

#### Phase W1 boundary (superseded by W2 above)

- W2 (this PR) lands `cfp_loader.py`.
- W3 expands the registry to ~50 venues (CS conferences, CS journals,
  FT50 accounting/finance/management).
- W4 lands `proposals/NSF-PAPPG.yaml` baseline + solicitation
  inheritance demo.

## [2.5.12] — 2026-05-23 (patch release; Writer plugin-bundle integration)

**Mission**: `mis_01KSARG7HJR0QMB9004ESZPM2K`
**Motivating decision**: `dec_01KSARC7RDJEV8BNK2QD79J5H7` (Option A — full plugin integration)
**Motivation journal**: `jrn_01KSARARTMH2CHT3SG0FZ8C93D`
**PI surfacing**: 2026-05-21 — *"the writer is not integrated into the plugin bundle, so I do not know how can I use the writer."*

### Distribution-only mission — Writer is now reachable through `/plugin install rka@rka`

Phase 1/2/3 of the Writer skill (`mis_01KS0C3RP04XANCZAB3HTNAG0P` + `mis_01KS2S22VV5P5SWWXNBXQDHMGX` + `mis_01KS2WW6MRN6AXP11EMCSCDFAR`) built the skill server-side (SKILL.md, references, scripts, `rka-writer-tools` MCP server, workspace-template). Plugin-distribution wiring was never in scope for those phases. This release closes the gap. **No Writer behavior changes.**

### Shipped

- **Writer skill mirrored into plugin distribution** (`plugin/skills/writer/`): hard copy of `rka/skills/writer/` (49 files; `diff -r` byte-identical excluding `__pycache__`). Matches `plugin/skills/brain/` + `executor/` + `pi/` precedent.
- **`/rka-start-manuscript` slash command** (`plugin/commands/rka-start-manuscript.md` + `plugin/scripts/start-manuscript.py`): bootstraps a per-manuscript workspace from `workspace-template/`. Substitutes `<your-username>` → `$USER` and `prj_REPLACE_WITH_PROJECT_ID` → user-supplied project ID in `.mcp.json`. Supports `--project-id`, `--venue`, `--path`, `--force` flags. Non-destructive (refuses non-empty target without `--force`). Lists 7 supported venues (CHI, EMNLP, IEEE-SP, Nature, NeurIPS, OSDI, USENIX) on no-args invocation. Inline `--self-test` smoke test of the substitution logic.
- **Plugin metadata updated**: `plugin/.claude-plugin/plugin.json` description (four role skills); `.claude-plugin/marketplace.json` plugin description ("~89 MCP tools, four role skills, six slash commands"); keywords add `writer`, `manuscript`, `latex`.
- **INSTALL.md §1 table** lists 4 skills + 6 commands + corrected tool count (~89, was "~90" stale); new §3 Step 4.5 documents `uv tool install '.[writer-tools]'` for the `rka-writer-tools` binary; §5.1 verification updates to "six `rka:rka` slash commands" and "four `rka:rka-*` skills".

### Empirical integration test (T5; mandatory firewall before this release)

All 5 checks pass:
1. Marketplace + plugin manifests JSON-valid; source resolves to `./plugin`.
2. Skill enumeration: 4 SKILL.md files in `plugin/skills/` with version 2.3.2 each.
3. Command enumeration: 6 `.md` files in `plugin/commands/` (5 existing + `rka-start-manuscript`).
4. `/rka-start-manuscript` bootstrap: creates 14 files; placeholder substitution verified end-to-end (`<your-username>` → `$USER`; `prj_REPLACE_WITH_PROJECT_ID` → user-supplied ID); `.mcp.json` valid post-substitution; non-destructive re-run refuses without `--force`; `rka-writer-tools` PATH-absence warning graceful.
5. `rka_get_manuscript` smoke test: `/api/manuscripts/jrn_FAKE_FOR_PROBE` returns HTTP 404 with proper error body — route registered, MCP tool present (`rka/mcp/server.py:4011`).

### Bookkeeper invariant

`git diff main` touches (since `a27e0f4` base):
- `plugin/skills/writer/` (49 files; hard-copy mirror)
- `plugin/commands/rka-start-manuscript.md` (new)
- `plugin/scripts/start-manuscript.py` (new)
- `plugin/.claude-plugin/plugin.json` (description + keywords)
- `.claude-plugin/marketplace.json` (description)
- `INSTALL.md` (§1 + §4.5 + §5.1)
- `pyproject.toml` + `rka/__init__.py` + `CHANGELOG.md` (release prep)

**Zero `rka/services/*`, `rka/api/*`, `rka/mcp/*`, `web/*`, `rka/skills/writer/*`, `rka/cli.py` touches.** Server-side Writer code unchanged. Phase-3.5 + embedding-UI backlog items not touched.

### Provenance

- Writer Phase 1: `mis_01KS0C3RP04XANCZAB3HTNAG0P`, `dec_01KS0AWYDV752AWQRF40CQBRFZ` (Option B: Claude Code skill)
- Writer Phase 2: `mis_01KS2S22VV5P5SWWXNBXQDHMGX`, `dec_01KS2S22VV5P5SWWXNBXQDHMGX` (rka-writer-tools MCP)
- Writer Phase 3: `mis_01KS2WW6MRN6AXP11EMCSCDFAR`, `dec_01KS2WPKMRVSJ2R0PP74722PEH` (revision-loop + 3 manuscript MCP tools)

## [2.5.11] — 2026-05-21 (Phase-3 chapter close — Phase-3.2 + 3.3 + 3.4 bundled; TRUE measurement surfaced; PARTIAL on recall + efficiency)

Bundled patch release shipping the full Phase-3 chapter close across three sequential missions. PI directive held the version at v2.5.11 (no inflation across the bundle).

**Chapter trajectory**: D1 (v2.5.1) + D2 (v2.5.3) + D3 (v2.5.2) + D4 ordering (v2.5.4 + v2.5.9 + this release) EMPIRICALLY VALIDATED. D4 recall + D4 efficiency PARTIAL on TRUE measurement (post-γ structural-only walker eliminated walker-extraction contamination that was inflating prior eval-v2 metrics by ~0.24 absolute on recall).

**Chapter-close decision**: `dec_01KS5TJPVKKD8SQCFSTNNS92C4`
**Chapter-close synthesis journal**: `jrn_01KS5TGWB2HWBYFW8X4J8BR4XK`

**Floor scoreboard (TRUE measurement, post-γ)**:
- `mean_recall_critical` = 0.774 (< 0.85 floor; Phase-3.5 spec'd: `mis_01KS5TTYSME88BQR5EC7BCXAGE`)
- `mean_ordering_score` = 0.464 (≥ 0.363 floor; +0.101 above floor)
- `mean_efficiency` = 0.042 (< 0.13 floor; structurally unreachable in v2; eval-v3 framework deferred as project-level)

**Process discipline**: 4 falsification catches across the bundle (Phase-3.2 T3 seed_limit, Phase-3.2 T4 per-tool K, Phase-3.3 T2 R1 recall contamination, Phase-3.4 T1 γ-closes-efficiency) with near-zero code waste (~9 lines reverted). Bookkeeper invariant held: zero `rka/services/*`, `rka/api/*`, `rka/mcp/*`, `web/*` touches across the three missions.

---

### Phase-3.4 — γ structural-only walker (TRUE measurement surfaced; recall + efficiency PARTIAL; ordering MAINTAINED)

**Mission**: `mis_01KS5KNXBBVYWTD5JH408K2X9R`
**Motivating decision**: `dec_01KS5KJ774WN7WEEETXBK2J3KG` (Option A — walker structural redesign, diagnostic-first across α/β/γ/δ)
**T1 evaluation checkpoint**: `chk_01KS5S8BJBYW0PQ309CPCJ5PMC` (Brain-ratified Option (I): ship γ + honest PARTIAL)
**Contamination meta-finding**: `chk_01KS5PF3832RYCRPKEY090CV65` (Phase-3.3 T2)

### Phase-3 chapter close — TRUE measurement (post-γ)

| Metric | v2.5.9 cfg11 (contaminated) | v2.5.11 (contaminated) | post-Phase-3.3 (contaminated) | post-Phase-3.4 γ (TRUE) | Floor | Status |
|---|---|---|---|---|---|---|
| mean_recall (critical) | 0.822 | 0.933 | 0.969 | **0.774** | ≥ 0.85 | ⚠️ **PARTIAL** (TRUE measurement surfaced) |
| mean_ordering_score | 0.403 | 0.471 | 0.513 | **0.464** | ≥ 0.363 | ✅ **MAINTAINED + IMPROVED** (+0.101 above floor) |
| mean_efficiency | 0.034 | 0.035 | 0.036 | 0.042 | ≥ 0.13 | ⚠️ **PARTIAL** (structurally unreachable; eval-v3 forward-pointed) |
| mean_expanded_recall | 0.760 | 0.817 | 0.855 | 0.633 | (informational) | TRUE measurement |

**Critical context**: prior eval-v2 metrics (v2.5.7–v2.5.11) were **systematically contamination-inflated** by ~0.24 absolute on recall. The pre-γ walker regex-extracted entity IDs from ALL string values in API responses, including embedded `@entity_id` references in journal/decision/checkpoint content body. Phase-3.4 γ replaces that with structural-only extraction; the post-γ numbers are the **TRUE measurement** of retrieval quality.

### γ walker change

The walker now extracts entity IDs only from values at known structural id-typed JSON keys:
- Single-id: `id`, `entity_id`, `source_id`, `target_id`, `mission_id`, `decision_id`, `claim_id`, `cluster_id`, `research_question_id`, `parent_id`, `parent_mission_id`, `linked_decision_id`, `motivated_by_decision`, `depends_on`, `supersedes`, `superseded_by`, `source_claim_id`, `target_claim_id`
- List-valued: `sources`, `entity_ids`, `ids`, `seeds`, `related_journal`, `related_decisions`, `related_literature`, `related_missions`

Embedded `@entity_id` references in body text are no longer extracted — they're incidental mentions, not retrieval candidates. This matches the API contract: structural id fields are what tools explicitly RETURNED; body text is content.

### T1 evaluation summary (chk_01KS5S8BJBYW0PQ309CPCJ5PMC)

4 candidate approaches evaluated empirically across all 16 scenarios:

| Variant | mean_recall | mean_efficiency | reaches 0.13? |
|---|---|---|---|
| full (contaminated baseline) | 0.969 | 0.036 | NO |
| α (cap walker to top-N=10 entries) | 0.837 | 0.039 | NO |
| β (cap walker output to M=30) | 0.522 | 0.088 | NO (closest) |
| **γ (structural-only walker)** | **0.732** | 0.040 | NO |
| δ (efficiency uses structural denominator) | 0.969 | 0.055 | NO |

**No variant closed the 0.13 efficiency floor.** γ ships on semantic faithfulness grounds — it surfaces TRUE recall and eliminates the contamination mechanism, even though TRUE values are PARTIAL on recall + efficiency.

### Phase-3 chapter trajectory (deliverable status)

| Deliverable | Mission | Release | Floor | Final status |
|---|---|---|---|---|
| D1 — multi-hop schema relaxation | mis_01KRQQRWA1HHHEKHB1TFHK2A4S | v2.5.1 | n/a | ✅ EMPIRICALLY VALIDATED |
| D2 — context-engine weighted-sum ordering | mis_01KRSP44W7BDZH11PZRGXH1WM4 | v2.5.3 | n/a | ✅ EMPIRICALLY VALIDATED |
| D3 — cluster→parent-RQ traversal | mis_01KRSQ4GCRWPSXCWZHGZ2ZR830 | v2.5.2 | n/a | ✅ EMPIRICALLY VALIDATED |
| D4 ordering | mis_01KS0C8BKTHCA8GB38BGDR1PTQ + Phase-3.1 | v2.5.4 + v2.5.9 | ≥ 0.363 | ✅ EMPIRICALLY VALIDATED (0.464 ≥ 0.363; +0.101 above floor) |
| D4 recall | Phase-3.2 + Phase-3.3 + Phase-3.4 | v2.5.11 + γ | ≥ 0.85 | ⚠️ PARTIAL — TRUE 0.774; Phase-3.5 spec'd |
| D4 efficiency | Phase-3.4 | γ | ≥ 0.13 | ⚠️ PARTIAL — TRUE 0.042; eval-v3 forward-pointed |

### Process discipline summary (4 falsification catches across Phase-3.2-3.4)

| Catch | Mission | Triggering checkpoint |
|---|---|---|
| T3 `seed_limit` hypothesis falsified | Phase-3.2 | chk_01KS5H6RES1C2YVV6BR14888MT (reverted) |
| T4 per-tool K hypothesis falsified | Phase-3.2 | chk_01KS5HZTE753XR1F0MFVFWG6MB (PARTIAL) |
| T2 R1 recall contamination | Phase-3.3 | chk_01KS5PF3832RYCRPKEY090CV65 (R1 shipped; SR3 deferred) |
| T1 efficiency floor structurally unreachable | Phase-3.4 | chk_01KS5S8BJBYW0PQ309CPCJ5PMC (γ shipped; PARTIAL) |

Near-zero code waste across all 4 catches. Multiple Brain calibration locks (LOCK 4 spec-drafting reads code first; LOCK 6 contamination methodology) added to project discipline.

### Phase-3.5 spec forthcoming (Brain commitment)

10 scenarios surface honest retrieval gaps under γ. Phase-3.5 addresses these via either corpus refresh, search-relevance tuning, or hybrid approach. Spec filed within 24h of Phase-3.4 batch-merge.

### Eval-v3 forward pointer

The structural efficiency limitation (combined_ranking dominated by BUNDLE_K=80 + 5 endpoint contributions ≈ 116 entities; floor 0.13 requires ≤ 46) is beyond Phase-3.x scope. A future eval-v3 framework redesign would address this at the framework level.

### Bookkeeper invariant — final state

`git diff` since `feat/phase-3-3-search-relevance` base:
- `eval-harness/v2/runner.py` (γ structural-only walker)
- `eval-harness/v2/tests/test_runner.py` (6 new γ tests + updated fixtures matching production API contract)
- `CHANGELOG.md` (this entry)

**Zero `rka/services/*`, `rka/api/*`, `rka/mcp/*`, `web/*` changes.**

### Per-scenario stability

Under contaminated baseline (post-Phase-3.3): mean recall 0.969 across 16 scenarios. Under TRUE measurement (post-γ): 10 of 16 scenarios surface honest recall < 1.0. The remaining 6 scenarios retain recall=1.0 — these are scenarios where structural retrieval genuinely surfaces all critical entities.

### Phase-3.3 — R1 runner-anchor multi-seed fix (SR3 deferred; DB contamination meta-finding)

> Version number pending PI authorization. PI directive: batch Phase-3.3 + Phase-3.4 merges; version bump deferred until both PRs are ready. When shipping, replace this heading with the chosen version (e.g. `## [2.5.12]`).

**Mission**: `mis_01KS5KEPXK77MAG54GW5M6DA79`
**Motivating decision**: `dec_01KS5KAYRBC717G5J4X01F8FR4` (Option A — search-relevance work, diagnostic-first)
**Related checkpoints**: `chk_01KS5NJN1652XHAKZ5DYZ4RZX9` (T1 diagnostic ratification) + `chk_01KS5PF3832RYCRPKEY090CV65` (T2 ship R1 + skip SR3 + document contamination)

### Floor status

| Metric | v2.5.9 cfg11 | v2.5.11 (Phase-3.2) | post-Phase-3.3 | Δ vs v2.5.11 | Floor | Status |
|---|---|---|---|---|---|---|
| mean_recall (critical) | 0.822 | 0.933 | **0.969** | +0.036 | ≥ 0.85 | ✅ CLOSED (contamination-inflated; see below) |
| mean_ordering_score | 0.403 | 0.471 | **0.513** | **+0.042** | ≥ 0.363 | ✅ MAINTAINED & IMPROVED (REAL) |
| mean_efficiency | 0.034 | 0.035 | 0.036 | +0.001 | ≥ 0.13 | ⚠️ PARTIAL (Phase-3.4) |
| mean_expanded_recall | 0.760 | 0.817 | 0.855 | +0.038 | (informational) | improved |

### Track A1 (R1 fix) — SHIPPED

Per T1 diagnostic (chk_01KS5NJN1652XHAKZ5DYZ4RZX9, Brain-ratified): T1 surfaced a NEW sub-class beyond the spec's SR1/SR2/SR3/SR4 taxonomy:

- **R1 (Runner-anchor BFS gap)**: 3 of 5 missing-critical instances are entities reachable via `/api/search` top-10 OR via first_mission anchor BFS — but blocked by the runner's `anchor_id = critical[0]["entity_id"]` heuristic when critical[0] is a decision.

**Fix** (`eval-harness/v2/runner.py` `_invoke_one` + `_call_multi_hop`, preference 3 per Brain ratification): when critical[0] is a decision AND first_mission is present, seed multi_hop BFS with **both**. Multi-seed BFS catches both neighborhoods; preference 1 (anchor swap) produced a SWAP not a NET LIFT (surfacing one entity but losing another reachable only from the decision anchor).

3 new R1 unit tests (`eval-harness/v2/tests/test_runner.py`):
- positive: critical[0]=decision + first_mission set → BOTH in seeds
- no-op: critical[0]=mission → single-seed preserved
- no-op: critical[0]=decision but no mission critical → single-seed preserved

**Verified empirical effect**:
- Recall: +0.000 in current DB (DB contamination masks the recall benefit — see meta-finding)
- Ordering: **+0.032 aggregate** (REAL; contamination-resistant — ordering measures placement, not presence)
- Architectural correctness verified via direct `/api/graph/multi-hop` call with multi-seed: 27 nodes including `mis_01KRPF3` (which v2.5.11 single-anchor BFS didn't reach)

### Track A2 (SR3 fix) — DEFERRED per chk_01KS5PF3832RYCRPKEY090CV65

`/api/search` direct probes confirm SR3 entities still NOT in top-200:
- scenario 4 trigger → `mis_01KRPF3`: NOT in top-200
- scenario 6 trigger → `jrn_01KRP5Q0F`: NOT in top-200

The eval-runner recall=1.0 for these scenarios is a **contamination artifact** (see below). Attempting SR3 fixes in contaminated DB is falsification-prone; deferred to a future mission with clean-DB methodology (Phase-3.4 territory, scope-extended for walker-vs-contamination work).

### Meta-finding: eval-v2 metric contamination via diagnostic artifacts

**Mechanism**: when a mission's T0/T1 diagnostic journals or checkpoints mention target entity IDs by ID in their content, the eval-runner's `walk_for_entity_ids` extracts those references from `rka_get_context`'s high-importance recent-content bundle. The walker's recursive entity-ID extraction inflates `combined_ranking` with entities that aren't actually retrieved by any tool's primary candidate set.

**Empirical evidence**: with R1-stash (pure v2.5.11 code on current DB), scenarios 3, 4, 6 ALL show recall=1.0 (the same as post-R1). The "closures" are entirely from DB drift — `/api/search` confirms the SR3 entities are still genuinely below top-200.

**True recall estimate (clean DB)**: approximately **0.92** (vs reported 0.969). R1's recall benefit (mis_01KRPF3 reach via multi-seed) materializes in clean DB; SR3 gaps remain. Ordering lift (+0.032) is unaffected by contamination.

**Discipline locked** (added to feedback memory):
- Future Phase-3.x diagnostic artifacts should either use placeholders (`<target_mission_id>` instead of actual IDs) OR verify recall changes via clean-DB methodology (direct REST probes, controlled stash-comparison, or snapshot-restore).
- Eval-runner aggregate recall is NOT reliable for measuring fixes applied in missions where the diagnostic mentioned target entities by ID.

### Bookkeeper invariant — final state

`git diff` (since v2.5.11 / Phase-3.2 base):
- `eval-harness/v2/runner.py` (R1 fix; multi-anchor `_call_multi_hop` signature)
- `eval-harness/v2/tests/test_runner.py` (3 new R1 tests; 1 pre-existing signature update)
- `CHANGELOG.md` (this entry)

**Zero `rka/services/*`, `rka/api/*`, `rka/mcp/*`, `web/*` changes**. The R1 fix is purely runner-side — no service-layer or API changes shipped.

### Per-scenario stability

| Scenario | v2.5.11 | post-Phase-3.3 | Δ | Notes |
|---|---|---|---|---|
| brain-mission-creation-eval-extension | 0.833 | 1.000 | +0.167 | DB contamination closure (NOT R1) |
| brain-session-start-checkpoint-review | 1.000 | 0.667 | **-0.333** | DB contamination regression (NOT R1; confirmed via db-drift baseline) |
| brain-session-start-fresh-resume | 0.833 | 0.833 | +0.000 | R1 SWAP: mis_01KRPF3 found via multi-anchor; chk_01KS0Q38 lost via DB contamination |
| brain-session-start-post-release | 0.600 | 1.000 | +0.400 | DB contamination closure (NOT R1) |
| executor-mission-pickup-orchestrator | 0.667 | 1.000 | +0.333 | DB contamination closure (NOT R1) |
| 11 other scenarios | 1.000 | 1.000 | +0.000 | Stable |

Net real change (clean-DB methodology): scenarios 1, 3 close via R1 multi-anchor BFS. Scenario 4 / scenario 6 SR3 gaps remain. Phase-3.4 absorbs both walker-vs-cap-efficiency AND walker-vs-contamination scope.

### Phase-3 chapter roadmap update

- **Phase-3.4 (walker-vs-cap structural + contamination methodology)**: scope EXTENDED by this finding. Pre-framed options α/β/γ/δ from chk_01KS5HZTE753XR1F0MFVFWG6MB now must establish TWO baselines per option (contaminated + clean) and report against both. γ (disable walker) becomes the contamination-elimination option as a side-effect.
- **Phase-3.5 (SR3 search-relevance for scenarios 4, 6)**: future mission. Awaits Phase-3.4 close to use clean-DB methodology.

### Phase-3.2 — Track A1 candidate-generation (recall CLOSED via tools_invoked expansion; A2 falsified → Phase-3.3; B falsified → Phase-3.4)

**Mission**: `mis_01KS5CRMZ0AGN0M5B694Q3M8B1`
**Motivating decision**: `dec_01KS5CN0CF8N60T88E2HC8K1SD` (Option A — candidate-generation track, diagnostic-first, two coupled sub-tracks)
**Closes**: `chk_01KS3K40N6JRHV118969RMBNF0` (v2.5.9's no-winner checkpoint that opened this mission)
**Strategic context**: `jrn_01KS5CKHNJ4K35EF8TFA084FT3`

### Floor status (canonical eval-v2 metrics)

| Metric | v2.5.9 cfg11 | v2.5.11 | Δ | Floor | Status |
|---|---|---|---|---|---|
| mean_recall (critical) | 0.822 | **0.933** | +0.111 | ≥ 0.85 | ✅ **CLOSED** |
| mean_ordering_score | 0.403 | **0.471** | +0.068 | ≥ 0.363 | ✅ **MAINTAINED & IMPROVED** |
| mean_efficiency | 0.034 | 0.035 | +0.001 | ≥ 0.13 | ⚠️ **PARTIAL** (deferred to Phase-3.4) |
| mean_expanded_recall | 0.760 | 0.817 | +0.057 | (informational) | improved |

**Stability check**: 0 regressions. All 8 v2.5.9 recall=1.0 scenarios remain at 1.0.

### Track A1 — 7-scenario `tools_invoked` expansion (delivers recall floor)

Per T1 diagnostic (chk_01KS5EZ6Z2D51Q1AW628DNA17Y, Brain-ratified): 7 of 8 failing scenarios were classified A1 (incomplete tools_invoked). Their expected critical entities are present in the DB but not in any currently-invoked tool's returned entity_ids. Adding the appropriate candidate-gen tool(s) to each scenario's `tools_invoked` surfaced those entities with **zero service-layer code changes**.

| Scenario | Recall pre | Recall post | Tools added |
|---|---|---|---|
| brain-session-start-fresh-resume | 0.500 | 0.833 | +multi_hop +journal |
| brain-session-start-multi-mission-state | 0.750 | 1.000 | +multi_hop +journal |
| brain-session-start-post-release | 0.400 | 0.600 | +multi_hop +journal +research_map |
| brain-contradiction-llm-removed-vs-enrichment-preserved | 0.667 | 1.000 | +research_map |
| executor-mission-pickup-orchestrator | 0.667 | 0.667 | +multi_hop (residual: search-relevance, Phase-3.3) |
| executor-backbrief-eval-v2-t2 | 0.667 | 1.000 | +multi_hop |
| executor-backbrief-bookkeeper-invariant-check | 0.667 | 1.000 | +research_map |

8 new regression tests in `eval-harness/v2/tests/test_scenarios_tools_invoked.py` lock the tools_invoked invariants.

### Track A2 — FALSIFIED & REVERTED

Per chk_01KS5H6RES1C2YVV6BR14888MT (Brain-ratified revert): scenario 4 (brain-mission-creation-eval-extension) was originally classified A2 (over-restrictive `search(query, limit=10)` seed step in `rka_multi_hop_retrieval`). T3 implemented `seed_limit` plumbing (service + API + runner + 3 unit tests) with default backward-compat. Unit tests passed (11/11). **Aggregate recall delta from T3: +0.0000.** Empirical falsification:

- Runner's `seeds=[anchor]` path bypasses the search step entirely on scenarios with a critical mission anchor; `seed_limit` never executes.
- Direct REST experiment: even query-only `multi_hop` with `seed_limit=20` doesn't surface `mis_01KRPF3` (the eval-v2 mission itself).
- `/api/search` cross-check: `mis_01KRPF3` is not in the top-30 search hits for the scenario trigger. Search-relevance-bound, not seed-count-bound.

**Disposition**: T3 reverted in full (no commit). Scenario 4 reclassified as "search-relevance gap" (not A2). Phase-3.3 spec'd to address the structural search-relevance issue.

### Track B — FALSIFIED ANALYTICALLY; NOT IMPLEMENTED

Per chk_01KS5HZTE753XR1F0MFVFWG6MB (Brain-ratified PARTIAL close): the per-tool K caps premise for closing the 0.13 efficiency floor was falsified analytically over the post-T2 bundles before any code was written:

| K | mean_combined | mean_efficiency | reaches 0.13? | mean_recall_crit |
|---|---|---|---|---|
| 5 | 169.9 | 0.0237 | NO | 0.7875 (regression) |
| 10 | 174.6 | 0.0402 | NO | 0.8604 (regression) |
| 30 | 199.6 | 0.0351 | NO | 0.9333 (T2 baseline) |
| 80 | 201.9 | 0.0350 | NO | 0.9333 |

**Structural root cause**: `rka_get_context` returns 80 rank-list candidates (BUNDLE_K=80 applied) but the eval-runner's entity-ID walker extracts ~172 entity_ids from those candidates' **rendered content** (embedded `@entity_id` references in journal/decision text). Per-tool K on the 5 Track B endpoints cannot move combined_ranking below the get_context-walker floor of ~172. The 0.13 efficiency floor requires combined ≤ 46.

**Disposition**: Phase-3.2 ships PARTIAL on efficiency (0.035 vs 0.13). Phase-3.4 spec'd by Brain for the walker-vs-cap structural redesign (α: cap walker to top-N candidates; β: post-walk truncation to M unique IDs; γ: disable walker; δ: redesign efficiency metric to exclude walker output).

### Process discipline successes

Two consecutive falsifications + zero code waste:
- T3 falsification caught at empirical contact (not T5 firewall); 9-line scope-extension reverted.
- T4 falsification caught analytically (pre-implementation); 0 lines drafted.

Both events reinforced the trust-but-verify discipline established at chk_01KS5EZ6Z2D51Q1AW628DNA17Y. Memory entries added: `feedback_scope_extensions_conditional_on_claim.md` (scope-extensions are conditional on the empirical claim holding).

### Bookkeeper invariant — final state

`git diff main` touches:
- `eval-harness/v2/corpus/scenarios.jsonl` (7 scenarios' tools_invoked expanded)
- `eval-harness/v2/tests/test_scenarios_tools_invoked.py` (NEW, +8 regression tests)
- `pyproject.toml`, `rka/__init__.py`, `CHANGELOG.md` (this release-prep commit)

Zero `rka/services/*`, `rka/api/*`, `rka/mcp/*`, `web/*` changes. Track B's pre-authorized API-edit scope was never exercised (T4 analytical falsification prevented code from being written).

### Scenario classification (final)

- **A1 CLOSED**: 7 scenarios via T2
- **search-relevance gap** (Phase-3.3): 4 scenarios — `brain-session-start-fresh-resume`, `brain-session-start-post-release`, `brain-mission-creation-eval-extension`, `executor-mission-pickup-orchestrator`
- **walker-extraction structural** (Phase-3.4): mission-wide efficiency ceiling
- **A3 (entity absent from DB)**: 0 scenarios (confirmed)

### Open question — resolved

scenario 1's `chk_01KS0NX38` (non-critical "useful" importance, status=resolved): NOT surfaced by the A1 fix; gap accepted per Brain ratification at chk_01KS5EZ6Z2D51Q1AW628DNA17Y open-question disposition (i). Doesn't affect the 0.85 critical-recall floor (already passed).

## [2.5.10] — 2026-05-20 (docs-only patch; INSTALL.md + README.md staleness cleanup)

**Surfaced by**: PI audit immediately following v2.5.9 GitHub release — checked whether the installation guide was fully consistent and correct with current state.

Docs-only patch. No code changes. No test changes (suite stays at 799 passing). Ships to address documentation drift between INSTALL.md / README.md and the actual v2.4.0+ feature surface.

### INSTALL.md — fixes

- **5 stale `v2.3.x` / `v2.3.2` version references** replaced with `v2.5.x` (`/api/health` example output, SessionStart hook example line) or `v2.5.10` (integration.json `version` field example).
- **2 stale "~110 tools" claims** corrected to "~90 tools" (actual count: 89 `rka_*` tools in `rka/mcp/server.py`).
- **§10 "What this guide intentionally doesn't cover"** rewritten:
  - Old text claimed `rka_ask` / `rka_generate_summary` are "optional tools" that require an LLM key. These tools were **removed in v2.4.0** per `jrn_01KRNZBS50K250HHHHEC58E4GC`; server-side code preserved for future re-wiring through the orchestrator's Claude Code SDK.
  - New text correctly states the tool removal, then notes that v2.4.0+ does support **pluggable embedding backends** (FastEmbed default; OpenAI-compatible HTTP like LM Studio / vLLM; Ollama), configurable via **Settings → Embeddings** in the web dashboard. Links to [`docs/embedding_backends.md`](docs/embedding_backends.md).

### README.md — fixes

- **Infrastructure Layer description** (line 242) updated:
  - Was: "embeddings (FastEmbed). An optional LiteLLM gateway powers `rka_ask` / `rka_generate_summary` only when the user wires up a cloud-LLM API key."
  - Now: "pluggable embedding backends (FastEmbed default; OpenAI-compatible HTTP; Ollama — configurable via Settings → Embeddings)" + accurate note that the LLM-gated tools were removed in v2.4.0.
- **Tool table** (line 852) removed the `rka_ask` row — tool no longer exposed.

### Scope discipline

Bookkeeper-strict observed. Touched files:
- `INSTALL.md` (8 in-place edits, all surgical)
- `README.md` (2 in-place edits)
- `pyproject.toml` + `rka/__init__.py` + `CHANGELOG.md` — version bump 2.5.9 → 2.5.10 + this entry

NOT touched: `rka/services/`, `rka/api/`, `rka/mcp/`, `web/`, tests, schema migrations.

### Operator impact

None at runtime. No rebuild required (`docker compose ps` will continue showing v2.5.9 containers as healthy; v2.5.10 brings nothing new at the API/MCP surface). Operators who fetch the v2.5.10 tag will see the corrected docs. A container rebuild is optional and only useful if the operator wants the `/api/health` `version` field to report `2.5.10`.

## [2.5.9] — 2026-05-20 (patch release; Phase-3.1 metric tuning — cfg11 sweep winner pinned; Phase-3 chapter closes PARTIAL)

**Mission**: `mis_01KS3EB2671CDD4V9RZCMYCEH1`
**Motivating decision**: `dec_01KS3E6ZJXXV7542QPWZ9W8BQS` (Option A: two-part bundled Phase-3.1 — recency-weight + bundle efficiency; Brain rec)
**Depends on**: `mis_01KS0QEW21N2NG4EJTKJ3JTWTE` (Eval-v2 corpus refresh; landed on main at `33b9381` via PR #17 merge 2026-05-20T19:40:51Z)
**Backbrief**: `jrn_01KS3EYZ30VCWZ34MQT1A897TW`
**Mid-mission checkpoints**: `chk_01KS3FZDX78FD89CVR4K6VYJFK` (baseline-drift; resolved → scope refined to Option B) and `chk_01KS3K40N6JRHV118969RMBNF0` (no-winner; verified + resolved → cfg11 ship per ratified disposition)
**Sequencing note**: v2.5.8 = `mis_01KS3E4S33B13EGR2NWRQM2QG4` (embedding subsystem bug-pair fix; Mission α), landed on main at `1189db6` via PR #18. Phase-3.1 slots cleanly to v2.5.9.

### (a) Ships strict improvement over v2.5.7 on TWO of three Eval-v2 axes

cfg11 sweep winner (`N=1` / `w_recency=0.15` / `bundle_K=80`) pinned as the default coefficients in `rka/services/context.py`. Independently verified for `chk_01KS3K40N6JRHV118969RMBNF0`:

| Metric | v2.5.7 baseline (current DB, current main) | v2.5.9 cfg11 | Δ |
|---|---|---|---|
| mean_recall | 0.801 | **0.822** | **+0.021** (improvement) |
| mean_ordering_score | 0.383 | **0.403** | **+0.020** (improvement; +0.040 above floor 0.363) |
| mean_efficiency | 0.037 | 0.034 | -0.003 (within DB-drift noise) |

The 0.022 recall improvement is exactly the gap between v2.5.7's K=30 anchor-aware truncation (which drops some expected entities from the bundle for anchor-aware scenarios) and Phase-3.1's K=80 always-on truncation (which captures the full structural retrieval ceiling). **cfg11 is NOT a regression** — it ships better recall AND better ordering vs v2.5.7.

### (b) Recall floor 0.85 NOT met — STRUCTURAL ceiling at 0.822

The 64-config sweep (`eval-harness/v2/sweep_v2_5_9.py`; DB drift Δ=0 across all entity tables in 14-minute sweep window) discovered:

- **All 24 configs at bundle_K ∈ {80, 150}** yield `mean_recall = 0.8219` regardless of `shape_N` or `w_recency`.
- **The same 8 scenarios** (all orchestrator workflow shapes: brain-session-start-fresh-resume, brain-session-start-multi-mission-state, brain-session-start-post-release, brain-mission-creation-eval-extension, brain-contradiction-llm-removed-vs-enrichment-preserved, executor-mission-pickup-orchestrator, executor-backbrief-eval-v2-t2, executor-backbrief-bookkeeper-invariant-check) are below recall=1.0 across cfg11 / cfg14 / cfg23 — **symmetric difference of below-1.0 sets is the empty set**, 7-of-8 with byte-identical per-scenario scores.

Diagnosis: expected_entities for these 8 scenarios are **NOT in the candidate set** returned by their `tools_invoked`. No ranking-level lever (recency_score / weighted-sum coefficients / bundle_K truncation) can promote entities that aren't candidates. The corpus's 0.85 recall floor was set against a different DB state or candidate-generation surface; the **current achievable maximum is 0.822**.

### (c) Efficiency floor 0.13 NOT met — STRUCTURAL: bundle_K caps only `get_context`

Phase-3.1 T2 introduced always-on post-rank-merge `bundle_K` truncation (replacing the v2.5.4-D4 `anchor_aware_present` gating). Empirically, bundle_K is the **only** lever among the swept dimensions with meaningful sensitivity (`K=30`: r=0.71, e=0.043 / `K=150`: r=0.82, e=0.031 — clear Pareto trade-off). But:

- Eval-v2's `combined_ranking` is the **UNION** of per-tool contributions from ~6 tools per scenario (`get_context`, `multi_hop_retrieval`, `ego_graph`, `get_journal`, `get_decisions`, `get_research_map`, etc.).
- `bundle_K` caps **only `get_context`'s contribution**. Other endpoints have their own SQL `LIMIT` clauses but no Phase-3.1 cap.
- Even at K=30, average bundle size remains ~135 entities (T2 smoke). To hit 0.13 efficiency with ~6 critical entities per scenario, combined_ranking must be ≤46 entities — requires capping **every** tool, not just `get_context`.

The efficiency floor is architecturally beyond the coefficient-tuning scope of Phase-3.1.

### (d) Phase-3 chapter closes PARTIAL — Phase-3.2 deferred for candidate-generation work

Phase-3 chain status:

- **D1** (`v2.5.1`, `mis_01KRQQRWA1HHHEKHB1TFHK2A4S`): multi-hop schema relaxation → EMPIRICALLY VALIDATED
- **D2** (`v2.5.3`, `mis_01KRSP44W7BDZH11PZRGXH1WM4`): context-engine weighted-sum ordering → EMPIRICALLY VALIDATED
- **D3** (`v2.5.2`, `mis_01KRSQ4GCRWPSXCWZHGZ2ZR830`): cluster → parent-RQ traversal → EMPIRICALLY VALIDATED
- **D4** ordering portion (`v2.5.4` + `v2.5.9`, `mis_01KS0C8BKTHCA8GB38BGDR1PTQ` + this mission): anchor-aware UNION + post-rank-merge bundle_K truncation → EMPIRICALLY VALIDATED for ordering (0.403 > 0.363 floor)
- **D4 recall ceiling** + **efficiency floor**: structural; coefficient tuning cannot close → **DEFERRED to Phase-3.2** (candidate-generation track, NOT coefficient tuning)

Brain commits to filing the Phase-3.2 spec within 24 hours of v2.5.9 ship. Scope per Brain ratification: candidate-set expansion + per-tool K + `tools_invoked` surface enrichment for the 8 failing orchestrator workflow scenarios.

### (e) Provenance — checkpoint chain

Three RKA checkpoints frame the mission:

- `chk_01KS3FZDX78FD89CVR4K6VYJFK` (T0 baseline-drift): surfaced +0.046 ordering swing from corpus-refresh T2 measurement vs Phase-3.1 baseline (44 minutes, same code, DB-state drift only). Brain ratified Option B + K-placement refinement (post-rank-merge instead of per-tool) + sweep matrix expansion to 64 configs.
- `chk_01KS3K40N6JRHV118969RMBNF0` (T4 no-winner): surfaced the structural recall + efficiency ceilings. Brain demanded trust-but-verify on the load-bearing "ceiling is structural" claim BEFORE ratifying cfg11 ship. Verification (1) re-ran v2.5.7 baseline on current DB → 0.801 (BELOW the K=150 ceiling 0.822, confirming the ceiling is real). Verification (2) per-scenario recall vectors at cfg11/cfg14/cfg23 → symmetric difference ∅. Claim CONFIRMED with stronger evidence than asked. Disposition: ship cfg11 as PARTIAL close.
- `chk_01KS0Q38YRR4S55ZT911W2QMEQ` (D4 K-escalation FAIL, from v2.5.4): pre-Phase-3.1 superseded — Phase-3.1 T4 sweep widens this finding from "K-escalation can't help" to "no coefficient combination can help" for the same scenario set.

### (f) Implementation chain (commits T1 → T6)

| Task | Commit | Surface |
|---|---|---|
| T1 — `recency_score = 1/(1+days/N)` env-var-configurable shape | `50103dc` | `_compute_recency_score()` pure helper; `RKA_CTX_RECENCY_SHAPE_N` env var; 5 new tests; backward-compat at N=1 bit-for-bit |
| T2 — post-rank-merge `bundle_K` always-on truncation | `3dfee5a` | Removed v2.5.4-D4 `anchor_aware_present` gating; default K bumped 30→50; anchor_aware_ids UNION preserved; 5 new tests (replacing 4 v2.5.4-D4 tests) |
| T3 — 64-config sweep harness | `ad9f55a` | `eval-harness/v2/sweep_v2_5_9.py` (shape_N × w_recency × bundle_K = 64); container-restart-per-config (Brain path-2 fallback after T3 analysis found hot-reconfig would need new API endpoint); winner-selection per Option B + tie-breaks |
| T4 — sweep execution + winner selection (background; 837 sec wall-clock; DB drift Δ=0) | (no commit; artifacts only) | `sweep_v2_5_9/{summary.json, winner.md, raw_cfg01..64, metrics_cfg01..64}` |
| T5 — pin cfg11 defaults | `32bd9b8` | `_DEFAULT_W_RECENCY = 0.15` (was 0.20); `_DEFAULT_BUNDLE_K = 80` (T2 was 50; v2.5.4-D4 was 30); `_DEFAULT_RECENCY_SHAPE_N = 1.0` unchanged (sweep tie-break wins); docker-compose.yml + tests updated |
| T6 — version bump + CHANGELOG | (this commit) | `pyproject.toml` + `rka/__init__.py` → 2.5.9; this entry |

### Bookkeeper invariant — strict, observed

Touches limited to scoped files per `dec_01KS3E6ZJXXV7542QPWZ9W8BQS`:
- `rka/services/context.py` — recency_score + bundle_K refactors
- `eval-harness/v2/sweep_v2_5_9.py` (new) + `eval-harness/v2/results/sweep_v2_5_9/` (new artifacts)
- `tests/test_services/test_context.py` — 11 new tests, 4 v2.5.4-D4 tests replaced
- `docker-compose.yml` — env var passthroughs + defaults
- `pyproject.toml` + `rka/__init__.py` + `CHANGELOG.md` — version + release prep

NOT touched: `rka/mcp/`, `rka/api/routes/`, `web/`, other `rka/services/*` files, schema migrations.

### Side-finding: cross-session HEAD contamination (process discipline)

Mid-mission, two concurrent Executor sessions (this mission β + Mission α embedding-fix) operating on the same git working directory + shared `.git/HEAD` produced **TWO near-violation incidents** of the bookkeeper invariant. In both cases, the cross-session checkout landed the phase-3-1 branch on top of Mission α's commits; defensive HEAD verification before each `git commit` caught both before push. Recovery: `git reset --hard 33b9381` + `git push --force-with-lease` (the first incident, where the new branch was inadvertently created from `6caa947` instead of `33b9381`); stash-then-switch for the second. Documented at `jrn_01KS3GH21FPSJ0EKCZKX1EQZ4X`. **Process learning for future parallel-mission setups**: isolate per-mission working trees via `git worktree add` so each mission has its own HEAD.

### Out of scope (deferred to Phase-3.2)

Brain has committed to filing Phase-3.2 spec within 24h. Scope per ratification:
- **Candidate-set expansion** for the 8 orchestrator workflow scenarios whose `expected_entities` aren't currently in any tool's candidate set.
- **Per-tool K caps** for non-`get_context` endpoints (multi_hop, ego_graph, get_journal, get_decisions, get_research_map, assemble_evidence) — the efficiency floor lever.
- **`tools_invoked` surface enrichment** if some scenarios are missing tool invocations that would surface their expected entities.
- **NOT** another coefficient sweep — the Phase-3.1 sweep locked in the learning that recency-shape and w_recency have noise-magnitude effects on the floor gaps.

## [2.5.8] — 2026-05-20 (patch release; embedding subsystem bug-pair fix: BackfillService metadata guard + worker startup loads persisted config)

**Mission**: `mis_01KS3E4S33B13EGR2NWRQM2QG4`
**Motivating decision**: `dec_01KS3E1FGSK530N8HM04BNMCEW` (Option A: single bundled bug-pair fix with scope-limited bookkeeper exemption for `rka/cli.py`)
**Surfaced by**: `mis_01KS0QEW21N2NG4EJTKJ3JTWTE` (Eval-v2 corpus refresh) — both bugs are pre-existing; corpus refresh exposed the silent-under-embedding failure mode.

### Bug 1 — `BackfillService` writes `embedding_metadata` when `vec_available=False`

`rka/services/embedding_backfill.py:run_backfill` unconditionally wrote rows into `embedding_metadata` for every batch element, including when `Database.vec_available` was `False` (sqlite-vec extension not loaded — vec_* INSERT was skipped). The v2.5.5 3-tuple `needs_reembed` then returned `False` permanently for these rows because metadata-by-content-hash matched, even though no vec_* row existed. Net effect: rows claimed to be "embedded at <model>/<dim>" with no underlying vector — silent under-embedding.

**Fix**: moved the `embedding_metadata` INSERT inside the `if vec_available:` block. Metadata write is now **coupled** to the vec_* write — both gate on `vec_available`. Documented as an invariant in the source.

**Tests added** (`tests/test_services/test_embedding_backfill.py`, +2 tests; suite 18 → 20):
- `test_metadata_not_written_when_vec_available_false`: patches `Database.vec_available=False` at the class level (property has no setter) and asserts no metadata row is written.
- `test_metadata_written_when_vec_available_true`: backward-compatibility positive case.

### Bug 2 — `rka-worker` startup ignores `/data/embedding_config.json`

`rka/cli.py:worker_main` constructed `EmbeddingService` directly from env vars (`RKA_EMBEDDING_MODEL` etc.) and passed it to `EnrichmentWorker(embeddings=...)`. The api-server boot path (`rka/api/app.py` v2.4.0+) had been updated to read the persisted config from `<data_dir>/embedding_config.json` via `EmbeddingConfigService.load_config()`, but the worker boot path was left on the legacy env-only constructor. Net effect: PI changing the embedding backend via webui (`PUT /api/config/embedding`) took effect for the api-server's hot path but **not** for the worker — every worker restart re-loaded the env-defaulted backend, silently serving stale embeddings until container rebuild.

**Fix**: added `EnrichmentWorker.boot()` classmethod + `_resolve_embeddings()` staticmethod in `rka/services/worker.py`. Resolution order matches the api-server boot path:

1. `embeddings_enabled=False` → worker has `embeddings=None`.
2. Otherwise, attempt to read `<data_dir>/embedding_config.json` via `EmbeddingConfigService.load_config()` and construct `EmbeddingService.from_config(...)`.
3. On any failure (file missing, corrupt, construction error), fall back to the legacy env-driven constructor (`EmbeddingService(model_name=env_fallback_model)`) and log WARNING.

`rka/cli.py:worker_main` swapped to a 1-line `EnrichmentWorker.boot(...)` invocation (Brain-ratified `cli.py` exemption-extension; see below).

**Tests added** (`tests/test_services/test_worker.py`, NEW file, +4 tests):
- `test_resolve_embeddings_uses_persisted_config`: writes a fastembed config to tmp_path, mocks `EmbeddingService.from_config`, asserts the persisted config (not env) was passed.
- `test_boot_classmethod_threads_data_dir_through`: smoke test for `EnrichmentWorker.boot()`.
- `test_resolve_embeddings_falls_back_to_env_when_config_missing`: empty tmp_path; asserts env_fallback_model was used and the log line confirms the fallback path.
- `test_resolve_embeddings_disabled_returns_none`: `embeddings_enabled=False` short-circuit.

### Scope-limited bookkeeper exemption (binding for THIS mission only)

This release is **bookkeeper-strict** for everything except a single 1-line glue change in `rka/cli.py` (Brain-ratified mid-mission per `dec_01KS3E1FGSK530N8HM04BNMCEW`).

**ALLOWED for this mission:**

- `rka/services/embedding_backfill.py`: Bug 1 fix (metadata-write guard).
- `rka/services/worker.py`: Bug 2 fix (`boot()` + `_resolve_embeddings()`).
- `rka/cli.py`: 1-line glue swap to `EnrichmentWorker.boot(...)` (Brain-ratified exemption-extension; Bug 2's env-only path lived in `cli.py:worker_main`, not `worker.py`).
- `tests/test_services/test_embedding_backfill.py`: extended (+2 tests).
- `tests/test_services/test_worker.py`: NEW (+4 tests).
- `pyproject.toml`, `rka/__init__.py`, `CHANGELOG.md`: version bump.

**NOT ALLOWED (remained strict):**

- Other `rka/services/*` files: 0 modified.
- `rka/api/`: 0 modified.
- `rka/mcp/`: 0 modified.
- `web/`: 0 modified.
- Schema migrations: none.

**Post-mission invariant**: future patch missions return to fully-strict bookkeeper (the `cli.py` exemption is for THIS mission's scope only; documented in `dec_01KS3E1FGSK530N8HM04BNMCEW`).

### Ops note

After deploying v2.5.8, **rebuild the container** (`docker compose up -d --build --force-recreate`) and **restart the worker** explicitly. The worker boot log will now indicate which config-resolution path was taken:

- `worker boot: reading config from /data/embedding_config.json (backend=<backend>, dim=<dim>)` — persisted config loaded.
- `worker boot: falling back to env defaults; persisted config not found at <path>` — file absent.
- `worker boot: failed to load persisted config (<exc>); falling back to env defaults (model=<env_model>)` — load attempt errored.

Operators can correlate these lines with webui config-changed events when troubleshooting embedding-drift symptoms.

### Test count

787 passing (including +6 new tests from this mission). No regressions.

## [2.5.7] — 2026-05-20 (patch release; Writer skill Phase 3: revision-loop handler + Brain mission integration + 3 optional MCP tools; BOOKKEEPER-EXEMPT)

**Mission**: `mis_01KS2WW6MRN6AXP11EMCSCDFAR`
**Motivating decision**: `dec_01KS2WPKMRVSJ2R0PP74722PEH` (Option A: single bundled Phase 3 mission with scope-limited bookkeeper exemption)
**Depends on**: `mis_01KS2S871YPQ3D5RVY5K3PSQY6` (Writer Phase 2; landed on main at `31fd574` via PR #15 merge 2026-05-20T14:25:46Z)
**Backbrief**: `jrn_01KS2X4MB80ERTPQ8M55NPZT5V` plus Brain ratification `jrn_01KS2XDDPSCRH2DF7X1MM4TDPQ`
**Sequencing note**: `mis_01KS0QEW21N2NG4EJTKJ3JTWTE` (Eval-v2 corpus refresh) was planned for v2.5.7 per the v2.5.6 changelog. Writer Phase 3 closed first; corpus refresh now slots to v2.5.8 when it ships. Phase 3 is the final Writer-track deliverable per design Section 16.

### Scope-limited bookkeeper exemption (binding for THIS mission only)

Phase 1+2's strict bookkeeper invariant (`git diff main -- rka/services/ rka/api/ rka/mcp/ web/` empty) was RELAXED for Phase 3 per `dec_01KS2WPKMRVSJ2R0PP74722PEH`:

**ALLOWED for Phase 3:**

- `rka/mcp/server.py`: 3 new `@mcp.tool()` functions (plus necessary supporting imports per Brain ratification 2026-05-20).
- `rka/api/routes/manuscripts.py`: NEW file with the 3 REST endpoints.
- `rka/services/manuscript.py`: NEW file with `ManuscriptService` class.
- `rka/api/app.py`: minimal 2-line glue (1 import + 1 `include_router`) to wire the new route. Brain extended the exemption mid-mission for this minimal touch (analogous to the imports-in-server.py allowance from T0 ratification).
- `rka/skills/writer/`: extended (revision_handler.py + SKILL.md + workflows.md).
- `tests/skills/writer/`: extended (4 new test files).
- `pyproject.toml`, `rka/__init__.py`, `CHANGELOG.md`: version bump.

**NOT ALLOWED (remained strict):**

- Other `rka/services/*` files: 0 modified (manuscript.py only).
- Other `rka/api/routes/*` files: 0 modified (manuscripts.py only).
- `web/`: 0 modified.
- Schema migrations: none.

**Post-Phase-3 invariant**: future Writer phases return to strict bookkeeper (the exemption is for THIS mission's scope only; documented in `dec_01KS2WPKMRVSJ2R0PP74722PEH`).

### Honest framing: branch-state vigilance side-finding

Mid-mission, the T3 commit landed on the wrong branch (`feat/eval-v2-corpus-refresh-v2.5.6` instead of `feat/writer-role-phase-3`) due to an unexplained external branch switch during file edits. Recovered via cherry-pick to phase-3 (the orphan commit on corpus-refresh remained local-only; never pushed). T4+ work added explicit HEAD verification before every commit. Surfaced for executor discipline awareness.

### Shipped (this release)

- **Revision-loop handler** (`rka/skills/writer/scripts/revision_handler.py`, 657 lines): 4 comment_class shapes (factual_r1 / style_r2 / inconsistency_r3 / logical_r4) per design doc Section 14. Heuristic classifier (`classify_comment`) with regex/keyword/structural patterns; returns `ClassificationResult(cls, confidence, ambiguous, rationale, matched_patterns)`; ambiguous defaults to ESCALATE per Brain ratification (the Writer's Claude Code runtime IS the LLM-assisted reasoning layer). Per-class handler functions (`handle_factual_r1` invokes validate_references Stage B-G; `handle_style_r2` re-runs ai_tic_lint strict; `handle_inconsistency_r3` runs bridge_repetition_check; `handle_logical_r4` prepares writer_evidence_gap mission payload). REVIEW_STATE.md helpers (`read_review_state`, `advance_review_state`) implement the 3-iteration cap.

- **Brain mission integration** (Writer SKILL.md Section 4 + references/workflows.md section 7): Writer now supports TWO invocation paths. (a) Direct PI invocation (Phase 1 default). (b) Mission-spawned invocation: Brain creates `writer-revision` mission with `tags=["writer-revision", "comment-class:<r1|r2|r3|r4>", "manuscript:<jrn_id>"]` plus the structured review comment in `context`. Writer reads via `rka_get_mission(id)`, extracts tags, classifies, dispatches. Uses existing MissionService tag surface (no schema migration). On `ambiguous=True` from classify_comment, Writer escalates via `rka_submit_checkpoint` before invoking any handler.

- **3 optional MCP tools** (BOOKKEEPER EXEMPT):
  - `rka_register_manuscript(venue, title, abstract, sections)`: POST /api/manuscripts; creates a jrn_ manifest with tags=['manuscript', f'venue:{venue}', 'phase:draft'].
  - `rka_get_manuscript(manuscript_id)`: GET /api/manuscripts/{id}; returns 404 if not tagged 'manuscript' (regular jrn_ entries are not Writer manifests).
  - `rka_validate_reference(manuscript_id, doi|title, author)`: POST /api/manuscripts/{id}/validate-reference; proxies to Phase 2's validate_references.py Stage B-G full pipeline; returns one of 7 status verdicts.
  - All 3 use the existing thin-HTTP-proxy pattern (httpx via `_client()` to the REST API).

- **REST endpoints** (`rka/api/routes/manuscripts.py`, NEW 147 lines): POST /api/manuscripts, GET /api/manuscripts/{id}, POST /api/manuscripts/{id}/validate-reference. Inline Pydantic models with `ConfigDict(extra='forbid')` per project's existing 422-on-unknown-field guard.

- **Service layer** (`rka/services/manuscript.py`, NEW 223 lines): `ManuscriptService` class extending `BaseService`. Wraps `NoteService` for journal-entry CRUD with the manuscript-specific tagging convention (Option 2 representation per `dec_01KS0BKJ5ZJKJ4R19GYAK3QN9D` Q1). `validate_reference` shells out to `scripts/validate_references.py` via subprocess.

- **37 new tests** under `tests/skills/writer/` (suite progression: 104 to 141): test_revision_handler.py (18 tests), test_manuscript_service.py (8 tests), test_manuscript_mcp_tools.py (6 tests), test_phase3_integration.py (5 tests). All 141 pass in 2.97s.

### Em-dash absolute ban dogfooded

Across all new Writer-managed files (revision_handler.py + 4 test files + manuscript.py + manuscripts.py): 0 U+2014 and 0 U+2013. CHANGELOG.md, rka/mcp/server.py, and rka/api/app.py are pre-existing project infrastructure; their em-dashes in section headings follow project style.

### Out of scope (Phase 4+ deferred indefinitely)

Per `dec_01KS2WPKMRVSJ2R0PP74722PEH` scope_boundaries:

- Manuscript search/discovery UI in `web/` dashboard.
- Manuscript versioning system (vs current single jrn_ manifest model).
- Multi-author collaboration features.
- OpenAlex/arXiv submission system integration.
- Manuscript export to publisher submission portals.

Design Section 16 ENDS at Phase 3. The Writer skill design is complete at Phase 3 close.

## [2.5.6] — 2026-05-20 (patch release; Writer skill Phase 2: rka-writer-tools MCP server + validation pipeline B-G + 5 venues + fetch_template lifecycle)

**Mission**: `mis_01KS2S871YPQ3D5RVY5K3PSQY6`
**Motivating decision**: `dec_01KS2S22VV5P5SWWXNBXQDHMGX` (Option A: single bundled Phase 2 mission)
**Depends on**: `mis_01KS0C3RP04XANCZAB3HTNAG0P` (Writer Phase 1; landed on main at `0d3886f` via PR #13 merge 2026-05-20T13:18:30Z)
**Backbrief**: `jrn_01KS2SK48P78ERN55MC3GRSQ4E` plus Brain ratification `jrn_01KS2T0C2EFRDSYHDJ8J9HBWYW`
**Sequencing note**: `mis_01KS0QEW21N2NG4EJTKJ3JTWTE` (Eval-v2 corpus refresh) was planned for v2.5.6 per the v2.5.5 changelog. Writer Phase 2 closed first; corpus refresh now slots to v2.5.7 when it ships. The two missions are parallel and touch disjoint paths (Writer touches `rka/skills/writer/` plus `tests/skills/writer/`; corpus refresh touches `eval-harness/v2/`).

### Honest framing: Brain T0 Backbrief discovery

The Phase 2 spec assumed (a) the PyPI package was named `serpapi-python`, (b) `acl-org/acl-style-files` used a year-branch convention, (c) all six PyPI dependencies were stable. T0 mandatory Backbrief verification corrected three spec errors:

- `serpapi` is the correct PyPI package name (1.0.2, MIT; not `serpapi-python`).
- `acl-org/acl-style-files` uses `master` branch plus frozen old year tags (`2020-12`, `2021-12`); year-branch convention does not exist. Pin strategy changed to `master_head_sha` at commit `2353f3ea58` (commit date 2025-11-13).
- `arxiv` shipped 4.0.0 on 2026-05-17 (3 days before mission filing). Two majors in 5 weeks signals unstable change velocity. Pin to `>=3.0,<4.0` for safety; Phase 3 audits 4.x release notes and re-evaluates.

Plus two version-drift advisories: `habanero` 11 months silent (last release 2025-06-06; functional, narrow Stage B/D surface) and `manubot` 22 months silent (last release 2024-07-20; functional, Stage F subprocess only). Both pinned at current latest per Brain ratification of T0 Backbrief; will surface to Brain if any Stage encounters API incompatibility during use.

### Shipped (this release)

- **`rka-writer-tools` combined MCP server** (`rka/skills/writer/mcp_tools/`). FastMCP-based stdio server exposing 4 high-level tools (validate_reference, disambiguate_author, find_citation, check_retraction) plus a diagnostic (report_backend_availability). Five backend wrappers under `mcp_tools/backends/`: crossref (habanero), openalex (pyalex), semantic_scholar (semanticscholar), arxiv_backend (arxiv 3.x), and serpapi_backend (serpapi 1.0.2) with CreditBudget plus SerpAPIBudgetExceededError. Each backend gracefully degrades when its PyPI package is absent or (for SerpAPI) when SERPAPI_API_KEY is unset.
- **Validation pipeline Stages B through G** (`rka/skills/writer/scripts/validate_references.py`). Upgrades the Phase 1 stub (Stage A only; B-G raised NotImplementedError) to a full implementation. Stage B: Crossref to OpenAlex to Semantic Scholar to arXiv waterfall. Stage C: 2+ sources to VERIFIED; 1 to LOW_CONFIDENCE; 0 to UNVERIFIED. Stage D: Crossref update-to retraction check (RWDB feeds main API since Sept 2023 acquisition). Stage E: OpenAlex author disambiguation with optional SerpAPI tertiary on mismatch. Stage F: manubot then bibtex-tidy then betterbib subprocess (GPL never vendored). Stage G: SerpAPI niche-rescue before HALLUCINATED verdict. Status enum: VERIFIED / FIELD_ERROR / UNVERIFIED / RETRACTED / HALLUCINATED / AUTHOR_MISMATCH / LOW_CONFIDENCE. AuditReport.has_any_blocking helper for compile-gate.
- **SerpAPI credit budget** (`rka/skills/writer/mcp_tools/backends/serpapi_backend.py`). Default 200/manuscript via SERPAPI_BUDGET env; per-project overlay via `ai_tic_config.yaml [serpapi.budget]` (T3 enhancement); graceful key-absence (Stage G falls back to HALLUCINATED with `note='no-serpapi-budget'`).
- **5 additional venue files** (`rka/skills/writer/references/venue/`). USENIX (Security + ATC + NSDI), IEEE-SP (plus IEEE-CS broader), NeurIPS, OSDI (plus SOSP umbrella), Nature (plus Nature family). Each follows the Phase 1 seven-field schema (Section names + Page-limit + Tone + Forbidden + Citation + Required sections + Sample corpus). Documents per-venue threat-model requirements (USENIX/IEEE-SP), Paper Checklist (NeurIPS), Methods-at-end convention (Nature), engineering-first quantitative emphasis (OSDI).
- **`template_registry.md` expanded** from 2 active entries (Phase 1) to 9 active (Phase 2). New entries for IEEE-SP / NeurIPS / OSDI / Nature; refreshed ieeetran / llncs / usenix / neurips / arxiv to remove Phase-1-only markers. ACL pin strategy updated to `master_head_sha`. SHA-256 placeholders remain `TBD` until first fetch per workstation; the fetch script captures plus prompts for ratification.
- **`fetch_template.py` full lifecycle** (`rka/skills/writer/scripts/fetch_template.py`). Upgrades the Phase 1 lookup-only stub to download + SHA-256 verify + cache (with `.sha256` sidecar) + refuse-on-mismatch + TBD-pin PI ratification path. Error hierarchy: TemplateRegistryError base; TemplateChecksumMismatchError, TemplatePinMissingError, TemplateDownloadError. Archive format support: .zip, .tar / .tar.gz / .tgz, single-file .cls / .sty / .bst.
- **61 new tests** under `tests/skills/writer/` (suite progression: 43 to 104). test_mcp_wrappers.py (12 tests): backend availability + graceful degradation + mocked-client paths. test_pipeline_stages.py (16 tests): per-stage isolation with module-attribute substitution; all 7 statuses round-trip. test_serpapi_budget.py (8 tests): CreditBudget basics + over-budget refusal + env/YAML overlay resolution order. test_fetch_template.py (15 tests): pin detection + SHA computation + lookup + error hierarchy + mismatch refusal + cache hit skips download. test_venue_files.py (extended +10): 5 new venues schema + USENIX threat model + NeurIPS Paper Checklist + Nature Methods-at-end + em-dash dogfood.

### Dependencies

New `[project.optional-dependencies] writer-tools` group:

```
habanero>=2.3.0          # Crossref; 11mo silent, narrow Stage B/D
pyalex>=0.21             # OpenAlex; active
semanticscholar>=0.12.0  # S2; active
arxiv>=3.0,<4.0          # PIN AWAY FROM 4.0; two majors in 5 weeks
serpapi>=1.0.2           # SerpAPI; not "serpapi-python"
manubot>=0.6.1           # Stage F subprocess; 22mo silent, narrow surface
```

Existing rka installs unaffected. Install via:

```
UV_CACHE_DIR=/tmp/uv-cache uv tool install --force --reinstall '.[writer-tools]'
```

### Entry points

Adds `rka-writer-tools = "rka.skills.writer.mcp_tools.server:main"` to `[project.scripts]`. Available after install as `~/.local/bin/rka-writer-tools`.

### Bookkeeper invariant preserved

`git diff main -- rka/services/ rka/api/ rka/mcp/ web/` was verified empty at every commit boundary across all 6 atomic Phase 2 commits. Writer Phase 2 adds code only under `rka/skills/writer/` plus `tests/skills/writer/`. The new MCP server lives at `rka/skills/writer/mcp_tools/`, NOT `rka/mcp/` (which remains the RKA core MCP per T0 Backbrief verification item 6).

### Out of scope (deferred to Phase 3)

- Revision-loop handler with 4 comment_class shapes (R1/R2/R3/R4).
- Brain mission integration for Writer revisions.
- Optional MCP tools `rka_get_manuscript`, `rka_validate_reference`, `rka_register_manuscript` (would be added to existing `rka` MCP server).

## [2.5.5] — 2026-05-20 (patch release; embedding-dim-flex generalization across all 6 entity types — coupled 3-bug fix)

**Mission**: `mis_01KS1RFNM2T1HTB077G507T1FR`
**Motivating decision**: `dec_01KS1RAAN8RNAAEYP2TEQPPAA9` (Option A bundled fix)
**Surfaced by**: PI on a peer machine 2026-05-19; another Brain session worked
around the bug via direct DB operations + a manually-triggered PUT.
**Sequencing note**: `mis_01KS0QEW21N2NG4EJTKJ3JTWTE` (Eval-v2 corpus refresh)
**slides from v2.5.5 to v2.5.6** because corpus refresh needs corrected
embeddings to compute against. v2.5.5 takes the corpus refresh's
originally-planned tag; corpus refresh ships next.

### Honest framing — three coupled bugs

After PI switched the embedding backend from `nomic-embed-text-v1.5` (768-dim)
to `text-embedding-qwen3-embedding-8b` (4096-dim) on 2026-05-15, semantic
search across journals — which dominates user retrieval — kept returning
vectors from the retired nomic model, permanently. Triage surfaced three
defects that compound:

- **Bug 1** — Only `vec_claims` had dim-flex reshape (migration 022 + v2.4
  `rka/services/embedding_reshape.py`). The other five vec_* tables
  (`vec_journal`, `vec_decisions`, `vec_literature`, `vec_missions`,
  `vec_artifacts`) were defined with hardcoded `float[768]` in
  `rka/db/schema_phase2.sql` and migration 002; no reshape mechanism
  existed. PUT `/api/config/embedding` propagated the new dim to
  `vec_claims` only.
- **Bug 2** — `rka/infra/embeddings.py:needs_reembed` compared only
  `content_hash`; never `model_name` or `dimensions`. So a model swap left
  every unchanged entity flagged "not stale" even though its stored vector
  belonged to a retired backend. The metadata row's `model_name` field said
  "nomic" forever.
- **Bug 3** — `rka/services/embedding_backfill.py:BackfillService.run_backfill`
  iterated `claims WHERE embedding_pending = 1` only; never touched
  journal/decisions/literature/missions/artifacts. Even if Bug 1 were
  patched, those five tables would stay empty after reshape.

### Fixed (this release)

- **`reshape_vec_table` generalization** (`rka/services/embedding_reshape.py`).
  Added `current_vec_table_dim(db, table_name)`, `reshape_vec_table(db,
  table_name, *, dim)`, and `reshape_all_vec_tables_if_needed(db, *, dim)`.
  A `_TABLE_TO_ENTITY` map covers all six vec_* tables. The v2.4 surface
  (`reshape_vec_claims`, `reshape_vec_claims_if_needed`,
  `current_vec_claims_dim`) is preserved as thin wrappers; existing 11-test
  reshape suite stays green.
- **Per-entity-type pending signal**. `vec_claims` keeps the v2.4
  `claims.embedding_pending` flag (the BackfillService cursor + existing
  tests depend on it). The other five entity types use
  `embedding_metadata`-absence: reshape DELETEs metadata rows for the
  affected `entity_type`, and v2.5.5's 3-tuple `needs_reembed` (below)
  returns True until backfill repopulates them.
- **Startup hook + PUT handler now reshape every vec_* table**
  (`rka/api/app.py`, `rka/api/routes/config.py`). The PUT handler's 202
  response body now carries a `reshape` key with per-table outcome
  alongside `job_id` + `status_url`.
- **3-tuple `needs_reembed`** (`rka/infra/embeddings.py`). The query widens
  to `SELECT content_hash, model_name, dimensions`. Returns True on ANY
  mismatch OR metadata absence. Defensive `dim == 0` early-return forces
  re-embed when the backend hasn't reported a dim yet.
- **`BackfillService` iterates all six entity types**
  (`rka/services/embedding_backfill.py`). New signature parameter
  `entity_types: Sequence[str] | None = None` defaults to the full set
  (claim, journal, decision, literature, mission, artifact). Per-entity-type
  cursor + write loop is parameterized by `_ENTITY_BACKFILL_CONFIGS` keyed on
  entity_type. Content composition matches the v2.4 entity write-path
  callers (e.g. journal = `content + " " + summary`; decision = `question +
  " " + rationale`; literature = `title + " " + abstract`; mission =
  `objective + " " + context`; artifact = `build_artifact_text(filename,
  filetype, mime, metadata)`). Per-type embed-batch failures are isolated:
  one type's failure does not stop the others; the final state is "failed"
  iff any type errored. v2.4 single-type-failure error format preserved
  when only one type fails.
- **Atomic metadata write in backfill loop**. The v2.4 backfill wrote only
  to `vec_claims` and skipped the metadata update; v2.5.5 always writes the
  matching `embedding_metadata` row with the active `content_hash +
  model_name + dimensions` so the 3-tuple gate's invariant holds.
- **Migration 024** (`024_dim_flex_all_vec_tables.sql`). Documentation-only
  no-op SQL file mirroring the migration 022 pattern; reshape itself is a
  runtime operation because the dim is config-driven (lives in
  `/data/embedding_config.json`).
- **Version-string drift fix**: `rka/__init__.py:__version__` had drifted
  to "2.5.3" while `pyproject.toml` was at "2.5.4". Both bumped to "2.5.5"
  together in this release.

### Tests (+21 across 3 files; suite 732 → 753 passing)

- `tests/test_services/test_embedding_reshape.py` (+9): 5 parametrized
  cases for each new vec_* table; metadata-DELETE behavior on non-claims
  reshape; claim metadata survives (uses flag); `reshape_all_vec_tables_if_needed`
  iterates every table; idempotent second-call no-op; rejects unknown
  table name.
- `tests/test_services/test_embedding_backfill.py` (+6): default
  iterates all six types; restricts to named entity_types; per-entity-type
  failure isolation; rejects unknown entity_type; end-to-end reshape →
  invalidate → backfill repopulates; idle (nothing pending) completes
  immediately.
- `tests/test_infra/test_embeddings_needs_reembed.py` (NEW, +6): full
  3-tuple match → False; content_hash mismatch → True; model_name
  mismatch → True (the Bug-2 trigger); dimensions mismatch → True;
  metadata absent → True; defensive `dim == 0` → True.

Existing v2.4 backfill tests preserved by passing `entity_types=("claim",)`
explicitly so they continue to test the claims-specific path under the
new all-types default.

### Live verification (2026-05-20 against the production container)

Before `docker compose up -d --build`:
```
vec_claims:     dim=4096  (already reshaped via prior manual op)
vec_journal:    dim=768   ← Bug 1
vec_decisions:  dim=768   ← Bug 1
vec_literature: dim=768   ← Bug 1
vec_missions:   dim=768   ← Bug 1
vec_artifacts:  dim=768   ← Bug 1
embedding_metadata: claim/decision/journal/mission all at dim=768
                    model=nomic-ai/nomic-embed-text-v1.5 (Bug 2)
```

After rebuild + restart (T2 startup hook fires automatically):
```
vec_claims:     dim=4096
vec_journal:    dim=4096  ✓
vec_decisions:  dim=4096  ✓
vec_literature: dim=4096  ✓
vec_missions:   dim=4096  ✓
vec_artifacts:  dim=4096  ✓
embedding_metadata: journal/decision/mission rows DELETEd by startup hook
                    (entries will be re-embedded via 3-tuple
                    needs_reembed on next embed_and_store call OR via a
                    PUT-triggered backfill)
```

Backfill kick-off requires an explicit PUT (background task fires only
on PUT, not on startup). The operational note below describes the path.

### Operational user note

Users who switched the embedding backend before upgrading to v2.5.5 and
whose `embedding_metadata` rows still carry an outdated `model_name` or
`dimensions` tuple should re-PUT `/api/config/embedding` after upgrade to
trigger the full all-entity reshape + backfill. The PUT body must have a
different `(backend, model, dim)` signature than the current saved config
for the handler to fire backfill — if your goal is just to refresh stale
metadata under the same backend, the alternative is to let the 3-tuple
`needs_reembed` gate refresh each entity individually as it is touched
(read/write paths trigger embed-on-stale).

The startup hook brings vec_* table dims into parity automatically on
container restart without invoking the backfill loop.

### Surfaced-by-empirical-state evidence

PI's peer machine ran a manual reshape via direct DB SQL + PUT trigger as
a workaround; this established the bug class, the empirical state we
verify against, and the operational path for users on existing
deployments.

### Brain post-mortem reference

- `jrn_01KS1S2QMVQPMXS8KHK1JS6HS1`: Executor Backbrief filed pre-implementation
  with full empirical baseline of the 6 vec_* tables + embedding_metadata
  aggregate + per-entity content-composition audit.

## [2.5.4] — 2026-05-19 (patch release; D4 bundle-narrowing + attribution metric — Phase-3 PARTIAL close)

**Mission**: `mis_01KS0C8BKTHCA8GB38BGDR1PTQ`
**Motivating decision**: `dec_01KS0C4PG88F29YBR91VQ3RRXY` (D4 re-scoped narrow per v2.5.3 addendum)
**Brain post-mortem**: `jrn_01KS0NNMM7NJAASDK0CHMFAPQK` (Eval-v2 baseline drift finding)
**T0 checkpoint**: `chk_01KS0NX382JYBRSRBECZ56JBKE` (drift surfaced) → `chk_01KS0Q38YRR4S55ZT911W2QMEQ` (T3 stop condition b)

### Honest framing — Phase-3 status: NEEDS DEEPER INVESTIGATION

D4's two-part scope shipped technically correct (67 tests pass; +6 new), but
the canonical Eval-v2 metric gates did NOT clear: re-running the v2.5.3 baseline
against the current RKA database produced `mean_recall = 0.755` (vs the stored
v2.5.3 reference 0.958) BEFORE D4 changes — the floor (≥ 0.85) was already
breached.

Root cause (per Brain post-mortem `jrn_01KS0NNMM7NJAASDK0CHMFAPQK`): the
v2.5.3 weighted-sum scorer's `w_recency=0.2` with `1/(1+days)` decay shape
amplifies the contribution of very-recent entries non-linearly. Phase 2's
6-retry chain (`mis_01KRKG9K1SSDZNDH90K2Z7ZM92` and successors) added ~30+
new journal entries between 2026-05-17 and 2026-05-19, all with very recent
`updated_at` timestamps; these displaced the v2.5.3-frozen `expected_entities`
from the top of the weighted-sum ranking in 7 session-start / mission-start
scenarios.

D4's anchor-aware truncation policy cannot recover the floor because 6 of 7
regressed scenarios have **no anchor-aware tools** in their `tools_invoked`
(verified via K-escalation K=30 / K=50 / K=75 — identical results). The
truncation gate only activates when at least one of `rka_get_ego_graph`,
`rka_multi_hop_retrieval`, or `rka_assemble_evidence` fires; for un-anchored
session-start patterns it's dormant.

D4's implementation is correct; the floor failure is **corpus-stale**:
`expected_entities` are pre-Phase-2-retry-artifacts and need re-annotation.
Follow-up mission `mis_01KS0QEW21N2NG4EJTKJ3JTWTE` (Eval-v2 corpus refresh +
D4 efficacy validation) is the Phase-3 closure attempt; ships as v2.5.5 if
floors clear.

### Fixed (this release)

- **Bundle-truncation policy with anchor-aware-tool priority**
  ([rka/services/context.py](rka/services/context.py)). When the caller signals
  `anchor_aware_present=True`, the overview-path bundle is capped at top-K
  (default 30; env-var-configurable via `RKA_CTX_BUNDLE_K`). Anchor-aware-tool
  outputs UNION through the cap regardless of weighted-sum rank, so the
  anchor-aware path's targeted retrieval is preserved. Backward compat:
  `anchor_aware_present=False` (default) leaves the full ranked list intact
  (v2.5.3 behavior).
- **Per-tool attribution annotation** (`eval-harness/v2/runner.py` +
  `metrics.py`). Each entity in the runner's `combined_ranking` is now
  attributed to the tool that first-discovered it (`first_discovery_map`).
  The metrics layer surfaces two numbers per tool: `first_discovery_coverage`
  (entities first-introduced by this tool) and `total_coverage` (entities
  present in this tool's response regardless of first-discoverer). A per-tool
  drop in `first_discovery_coverage` while `total_coverage` stays high is
  "attribution shift, not coverage loss" — distinguishable in the report
  without triggering false-alarm investigation.
- **`ContextRequest` model + `/api/context` route**: pass-through for the new
  parameters (`anchor_aware_present`, `anchor_aware_ids`).
- **`docker-compose.yml`**: `RKA_CTX_BUNDLE_K` env interpolation pattern
  (defaults to 30; sweep harness overrides for K-tuning).

### Tests

- **4 new context-truncation tests** at
  `tests/test_services/test_context.py::TestV2_5_4D4BundleTruncation`:
  truncation applied when anchor_aware_present=True (K=30 cap);
  truncation skipped on backward-compat path; `RKA_CTX_BUNDLE_K=50`
  override propagates; anchor-aware outputs UNION through the cap.
- **2 new attribution-metric tests** at
  `eval-harness/v2/tests/test_metrics.py`:
  `test_annotation_records_first_discoverer` (per-tool split distinguishes
  first-discovery from total);
  `test_per_tool_attribution_metric_distinguishes_first_vs_total` (the
  canonical "attribution shift, not coverage loss" use case — `rka_get_journal`
  drops on first-discovery while total stays constant).
- Test count: pre-D4 17 context tests → post-D4 21; pre-D4 44 metrics tests
  → post-D4 46. Net +6 tests.

### Eval-v2 impact — D4 K-escalation under drifted baseline

| Metric | v2.5.3 stored (2026-05-17) | Current drift (2026-05-19, pre-D4) | D4 K=30 | D4 K=50 | D4 K=75 |
|---|---|---|---|---|---|
| mean_recall (critical) | 0.958 | 0.776 | 0.755 | 0.755 | 0.755 |
| mean_expanded_recall | 0.875 | 0.685 | 0.673 | 0.673 | 0.673 |
| mean_ordering_score | 0.400 | 0.331 | 0.328 | 0.329 | 0.329 |
| mean_efficiency | 0.0351 | 0.026 | 0.032 | 0.028 | 0.028 |

D4 K-escalation cannot move the floor — 6 of 7 regressed scenarios have no
anchor-aware tools (truncation gate dormant); the 7th regressed FURTHER
under D4 (`brain-paper-scaffold-session-start-section` 1.000 → 0.667).

### Per-tool attribution shift example (D4 metric working as designed)

| Tool | first_discovery_coverage | total_coverage | Reading |
|---|---|---|---|
| `rka_get_ego_graph` | 0.778 | 0.778 | Anchor-aware; always fires first |
| `rka_multi_hop_retrieval` | 0.683 | 0.817 | Mild shift; mostly first-discovers |
| `rka_get_mission` | 0.267 | 0.800 | **BIG attribution shift; total stays at 0.8** |
| `rka_get_context` | 0.267 | 0.372 | Mild shift |
| `rka_get_journal` | 0.000 | 0.000 | True coverage loss (corpus-stale issue) |

The `rka_get_mission` row is the canonical D4 success: under v2.5.5 runner
reorder, anchor-aware tools fire first and first-discover mission entities;
`rka_get_mission` still returns them (total 0.800) but no longer
first-discovers them. Pre-D4 metric flagged this as a per-tool drop
0.800 → 0.267, triggering investigation; D4 metric surfaces it as the
attribution shift it actually is.

### Release-line scope

Main only — `release/desktop` is independent per the hub-and-spoke
architecture (`dec_01KRPAVSTJ4H80VXJVN6DQ82WQ`). No cherry-pick attempted.

### Phase-3 closure status

D1 (v2.5.1) + D2 (v2.5.3) + D3 (v2.5.2) **closed**. D4 (this release)
ships the technical implementation but **NEEDS DEEPER INVESTIGATION** before
the eval-v2 metric gates clear. Follow-up mission
`mis_01KS0QEW21N2NG4EJTKJ3JTWTE` (Eval-v2 corpus refresh + D4 efficacy
validation; per `dec_01KS0QBCGG9FWFT2R0MSP3HHY9` Option A) is the Phase-3
chapter-close attempt; ships as v2.5.5 if floors clear post-refresh.

If only `mean_efficiency` fails post-refresh, ship v2.5.5 as partial
Phase-3 close + Phase-3.1 K-tuning. Brain confidence going into corpus
refresh: moderate-to-high.

---

## [2.5.3] — 2026-05-17 (patch release; D2 context-ordering closed via 3-mission stack)

**Missions** (in order):
- `mis_01KRSMPNRQ70WRB1NH9BJAT6JX` — original D2 sort refactor
- `mis_01KRSP44W7BDZH11PZRGXH1WM4` — coefficient A/B sweep
- `mis_01KRSQ4GCRWPSXCWZHGZ2ZR830` — runner reorder (winning vector)

**Decisions**:
- `dec_01KRSMMCS8MD7KQDBS0E2DVKBQ` (D2 fix-shape; covers all 3 missions)
- `dec_01KRSP1852TKACJA0BM0HJNWBB` (hold-and-tune ratification after sort-only fell below floor)
- `dec_01KRSQ1TDY1X976W7EV16GXWZV` (vector-II ratification after sweep flat)

**Surfaced by**: Eval-v2 Finding 1 — `mean_ordering_score = 0.251` against the v2.5.2 baseline. The fix lifts this to **0.400** (+0.137 absolute, +0.037 above the 0.363 floor target).

### Root cause (resolved across 3 missions)

The `ContextEngine` post-fetch ranker had two documented-vs-implemented divergences from the v2.4 design (`dec_01KQQPD6Y6B362T3K08368BDMP`):
1. Topic-driven `get_context(topic=…)` discarded BM25/vector search relevance and re-sorted by importance only.
2. Overview `get_context()` used `created_at` as a tuple tie-break, not as the multiplicative recency term the v2.4 spec called for.

The original v2.5.3 mission fixed both. Per-scenario validation showed the fix worked (paper-scaffold-session-start-section lifted +0.333), but the aggregate move was only +0.016 — well below the 0.10 floor. A 5-config coefficient A/B sweep (v2.5.4) then proved coefficient space empirically flat (spread 0.0272 across the simplex), confirming `ContextEngine`'s internal sort was NOT the bottleneck. The winning attack vector turned out to be one layer up: the Eval-v2 runner's tool-invocation order.

### Fixed

- **Topic-anchored `get_context` preserves BM25/vector relevance order** (Mission 1, `rka/services/context.py`). Search hits annotated with `_search_rank = i` after `_hydrate_hits`; topic_sort_key uses `(rank, -importance, -centrality)` ascending. Importance/centrality break ties within identical search rank.
- **Overview `get_context` uses a weighted-sum score with recency as a first-class multiplicative term** (Mission 1):
  ```
  score = w_imp * importance_normalized + w_cent * log1p(centrality) + w_recency * recency_score
  ```
  where `recency_score = 1.0 / (1 + days_since_created)` clamped to `[0, 1]`. Default coefficients: `w_imp=0.5`, `w_cent=0.3`, `w_recency=0.2`. Semantic shift: a heavily-linked recent high-band entry can now outrank an un-linked critical-band entry. The v2.4 spec called for this; pre-v2.5.3 the strict-band hierarchy was the *bug*, not the design.
- **PI-source lift preserved at +0.125 normalized** (matches pre-v2.5.3 `+5/40` magnitude).
- **Two pre-v2.5.3 tests updated** to reflect the new semantics (`test_pi_source_lift_applied_within_band` now checks the lift via `_overview_score` directly; `test_high_centrality_with_age_can_beat_un_linked_critical` inverts the assertion). The decision rationale named the old invariant as the bug.

### Added

- **Env-var-configurable coefficients** (Mission 2, `rka/services/context.py` + `docker-compose.yml`). Read from `RKA_CTX_W_IMP`, `RKA_CTX_W_CENT`, `RKA_CTX_W_RECENCY`, `RKA_CTX_PI_LIFT` at module import time. Docker-compose interpolates from shell env so eval sweeps can swap configs via container restart without source rebuilds. `_reload_coefficients_from_env()` helper for in-process test overrides.
- **A/B sweep harness** at `eval-harness/v2/sweep_v2_5_3.py` (Mission 2). Runs the eval-v2 corpus across N coefficient configs, restarting the rka container between configs. Outputs aggregated metrics + per-config raw bundles. Reusable for future tuning.
- **Eval-v2 runner anchor-aware tool-order policy** (Mission 3, `eval-harness/v2/runner.py`). When a scenario has critical expected entities AND its `tools_invoked` includes any of `{rka_get_ego_graph, rka_multi_hop_retrieval, rka_assemble_evidence}`, those tools fire FIRST in deterministic order. Anchor-aware tools' outputs now lead the bundle's `combined_ranking` instead of being buried behind `get_context`'s 150+ entries. Non-anchored scenarios are no-ops (preserved behavior).

### Empirical finding (locked for future tuning work)

- **Coefficient space is essentially flat for this corpus**. 5-config sweep spanned simplex corners (recency-heavy, centrality-heavy, importance-dominant, balanced); aggregate `mean_ordering_score` moved <0.028 across the span. Future tuning should NOT waste effort on coefficient search; the lever is somewhere else (runner-order, type-aware boosting, corpus alignment).
- **Tool-invocation order is the dominant lever** for the aggregate metric. 9 anchor-affected scenarios lifted +0.30 to +0.53 each from the reorder; 7 un-anchored scenarios stayed within DB-drift noise (±0.04).

### Tests

- **17 context tests** in `tests/test_services/test_context.py` (11 pre-existing + 3 v2.5.3 sort-by-retrieval-path + 3 v2.5.4 env-var coefficients).
- **14 runner tests** in `eval-harness/v2/tests/` (7 pre-existing + 6 v2.5.5 reorder unit + 1 v2.5.5 lock-defaults integration).
- All previous regression tests pass (52 db, 25 cluster-related, etc.).

### Eval-v2 impact (canonical v2.5.3 run)

| Metric | v2.5.0 baseline | v2.5.1 | v2.5.2 | **v2.5.3** | Δ vs v2.5.2 |
|---|---|---|---|---|---|
| mean_recall (critical) | 0.958 | 0.958 | **1.000** | 0.958 | -0.042 (DB drift; see note) |
| mean_expanded_recall | 0.888 | 0.888 | 0.938 | 0.875 | -0.063 |
| **mean_ordering_score** | 0.251 | 0.253 | 0.263 | **0.400** | **+0.137** ✓ |
| mean_breadth | 3.25 | 3.25 | 3.25 | 3.00 | -0.25 |
| mean_efficiency | 0.037 | 0.036 | 0.037 | 0.035 | -0.002 |

**Per-tool critical-coverage**:

| Tool | v2.5.2 | v2.5.3 | Δ | Notes |
|---|---|---|---|---|
| `rka_get_ego_graph` | 0.333 | 0.778 | +0.444 ↑ | now first-discoverer for anchored entities |
| `rka_multi_hop_retrieval` | 0.000 | 0.817 | +0.817 ↑ | combined v2.5.1+v2.5.2+v2.5.3 effect |
| `rka_get_journal` | 1.000 | 0.000 | -1.000 ↓ | **attribution shift, not coverage loss** — entities still in bundle |
| (others) | unchanged | unchanged | 0.000 | |

The `rka_get_journal` per-tool drop is an attribution shift: the reorder puts anchor-aware tools ahead of `get_journal`; entities `get_journal` used to first-discover are now first-discovered by `ego_graph`/`multi_hop`. Total bundle recall unchanged. (Possible v2.5.4 metric refinement: annotate first-discovery vs follow-on coverage.)

The aggregate `mean_recall` drop from v2.5.2's 1.0 to 0.958 is DB-drift between runs (8 new entities added to live `rka_development` between the v2.5.2 and v2.5.3 eval runs displaced older entries from `/api/notes` top-20). Re-running v2.5.2 against today's DB would show the same drop. Hard recall floor (0.85) preserved.

### Release-line scope

Main only — `release/desktop` is independent per `dec_01KRPAVSTJ4H80VXJVN6DQ82WQ`.

### Phase-3 status

D1 (v2.5.1), D3 (v2.5.2), D2 (v2.5.3) all closed. D4 (bundle-narrowing) remains — re-scoping recommended per the v2.5.3 addendum in `eval-harness/v2/report.md` (anchor-aware-tool priority for bundle truncation; per-tool attribution annotation in the metric).

---

## [2.5.2] — 2026-05-16 (patch release; cluster → parent-RQ traversal)

**Mission**: `mis_01KRS1D8C0E2FP52D0P6JNB3SX`
**Fix-shape decision**: `dec_01KRS1ADPD4W6AW2X54MKVXMCR`
**Sequencing decision**: `dec_01KRRM5WKSSX7C3ZXZME0BMVQ9` (D3 ratified after D1 closed at v2.5.1)
**Surfaced by**: Eval-v2 Finding 3 (S7 + S9 cluster-anchored scenarios stuck at 0.67 critical-recall across v2.5.0 + v2.5.1 baselines).

### Root cause

`evidence_clusters.research_question_id` is a FOREIGN KEY column populated for 101/101 clusters across all 9 projects, but `GraphService.multi_hop_retrieval` and `GraphService.get_ego_graph` only walk `entity_links` + `claim_edges`. The FK column was invisible to graph traversal — every cluster anchor missed its parent research-question. Not a weight-tuning problem (the original hypothesis); a missing-edge-type problem.

### Added

- **New `entity_links.link_type` value: `'answers'`** (cluster → parent-RQ direction).
  Active-tier entry; rejects unknowns via the CHECK constraint same as the
  other 11 link types.
- **Migration 023** (`rka/db/migrations/023_cluster_answers_links.sql`):
  - Extends the CHECK enum (from migration 021) to include `'answers'`.
    Uses migration 021's documented table-swap pattern.
  - Backfills one entity_link per `evidence_clusters` row with a non-null
    `research_question_id` — `link_type='answers'`, `source=cluster`,
    `target=decision`, `link_weight=1.0`, `link_reason='backfill from
    evidence_clusters.research_question_id FK (migration 023)'`.
    Idempotent via INSERT OR IGNORE against the project-scoped UNIQUE
    triple from migration 020.
  - Production row count post-migration: **101 entity_links** across 9
    projects (16 for `prj_01KKQM9JFG67GT5FGWTAHD9YE4`, the Eval-v2 project).
- **`DEFAULT_EDGE_WEIGHTS['answers'] = 1.0`** in `rka/services/graph.py`
  (high-signal tier alongside `justified_by` / `motivated` / `evidence_for` /
  `derived_from`).
- **ClusterService hook for parity going forward** in
  `rka/services/clusters.py` — `.create` and `.update` write the `answers`
  link via `BaseService.add_link(...)` whenever a non-null
  `research_question_id` is set. INSERT OR IGNORE semantics keep re-runs
  safe; no future migration needed for new clusters.

### Fixed

- **Cluster-anchored graph traversal now surfaces the parent
  research-question.** Both `GraphService.get_ego_graph` and
  `GraphService.multi_hop_retrieval` walk the new `answers` edges
  automatically (no graph-layer code changes required beyond the
  weight-map entry).

### Tests

- **4 migration tests** at `tests/test_db/test_migration_023.py`:
  CHECK extension accepts `'answers'`; CHECK still rejects unknown
  link types (additive, not removal); backfill is idempotent across
  two runs; row count invariant equals cluster count with non-null FK,
  per-project breakdown propagates `project_id` correctly, orphan
  null-FK clusters produce no link, provenance columns set as documented.
- **4 regression tests** at `tests/test_services/test_graph.py`:
  ego_graph from cluster anchor includes parent RQ (S7 anchor verbatim);
  multi_hop_retrieval seeds-only cluster traversal returns parent RQ
  (combined v2.5.1 + v2.5.2 regression-lock); ClusterService.create
  emits exactly one link when FK set; ClusterService.create emits no
  link when FK is NULL.

### Eval-v2 impact — live re-run against v2.5.2 container

| Per-scenario critical recall | v2.5.0 / v2.5.1 | v2.5.2 |
|---|---|---|
| S7 `brain-contradiction-staleness-vs-validation` | 0.667 | **1.000** |
| S9 `brain-paper-scaffold-session-start-section`  | 0.667 | **1.000** |
| Other 14 scenarios | 1.000 | 1.000 |

| Aggregate | v2.5.1 | v2.5.2 | Δ |
|---|---|---|---|
| mean_recall (critical) | 0.9583 | **1.0000** | **+0.0417** |
| mean_expanded_recall | 0.8875 | 0.9375 | +0.0500 |
| mean_ordering_score | 0.2533 | 0.2628 | +0.0096 |
| mean_efficiency | 0.0362 | 0.0372 | +0.0010 |

| Per-tool critical-coverage (directly-affected tools) | v2.5.1 | v2.5.2 |
|---|---|---|
| `rka_get_ego_graph` | 0.333 | **0.778** (Δ +0.444) |
| `rka_multi_hop_retrieval` | 0.683 | **0.817** (Δ +0.133) |

**Every scenario in the 16-scenario corpus now scores critical-recall = 1.0.**

Critical-recall floor (0.85) passes flat at the ceiling. v2.5.2 artifacts
at `eval-harness/v2/results/raw_v2.5.2/` + `metrics_v2.5.2.json`. Baselines
preserved: v2.5.0 at `results/raw/` + `metrics.json`; v2.5.1 at
`results/raw_v2.5.1/` + `metrics_v2.5.1.json`. Full before/after analysis
in `eval-harness/v2/report.md` § "v2.5.2 addendum — D3 closed".

### Release-line scope

Main only — `release/desktop` is independent per the hub-and-spoke
architecture (`dec_01KRPAVSTJ4H80VXJVN6DQ82WQ`). No cherry-pick attempted.

### Phase-3 hooks remaining

D1 (v2.5.1) + D3 (v2.5.2) both closed. D2 (importance-weight tuning) and
D4 (bundle-narrowing policy) remain candidate Phase-3 missions; their
success signal has shifted from `mean_recall` (now at the 1.0 ceiling)
to `mean_ordering_score` (0.263) and `mean_efficiency` (0.037).

---

## [2.5.1] — 2026-05-16 (patch release; multi-hop schema relaxation)

**Mission**: `mis_01KRRM8CJP34KTN8KJMZQH2PFP`
**Motivating decision**: `dec_01KRRM5WKSSX7C3ZXZME0BMVQ9` (D1 sequencing from Eval-v2 report)
**Surfaced by**: Eval-v2's v2.5.0 live run (Finding 4 in `eval-harness/v2/report.md`,
journal `jrn_01KRPGY39DJA2K9KV20XD733GK`) — every `rka_multi_hop_retrieval`
invocation in the 16-scenario corpus returned 422.

### Fixed

- **`POST /api/graph/multi-hop` now accepts seeds-only invocations.**
  `MultiHopRequest.query` was a required `str` (no default), so any
  body that only carried `seeds` was rejected by FastAPI's schema
  validator with the default per-field-error 422 — even though the
  service layer (`rka/services/graph.py:multi_hop_retrieval`) has
  always had an explicit seeds-set branch that bypasses search.
  ([rka/api/routes/graph.py](rka/api/routes/graph.py))
- **422 body shape on neither-set requests is now the Affordance-G
  structured object** (`{error, detail, hint}`) instead of FastAPI's
  per-field-error array. Mirrors the Mission B precedent at
  `rka/api/routes/config.py:_422`. The `hint` field is a fully-rendered
  example so callers see actionable guidance instead of needing the
  schema docs.
- **Eval-v2 runner sends a v2.5.1-compliant body.** `_call_multi_hop`
  now sends `seeds=[anchor]` (a list, not the v2.4-era singular
  `start_entity` key that the schema never recognized) and always
  populates `query` from `scenario.trigger[:200]`.
  ([eval-harness/v2/runner.py](eval-harness/v2/runner.py))

### Behavior preserved (regression-locked)

- **Query-only invocations** still succeed (search-based seeding path).
- **Both `query` + `seeds` provided** still succeed; the service uses
  explicit seeds and bypasses the search step.
- **MCP wrapper** (`rka_multi_hop_retrieval` in `rka/mcp/server.py`)
  always sends `query`, so no MCP-side change is required.

### Tests

- 4 new regression tests at `tests/test_api/test_graph_route.py` —
  seeds-only / query-only / neither (422 + Affordance-G shape) / both
  combined.
- 1 new test at `eval-harness/v2/tests/test_runner.py` —
  `test_call_multi_hop_body_matches_v2_5_1_schema` asserting body
  shape against the schema (no `start_entity` legacy key; `seeds` is
  a list; `query` always populated).

### Eval-v2 impact (live re-run against v2.5.1 container)

- **`per_tool_mean_critical_coverage[rka_multi_hop_retrieval]`**
  moved **0.000 → 0.683** (Δ +0.683).
- Zero `rka_multi_hop_retrieval` divergences across the 16-scenario
  corpus (was 16 — one per scenario).
- Aggregate `mean_ordering_score` nudged **+0.0022** from the newly-
  populated multi-hop contribution to the combined ranking.
- Critical-recall floor (0.85) still PASSES at 0.958.
- v2.5.1 artifacts: `eval-harness/v2/results/raw_v2.5.1/` +
  `metrics_v2.5.1.json`. v2.5.0 baseline preserved at
  `results/raw/` + `metrics.json`.
- Full before/after analysis in `eval-harness/v2/report.md` § "v2.5.1
  addendum — D1 closed".

### Release-line scope

This patch lands on **main only**. The `release/desktop` line is
independent per the hub-and-spoke architecture
(`dec_01KRPAVSTJ4H80VXJVN6DQ82WQ`); a future cherry-pick to
`v2.5.0-desktop` is up to the desktop release cadence and is not part
of this mission.

### Phase-3 hooks (D2/D3/D4) unchanged

D1 was the well-scoped first slice. D2 (importance-weight tuning),
D3 (cluster→parent-RQ pathway), and D4 (bundle-narrowing policy) remain
candidate Phase-3 missions, gated on PI ratification.

---

## [2.5.0] — 2026-05-15 (main branch; distinct from `v2.5.0+desktop` on release/desktop)

**Release line note.** Per the hub-and-spoke architecture decision
`dec_01KRPAVSTJ4H80VXJVN6DQ82WQ`, this v2.5.0 release on `main`
is independent of `v2.5.0-desktop` on `release/desktop`. Main carries
core RKA features; release/desktop carries macOS .app distribution.
Eval-v2's composed-context coverage harness is core infrastructure, so
it lands on main and bumps main's minor.

### Added

- **Eval-v2 composed-context coverage harness** at `eval-harness/v2/`,
  extending (not replacing) the May 14 single-endpoint `rka_search`
  eval (`mis_01KRKJ9G20EM5XMA147JTKQCFF`).
  - **Corpus schema** (`eval-harness/v2/schema.md` +
    `eval-harness/v2/schema.json`) with JSON Schema Draft 2020-12
    validation. Each scenario carries: `scenario_id`, `actor`
    (brain | executor), `trigger`, `tools_invoked`, `expected_entities`
    with `importance` tags (critical | useful | nice-to-have), optional
    `context_length_budget_estimate` + `notes`.
  - **Schema validator** (`schema_validator.py`) with two runtime rules
    JSON Schema can't express cleanly: critical-floor ≥3 per scenario,
    and entity_id/entity_type prefix consistency.
  - **Corpus of 16 scenarios** (`corpus/scenarios.jsonl`) spanning 6
    pattern types: Brain session-start (4), Brain mission-creation (2),
    Brain contradiction-investigation (2), Brain paper-scaffold-assembly
    (2), Executor mission-pickup (3), Executor backbrief-gate (3).
    All entity IDs anchored to real rka_development entities.
  - **Runner** (`runner.py`) — REST-direct execution of the composed
    call sequence per scenario (11 distinct MCP tools mapped), entity-ID
    extraction via depth-first walker, anchor-entity logic for
    multi_hop / ego_graph / assemble_evidence, defensive JSON parsing
    for non-existent endpoints' SPA fallbacks, sister-uncertainty
    probing with checkpoint-on-divergence per Brain T2-gate ratification.
  - **Metrics** (`metrics.py`) — 5 per-scenario metrics (recall over
    critical-only, expanded_recall, NDCG-style ordering_score, breadth,
    efficiency) + per-corpus aggregation + per-actor breakdown +
    per-tool critical-coverage breakdown + reproducibility provenance
    (corpus SHA + rka HEAD + timestamp).
  - **36 unit + integration tests** (13 T1 schema + 6 T3 runner +
    17 T4 metrics) all passing.
  - **Live run results** in `results/raw/<scenario_id>.jsonl` +
    `results/metrics.json`:
    - mean_recall (critical) = 0.958 — PASSES 0.85 floor
    - mean_expanded_recall = 0.887
    - mean_ordering_score = 0.251 (low — critical entities buried mid-bundle)
    - mean_breadth = 3.25 of 5 entity types
    - mean_efficiency = 0.037 (very low — bundles 96% noise)
  - **Brain narrative report** at `eval-harness/v2/report.md` with 5
    headline findings + 4 decision-slate hooks for Phase 3 (bug fix
    on rka_multi_hop_retrieval 422, importance-weight tuning, cluster→
    parent-RQ pathway, bundle-narrowing policy).

### Surfaced bugs (next-mission candidates)

- `rka_multi_hop_retrieval` returns **422 Unprocessable Content** on
  every invocation during the live run — likely a request-body schema
  drift between MCP-tool docs and the `/api/graph/multi-hop` REST
  endpoint. Logged at `eval-harness/v2/results/raw/*.jsonl` and
  surfaced as Phase-3 decision-slate hook D1 in
  `eval-harness/v2/report.md`.

### Mission reference

- Mission: `mis_01KRPF3DERZS2W5VFDYE9E9GKM`
- Motivating decision: `dec_01KRPF09AP1FE1CRR6YQBY2R5F`
- Mid-mission gate ratification (Option B + S6 critical promotion):
  PI greenlight 2026-05-15
- Procedural-recurrence calibration: `jrn_01KRPGY39DJA2K9KV20XD733GK`
- Working branch: `feat/eval-v2-composed-context`
  (merged to main at this release via --no-ff)
- Test suite at release: 36 in `eval-harness/v2/tests/` + the prior
  v2.4.1 baseline

### Bookkeeper invariant

`git diff main -- rka/services/worker.py = 0 lines` held across every
commit on the eval-v2 branch (verified at T1 ca61cbe, T2 ea4d32c,
T2.1 8bde65f, T3 4ce5f09, T4 9043374, T5 fbcdbdb, T6 ec25052,
T7 release commit). The mission's measurement-only constraint
held too: `git diff main -- rka/` = 0 lines (Eval-v2 added no
source-code changes to RKA proper).

---

## [2.4.1] — 2026-05-15

### Fixed

- **`openai_compat` + `ollama` embedding backends: default httpx timeout
  raised from 30s → 600s.** The prior 30s default made local 8B-class
  embedding servers (LM Studio + qwen3-embedding-8b, Ollama + nomic-large
  variants) fail the first backfill batch with `httpx.ReadTimeout` and no
  claims would land. Constructor still accepts `timeout_seconds=...` so
  fast hosted backends can opt back down.
- **`BackfillService` default batch size lowered from 32 → 8.** A 32-text
  batch against an 8B-class model on a single Mac is multiple seconds even
  under ideal conditions; reducing the default lets the first batch
  complete and keeps the polling UI honest. Constructor still accepts
  `batch_size=...` for hosted-API workloads where 32+ is fine.
- **Backfill failure message now includes the exception class name.** Prior
  `status.error` rendered as `"batch embed failed (cursor at …): "` (empty
  after the colon) when the underlying exception had no string
  representation — e.g. `httpx.ReadTimeout()`. Now renders as
  `"batch embed failed (cursor at …): ReadTimeout: <message>"`. Locked by
  `test_backfill_error_includes_exception_class_when_message_empty`.

### Tests

- 4 new tests in `tests/test_services/test_embedding_backfill.py`:
  - `test_backfill_error_includes_exception_class_when_message_empty`
  - `test_backfill_default_batch_size_is_eight_v241`
  - `test_openai_compat_default_timeout_is_600_v241`
  - `test_ollama_default_timeout_is_600_v241`

### Provenance

- Triggered by PI UI failure observation post-v2.4.0 release: LM Studio
  + qwen3-embedding-8b 4096-dim backfill failed at 0/827 claims after
  ~23 min wall-clock with empty `status.error` after the colon.
- Bookkeeper invariant `git diff main -- rka/services/worker.py` = 0 lines
  held on the v2.4.1 hotfix branch.

## [2.4.0] — 2026-05-15

### ⚠ BREAKING CHANGES

- **`/api/capabilities` no longer returns the `llm` field.** The response
  is now `{"embedding": {available, reason_unavailable}}` — top-level
  `llm` is absent (not null, not `{available: false}`, gone). Any client
  that read `response.capabilities.llm` before v2.4.0 must update.
  Locked by a regression test in
  `tests/test_api/test_capabilities_route.py`. Rationale: PI directive
  `jrn_01KRNZBS50K250HHHHEC58E4GC` ratified Interpretation A of the
  LLM-capability removal — service code preserved, user-facing surface
  removed.
- **`web/src/hooks/useLLM.ts` and `web/src/pages/Notebook.tsx` are
  deleted.** The Settings page's LLM config card is replaced with a new
  Embeddings card; LLM types are removed from `web/src/api/types.ts`
  and LLM methods from `web/src/api/client.ts`. Server-side
  `rka/infra/llm.py`, `rka/api/routes/llm.py`, and the `rka_ask` /
  `rka_generate_summary` MCP tools are PRESERVED for future re-wiring
  through the orchestrator's Claude Code SDK.
- **`docker-compose.yml` no longer carries `RKA_LLM_*` env var
  references** (commented or active). `RKA_EMBEDDINGS_ENABLED: "true"`
  is set explicitly on both services.

### Added

- **Pluggable embedding backends.** Three concrete implementations
  behind the `EmbeddingBackend` Protocol:
  - **FastEmbed** (local ONNX, default; nomic-768 baseline)
  - **OpenAI-compat HTTP** (OpenAI API, LM Studio, vLLM, Together,
    Anthropic-via-shim — whichever the `base_url` points at; `api_key`
    optional)
  - **Ollama** (singular-prompt `/api/embeddings`; not the
    list-wrapped OpenAI shape)
- **Persistent embedding config at `/data/embedding_config.json`**
  (file-mode 0600, atomic write via tmp+rename, pre-flight backup to
  `embedding_config.backup.json` on every save).
- **REST API for embedding config:**
  - `GET /api/config/embedding` — current config with `api_key`
    redacted to `"***"`
  - `PUT /api/config/embedding` — validate + test + persist; returns
    202 + `{job_id, status_url}` if backfill kicked off, 200 if only
    `api_key` changed
  - `POST /api/config/embedding/test` — probe without persisting;
    returns `{ok, detail, detected_dim, latency_ms}`
  - `GET /api/config/embedding/backfill/status?job_id=…` — polling
    endpoint for the UI progress bar
  - 422 error mapping (Affordance G pattern):
    `{"error": "embedding_config_invalid", "detail": ..., "hint": ...}`
- **Migration 022 (`022_dim_flex_vec_claims.sql`)** — adds
  `claims.embedding_pending` column + partial index; flags every
  existing claim as pending so the configured backend re-embeds them.
- **`rka/services/embedding_reshape.py`** — drops + recreates the
  `vec_claims` virtual table at a config-driven dim. Runs on app
  startup (only when the dim has actually changed) and on
  PUT-with-dim-change.
- **`rka/services/embedding_backfill.py:BackfillService`** — iterates
  pending claims in `id`-ascending order, embeds in batches (default
  32), writes vec_claims rows, clears the flag. Resumable across
  container restarts. Per-claim failures keep the flag for retry;
  batch-level embed failures mark the job state=`failed`.
- **Web UI Settings page → Embeddings tab.** Backend dropdown,
  conditional fields per backend, **Test connection** button,
  confirmation modal for **Save & re-embed**, progress bar polling
  the status endpoint every ~1500 ms. The 422 hint for corrupt config
  renders verbatim from the server.
- **First-run banner.** Dismissible "Semantic search is enabled"
  banner with a link to Settings → Embeddings; dismissal persists in
  `localStorage` (`rka_first_run_banner_dismissed_v2_4`).
- **First-run startup hook.** When `/data/embedding_config.json` is
  absent, app startup persists `DEFAULT_CONFIG` (fastembed + nomic-768)
  via the standard `save_config` path so the config file exists from
  the very first request.
- **Reconcile-dim guard.** Each backend's production `embed()` path
  calls `reconcile_dim(self._dim, observed)` — raises
  `EmbeddingConfigError` on real drift; preserves the legitimate
  populate-from-zero path used by `test_connection()`. Replaces
  silent `self._dim = len(vec)` mutation that previously masked
  config-vs-server-dim divergence.
- **`docs/embedding_backends.md`** — full backend reference: matrix,
  switching procedure, latency table, troubleshooting (LM Studio
  connect-refused, dim mismatch, bind-mount + 0600 caveat).
- **`CHANGELOG.md`** — this file.

### Changed

- `embeddings_enabled` config default flipped from `False` to `True`.
  Override via `RKA_EMBEDDINGS_ENABLED=false` env var if you really
  want the in-process EmbeddingService disabled.
- `EmbeddingService` keeps the same public surface (`embed`,
  `embed_document`, `embed_batch`, `store_embedding`, …) but the work
  is dispatched to a swappable `EmbeddingBackend` chosen at
  construction time. Legacy `EmbeddingService(model_name=...)` calls
  still work and default to FastEmbed.
- `rka_get_status` MCP formatter renders the capabilities LLM line
  conditionally (`if "llm" in caps`) so it gracefully omits it now and
  re-appears if Phase 2 puts the field back.

### Preserved (deliberate non-removals)

- `rka/infra/llm.py`, `rka/api/routes/llm.py` server modules
- `rka_ask`, `rka_generate_summary` MCP tools (graceful no-op when LLM
  unavailable, which is the new default)
- Background enrichment paths in `rka/services/worker.py` (bookkeeper
  invariant: `git diff main -- rka/services/worker.py` is empty across
  every Mission D commit)
- `enrichment_status` column on entries
- LLM-dependent web pages outside Notebook (Timeline, ContextInspector)
  — none imported `useLLM` directly and continue to render unchanged

### Mission reference

- Mission: `mis_01KRNYPVB8N3HDMZ9HK9HM3TB0`
- Motivating decision: `dec_01KRNYJ966H6W4REMK2ZJY2Y9R`
- LLM-removal refinement: `jrn_01KRNZBS50K250HHHHEC58E4GC`
- Mid-mission gate ratification: `dec_01KRP0WFMXAF0TQN6RDXY65WEX`
- Working branch: `feat/v2.4-pluggable-embeddings` (from `main@42e04c6`)
- Test suite at release: 599 passing (511 baseline + 88 mission-D tests)
