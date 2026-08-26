# Claim-edge integrity independent audit and remediation record

- Status: remediated candidate; ready for final review before commit
- Date: 2026-08-25
- Baseline: `origin/main` at `57fa8f0`
- Candidate branch: `fix/claim-edge-integrity`
- Candidate commit before follow-up: `eb9faa3`
- Worktree:
  `/Volumes/FuSpace/Projects/rka/.claude/worktrees/rka-performance-eval-2d20e9`
- Safety: no live database, service rebuild, merge, commit, push, or remote
  change occurred during this audit and remediation

## 1. Audit verdict before remediation

The original candidate had the correct overall direction and a safe
transactional migration, but was not merge-ready. The independent review found:

1. **P1: retry was not a semantic no-op.** Reusing an existing `member_of`
   edge still updated the parent cluster, which appended a false immutable
   `change_events` row and advanced downstream cursors.
2. **P2: NULL cluster counts escaped repair.** Migration 052 and the integrity
   query used `!=`; SQLite treats `NULL != N` as unknown, so a legacy
   `claim_count=NULL` remained undetected.
3. **P2: split/merge accepted non-RQ decisions.** The path checked only project
   membership, not `kind='research_question'`, and could emit a semantically
   false `answers` link.
4. **P2: mixed-RQ merge silently selected the first RQ.** Merging clusters from
   different research questions without an explicit target reassigned evidence
   according to source order.

## 2. Remediation

The follow-up changed only the isolated candidate worktree.

- Duplicate membership creation now performs no cluster write and creates no
  change event when the existing cached count is correct.
- A genuinely stale cached count is still repaired on create or retry.
- Migration 052 and `check_integrity` use SQLite's NULL-safe `IS NOT`
  comparison.
- Split and merge require an in-project decision whose semantic kind is
  `research_question`.
- A merge across multiple source RQs requires an explicit valid target RQ.
- Full legacy knowledge-pack import now exercises duplicate-membership
  normalization and count repair.
- Two independent SQLite connections now exercise concurrent creation of the
  same membership.

Changed candidate files:

- `rka/db/migrations/052_claim_edge_membership_integrity.sql`
- `rka/services/claims.py`
- `rka/services/knowledge_pack.py`
- `rka/services/researcher_tools.py`
- `tests/test_db/test_migration_052.py`
- `tests/test_services/test_knowledge_pack.py`
- `tests/test_services/test_researcher_tools_transactions.py`

## 3. Database-copy validation

Migration 052 was run only against a temporary copy of the real database.

| Measure | Before | After |
|---|---:|---:|
| `member_of` rows | 971 | 967 |
| distinct memberships | 967 | 967 |
| duplicate memberships | 4 | 0 |
| cluster count mismatches | 3 | 0 |
| NULL cluster members | 0 | 0 |
| NULL claim counts | 0 | 0 |

The migration runner performs deletion, index creation, count repair, and
ledger registration in one transaction, so a failure rolls back the entire
migration.

## 4. Verification

| Gate | Result |
|---|---:|
| New and focused regression tests | 15 passed |
| Claim/cluster/graph/knowledge-pack expanded regression | 93 passed |
| Complete Core gate: DB + services + API + MCP | 2,804 passed |
| `git diff --check` | passed |
| Ruff critical syntax/undefined-name checks | passed |

The complete gate produced one existing Pydantic forward-reference warning.
The repository's default Ruff profile still reports 44 pre-existing lint items,
including executable-bit, import-order, and broad-exception debt; they were not
expanded into this bounded correctness change.

## 5. Residual risks and explicit non-goals

- Legacy pack normalization preserves the first duplicate membership in input
  order. Choosing a survivor by timestamp or provenance would be a separate
  policy decision.
- Source clusters remain as empty clusters after merge and retain their
  original `answers` links. This is existing behavior and needs a separate
  lifecycle decision if it should change.
- The database schema can still represent a `member_of` edge with
  `cluster_id=NULL` when bypassing the public service. Services reject it and
  integrity detects it; a relation-shape database constraint is future
  hardening.
- This Core gate does not include Writer-skill or frontend tests.

## 6. Recommendation

The initial `changes requested` verdict is resolved. The candidate is suitable
for final human/code review and then a commit on `fix/claim-edge-integrity`.
It should not be merged or pushed until that final review and the normal PR
authorization occur.
