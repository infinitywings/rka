# Active Workflow

This file tracks the current state of the manuscript so the Writer can
resume on session start. Update at session end via the digest sub-procedure.

current_phase: venue_selection
last_checkpoint: (none)
next_action: Confirm target venue with PI and run the Venue handler sub-procedure.
last_session: (initial bootstrap)

## Phase markers (reference)

| Phase | Trigger to advance |
|---|---|
| venue_selection | Venue checkpoint ratified; .planning/PRECIS.md authored |
| framing_elicitation | Choice rounds complete; PI confirms one provisional spine |
| evidence_synthesis | In-scope RQs selected; cluster blockers and counterevidence resolved |
| contribution_contract | Exact allowed/prohibited contribution boundary accepted for spine import |
| outline | Outline checkpoint ratified; .planning/OUTLINE.md ratified |
| table_figure_plan | Table/figure plan checkpoint ratified |
| reference_set | References ratified; refs.bib populated with VERIFIED entries |
| drafting | Section drafts in progress; last completed section in `last_section_drafted` |
| review | All sections drafted; PI reviewing |
| revision | PI returned comments; iteration count in REVIEW_STATE.md |
| final_layout | Full draft compiles; layout audit PASS or WARN; PI ratifies submit |
| submitted | Native manuscript transitioned after final readiness and PI approval |

## Notes

Project: REPLACE_WITH_PROJECT_ID
Canonical manuscript: REPLACE_WITH_MANUSCRIPT_ID (created or verified by
`rka writer init` before this workspace was published).
