# M5 / PR 9 progressive-outline exit evidence

- Date: 2026-08-15
- Baseline: `a49475b8cefadeea8486023fa010ad36841a8979`
- Branch: `agent/m5-progressive-outline`
- Pull request: [#80](https://github.com/infinitywings/rka/pull/80)
- Scope: progressive L2-L5 manuscript outlines, unit writing rationale,
  evidence-linked edit/expand/condense/reorder proposals, and deterministic
  workbench navigation
- Data safety: the live RKA service and research projects were not changed;
  browser and pack acceptance used a disposable SQLite database and a
  short-lived production container bound only to `127.0.0.1:19712`

## Contract exercised

The release candidate implements the authority boundary frozen in
[ADR 0009](../../adr/0009-progressive-outline-and-unit-editor.md):

- every native manuscript unit may carry one project- and manuscript-scoped
  outline profile with L2-L5 hierarchy, writing job, takeaway, transition,
  quick-reader text, evidence/figure/table/citation plans, and blockers;
- outline profiles enrich stable `mun_` identities rather than creating a
  second manuscript authority;
- edit, expand, condense, and reorder prepare ADR 0006 semantic proposals and
  cannot mutate the manuscript before an explicit apply;
- expansion retains the parent and discloses inherited claim/evidence
  bindings; condensation unions descendant bindings and plans into the
  retained parent before removing descendants;
- reorder requires the exact active unit-key set and reports predecessor
  impact without changing semantic content;
- the projection exposes hierarchy, reverse claim/evidence trace, categorical
  completeness, and the current Outline checkpoint without resolving or
  ratifying either implicitly;
- REST, direct MCP, typed query/execute MCP, change cursors, knowledge packs,
  rekeying, integrity checks, and authorized whole-project deletion expose the
  same outline state; and
- the Writer guidance uses the same proposal-first, evidence-bounded contract.

## Automated verification

> **Independent-audit correction (2026-08-17):** the original run below
> verified default inheritance but did not exercise explicit child-binding
> narrowing, used a two-unit synthetic browser fixture rather than a real
> research project, and did not include frontend build CI. Those omissions
> invalidate the original merge-ready conclusion until the correction suite
> and real-project exit pass recorded in a later section are complete. The
> historical command results remain preserved rather than rewritten.

| Gate | Result |
|---|---|
| Full Python suite | `3114 passed, 5 warnings in 164.02s` |
| Focused service/API/MCP/migration suite | `968 passed` |
| Skill packaging suite | `2 passed` |
| TypeScript and production Vite build | Passed; 2,421 modules transformed |
| Targeted changed-workbench ESLint | Passed with zero findings |
| Changed Python Ruff gate outside the legacy monolithic MCP server | Passed |
| MCP server Ruff baseline comparison | Unchanged: 14 existing findings |
| Patch whitespace check | Passed |

The production build retains the repository's existing large-chunk advisory.
Repository-wide ESLint is not green on `main`: it reports the same seven
errors and two warnings in unrelated shared UI, Journal, Research Map, and
Settings files. Every changed workbench file passes the targeted gate.

## Browser acceptance walkthrough

The production frontend and feature-branch API were served from image
`rka-pr9-test:a49475b` on `127.0.0.1:19712` against a disposable project.
The browser opened manuscript `man_01M04B41F1VX37GJ9THAYGT33P` directly at
the Outline stage.

1. The projection showed two complete L2 units. Deterministic **Inspect**
   navigation exposed the exact unit, manuscript-claim, and evidence IDs.
2. An explicit action created pending Outline checkpoint
   `mck_01M04B61J828071SCB6NGZ0PJC`; outline edits did not resolve it.
3. Edit proposal `spp_01M04B6FS490CDJ6JWFQFNCE15` reported one semantic
   change and no warning. The canonical transition remained unchanged until
   apply, then the applied text appeared in the outline.
4. Reorder proposal `spp_01M04B712HF0CMBJJ8NGDZPP4V` reported two order
   changes and `OUTLINE_ORDER_CHANGED`; explicit apply changed the order.
5. Expansion proposal `spp_01M04B7PT9CSM4M4JH0A2V8TCG` added L3 child
   `METHOD.MECHANISM`, retained its parent, and disclosed the inherited claim
   and evidence binding before apply.
6. Condensation proposal `spp_01M04B82DQK5CX2KVNYNNB4Y85` reported the
   removed unit and downstream order impact. Explicit apply removed the child
   from the active projection and increased the retained parent evidence-plan
   count to three, demonstrating the union-before-removal invariant.
7. The final canonical projection was revision 7, ordered `METHOD`, `INTRO`,
   with all four proposals applied and the checkpoint still pending. The
   browser console contained no warning or error, and the rendered hierarchy,
   editor, proposal preview, trace panel, and checkpoint controls were visually
   inspected.

## Restart, pack, rekey, and deletion gate

After the disposable container restarted, the API and browser restored
revision 7, the active unit order, the removed-child history, all four applied
proposals, and the pending checkpoint. SQLite checks showed:

- active units `METHOD` at order 0 and `INTRO` at order 10;
- removed unit `METHOD.MECHANISM` retained in history;
- four applied semantic proposals and three outline profiles; and
- an empty `PRAGMA foreign_key_check`.

Exporting and importing the completed project restored 53 native rows,
including three profiles, three units, four proposals, and eight proposal
events. The removed child's parent rekeyed to the imported `METHOD` unit, and
all writing intentions and evidence plans remained exact. Authorized deletion
of imported project `prj_01M04BBBNEPFY4V3AWTYJ8RTKN` succeeded; the database
retained only the original disposable project and an empty foreign-key check.

## Independent-audit correction revalidation (2026-08-17)

The P1 and selected P2 corrections from the independent audit were validated
against the current PR branch after implementation:

| Correction gate | Result |
|---|---|
| Full Python suite | `3126 passed, 5 warnings in 188.36s` |
| Complete MCP plus semantic-patch API suite | `1431 passed in 19.80s` |
| Focused model-drift/MCP/outline suite | `965 passed in 2.90s` |
| Production Vite build | Passed; 2,421 modules transformed |
| Changed-workbench ESLint | Passed with zero findings |
| Writer skill validation and source/plugin mirror | Passed |
| Disposable real-project outline run | Passed against three actual claims from `prj_01KN51HD73DSY9ZR9C56JYRNYZ` |
| SQLite foreign-key check after the real-project run | Empty |

The real-project run exercised an AI-origin expansion proposal with an exact
host-agent context manifest, verified that the canonical manuscript remained
unchanged before review, and recorded PI application afterward. One child
narrowed two inherited support bindings to one and explicitly removed its
qualifier; a sibling inherited both support bindings and the qualifier. The
run also rejected child-before-parent ordering, accepted a parent-first
contiguous subtree order, captured an Outline checkpoint with
`rka.checkpoint-dependencies/v2`, and superseded that approval after a typed
support-to-qualifier binding change. Four active units and zero foreign-key
violations remained at the end.

The installed live server's complete export contained 5,882 rows but could
not be imported directly into the current-main schema: it carried five
forward-only staleness fields on claims and evidence clusters and one
pre-existing orphaned entity-link target. The disposable acceptance therefore
selected three real claims plus their source journal, explicitly removed 15
instances of only those forward-only fields, and imported that closed four-row
subset. This is a documented version-skew/integrity limitation of the source
pack, not a claim that full-pack portability passed.

## Exit decision

PR 9 now satisfies the independent-audit correction and feature-branch
verification gates and remains published for review in draft PR #80. Its
remaining gates are refreshed GitHub CI and human review. PR 10 must remain
dependent on PR 9 review and merge; it owns draft prose editing and source
synchronization rather than expanding this outline contract implicitly.
