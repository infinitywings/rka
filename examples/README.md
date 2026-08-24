# Example knowledge pack

`rka_development.rka-pack.zip` is a real RKA project: the knowledge base that
was used to build RKA itself. Import it to see what a research log looks like
after a year of use — decisions with recorded rationale, supersede chains,
missions with reports, claims grouped into evidence clusters, and the typed
links between all of them.

```bash
curl -F "file=@examples/rka_development.rka-pack.zip" \
     -F "project_name=rka-sample" \
     http://localhost:9712/api/projects/import
```

| | |
|---|---|
| Rows | 9,365 across 13 populated tables |
| Journal entries | 1,647 |
| Decisions | 145 (incl. supersede chains) |
| Claims / clusters | 142 / 20 |
| Missions | 116 |
| Literature | 159 |
| Typed links | 2,800 |
| Exported | 2026-08-24, pack schema 50 |

## Why this project makes a useful sample

It is not a curated demo. It is the log of a real, messy project, so it
contains the things a synthetic fixture usually lacks: decisions that were
later reversed, missions that ended in `partial`, claims whose evidence turned
out to be contested, and entries written before conventions settled. Retrieval
and traversal behave differently on that than on clean data, which is the point.

## What was removed before publication

The pack is a faithful dump of a working research log, so it could not be
published unread. [`scripts/sanitize_knowledge_pack.py`](../scripts/sanitize_knowledge_pack.py)
applies a fixed rule set and refuses to write output if anything still matches
its residual checks. On this export it made 219 replacements:

| What | Count | Becomes |
|---|---|---|
| Absolute paths under a home directory | 146 | `/Users/researcher/…` |
| Ids of the researcher's other projects | 26 | `prj_0000…` placeholders |
| Names of those projects | 15 | `project-B` … `project-K` |
| Paths under the workspace volume | 11 | `/Volumes/Workspace/…` |
| Private-range IP addresses | 11 | RFC 5737 `192.0.2.x` |
| Course and LMS identifiers | 6 | `[course]`, `course ID [redacted]` |
| Third-party names | 3 | `[collaborator]` |
| One grant fit-assessment section | 1 | redaction notice |

Cross-project references are aliased rather than deleted, so an entry that says
"unlike what we did in project-C" still reads coherently. The `project-B` … `-K`
labels are ordered by corpus size and match the ones used in the eval-harness
reports.

The sanitizer deliberately does **not** redact the project owner's name or
affiliation. Those are already in every commit in this repository; blanking
them in the sample would be theatre, not privacy.

One journal entry retains a summary of a public NSF solicitation — its number,
terms and deadlines are published by NSF — while the section that assessed how
an internal research direction fit it, and named collaborators, is replaced by
a redaction notice.

## Re-exporting

To refresh the sample from a live project:

```bash
curl -H "X-RKA-Project: <project_id>" \
     -o fresh.rka-pack.zip \
     http://localhost:9712/api/projects/export

python scripts/sanitize_knowledge_pack.py fresh.rka-pack.zip \
       examples/rka_development.rka-pack.zip
```

The sanitizer exits non-zero and writes nothing if any residual check fires, so
a rule that has gone stale fails loudly rather than shipping a leak. Run
`--check` on its own to scan a pack without rewriting it.
