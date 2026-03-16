"""Onboarding service — generates project-specific CLAUDE.md files."""

from __future__ import annotations

import logging

from rka.services.base import BaseService

logger = logging.getLogger(__name__)

ROLE_DESCRIPTIONS = {
    "executor": "the implementation AI — you write code, run experiments, process data, and execute missions assigned by the Brain.",
    "brain": "the strategic AI — you interpret findings, make research decisions, manage literature, and direct the Executor.",
}


class OnboardingService(BaseService):
    """Generates project-specific CLAUDE.md for AI agents."""

    async def generate_claude_md(self, role: str = "executor") -> str:
        """Query the live database and produce a project-specific CLAUDE.md."""
        role = role.lower()
        if role not in ROLE_DESCRIPTIONS:
            role = "executor"

        sections: list[str] = []

        # --- Project header ---
        state = await self._get_project_state()
        project_name = state.get("project_name", "Untitled Project")
        phase = state.get("current_phase", "unknown")
        summary = (state.get("summary") or "")[:200]
        role_title = role.capitalize()

        sections.append(f"# CLAUDE.md \u2014 {project_name} ({role_title} instructions)\n")
        sections.append(
            f"This project uses **RKA (Research Knowledge Agent)** for persistent knowledge management.\n"
            f"You are the **{role_title}**: {ROLE_DESCRIPTIONS[role]}\n"
        )
        sections.append("---\n")
        sections.append(
            f"## Project\n"
            f"**Name**: {project_name}\n"
            f"**Phase**: {phase}\n"
            f"**RKA dashboard**: http://127.0.0.1:9712\n"
            f"**Focus**: {summary or 'Not set'}\n"
        )

        # --- Session start protocol ---
        sections.append("---\n")
        sections.append("## Session Start Protocol\n")
        if role == "executor":
            sections.append(
                "1. `rka_get_context()` \u2014 load current project state\n"
                "2. `rka_get_mission()` \u2014 check for active/pending missions\n"
                "3. `rka_get_checkpoints(status=\"open\")` \u2014 check for blockers\n"
            )
        else:
            sections.append(
                "1. `rka_get_context()` \u2014 load current project state\n"
                "2. `rka_get_checkpoints(status=\"open\")` \u2014 resolve Executor blockers first\n"
                "3. `rka_get_review_queue()` \u2014 items flagged for your attention\n"
                "4. `rka_get_research_map()` \u2014 see the big picture\n"
            )

        # --- Active Research Questions ---
        rqs = await self._get_research_questions()
        sections.append("---\n")
        sections.append("## Active Research Questions\n")
        if rqs:
            for rq in rqs:
                sections.append(
                    f"- **{rq['question']}** "
                    f"(clusters: {rq['cluster_count']}, claims: {rq['claim_count']}, gaps: {rq['gap_count']})"
                )
        else:
            sections.append(
                'No research questions defined yet. Use `rka_add_decision(kind="research_question")` to create one.'
            )
        sections.append("")

        # --- Active Missions ---
        missions = await self._get_active_missions()
        sections.append("## Active Missions\n")
        if missions:
            for m in missions:
                task_count = len((m.get("tasks") or "").split("\n")) if m.get("tasks") else 0
                sections.append(
                    f"- [{m['status']}] **{m['objective']}** (ID: `{m['id']}`)\n"
                    f"  Tasks: {task_count}, Phase: {m.get('phase', 'n/a')}"
                )
        else:
            sections.append("No active missions.")
        sections.append("")

        # --- Recording Standards ---
        active_mission_id = missions[0]["id"] if missions and missions[0]["status"] == "active" else "{mission_id}"
        sections.append("## Recording Standards (v2.0)\n")
        sections.append("| Situation | Tool | Parameters |")
        sections.append("|-----------|------|-----------|")
        sections.append(f'| Got a result | `rka_add_note` | `type="note", related_mission="{active_mission_id}"` |')
        sections.append(f'| Ran an experiment/procedure | `rka_add_note` | `type="log", related_mission="{active_mission_id}"` |')
        sections.append('| PI/Brain instruction | `rka_add_note` | `type="directive"` |')
        sections.append("| Hit a decision point | `rka_submit_checkpoint` | `blocking=True` |")
        sections.append("| Finished a mission | `rka_submit_report` | Include `related_decisions=[...]` |")
        sections.append("| Found a paper | `rka_add_literature` or `rka_enrich_doi` | |")
        sections.append("| Made a decision | `rka_add_decision` | Include `related_journal=[...]` |")
        sections.append("")
        sections.append("**Always set `related_mission` when working on a mission task.**")
        sections.append("**Always set `related_decisions` when a finding bears on a decision.**\n")

        # --- Established Tags ---
        tags = await self._get_top_tags()
        sections.append("## Established Tags\n")
        if tags:
            for t in tags:
                sections.append(f"- `{t['tag']}` ({t['cnt']} entries)")
        else:
            sections.append("No tags established yet.")
        sections.append("")

        # --- Established Topics ---
        topics = await self._get_topics()
        sections.append("## Established Topics\n")
        if topics:
            for t in topics:
                desc = t.get("description") or "No description"
                sections.append(f"- `{t['name']}` \u2014 {desc}")
        else:
            sections.append("No topics defined yet.")
        sections.append("")

        # --- Open Checkpoints ---
        checkpoints = await self._get_open_checkpoints()
        sections.append("## Open Checkpoints\n")
        if checkpoints:
            for cp in checkpoints:
                cp_type = cp.get("type", "question")
                sections.append(f"- [{cp_type}] **{cp['description']}** (ID: `{cp['id']}`)")
        else:
            sections.append("No open checkpoints.")
        sections.append("")

        # --- Key Decisions ---
        decisions = await self._get_recent_decisions()
        sections.append("## Key Decisions (recent)\n")
        if decisions:
            for d in decisions:
                chosen = d.get("chosen") or "pending"
                kind = d.get("kind", "decision")
                sections.append(f"- **{d['question']}** \u2192 {chosen} ({kind})")
        else:
            sections.append("No decisions recorded yet.")
        sections.append("")

        # --- Constraints ---
        sections.append("## Constraints\n")
        sections.append("- Journal entry types: `note` (observations/analyses), `log` (procedures), `directive` (instructions)")
        sections.append("- Old types (finding, insight, methodology, etc.) are accepted but mapped to these three")
        sections.append("- Always set `related_mission` when working on a mission task")
        sections.append("- Always set `related_decisions` when a finding bears on a decision")
        sections.append("- Raise checkpoints for strategic decisions \u2014 don\u2019t decide unilaterally")
        sections.append("- Cross-reference everything: decisions need `related_journal`, missions need `motivated_by_decision`")

        return "\n".join(sections)

    # ---- Private query helpers ----

    async def _get_project_state(self) -> dict:
        row = await self.db.fetchone(
            "SELECT * FROM project_states WHERE project_id = ?",
            [self.project_id],
        )
        return dict(row) if row else {}

    async def _get_research_questions(self) -> list[dict]:
        try:
            rqs = await self.db.fetchall(
                """SELECT d.id, d.question, d.status
                   FROM decisions d
                   WHERE d.project_id = ? AND d.kind = 'research_question' AND d.status = 'active'
                   ORDER BY d.created_at DESC""",
                [self.project_id],
            )
            result = []
            for rq in rqs:
                stats = await self.db.fetchone(
                    """SELECT COUNT(*) as cluster_count,
                              COALESCE(SUM(claim_count), 0) as claim_count,
                              COALESCE(SUM(gap_count), 0) as gap_count
                       FROM evidence_clusters
                       WHERE research_question_id = ? AND project_id = ?""",
                    [rq["id"], self.project_id],
                )
                result.append({
                    "question": rq["question"],
                    "cluster_count": (stats["cluster_count"] or 0) if stats else 0,
                    "claim_count": (stats["claim_count"] or 0) if stats else 0,
                    "gap_count": (stats["gap_count"] or 0) if stats else 0,
                })
            return result
        except Exception:
            return []

    async def _get_active_missions(self) -> list[dict]:
        rows = await self.db.fetchall(
            """SELECT id, objective, status, phase, tasks
               FROM missions
               WHERE project_id = ? AND status IN ('pending', 'active')
               ORDER BY created_at DESC""",
            [self.project_id],
        )
        return [dict(r) for r in rows]

    async def _get_top_tags(self) -> list[dict]:
        rows = await self.db.fetchall(
            """SELECT tag, COUNT(*) as cnt
               FROM tags WHERE project_id = ?
               GROUP BY tag ORDER BY cnt DESC LIMIT 20""",
            [self.project_id],
        )
        return [dict(r) for r in rows]

    async def _get_topics(self) -> list[dict]:
        try:
            rows = await self.db.fetchall(
                "SELECT name, description FROM topics WHERE project_id = ? ORDER BY name",
                [self.project_id],
            )
            return [dict(r) for r in rows]
        except Exception:
            return []

    async def _get_open_checkpoints(self) -> list[dict]:
        rows = await self.db.fetchall(
            """SELECT id, description, type
               FROM checkpoints
               WHERE project_id = ? AND status = 'open'
               ORDER BY created_at DESC""",
            [self.project_id],
        )
        return [dict(r) for r in rows]

    async def _get_recent_decisions(self) -> list[dict]:
        rows = await self.db.fetchall(
            """SELECT question, chosen, kind, status
               FROM decisions
               WHERE project_id = ? AND status = 'active'
               ORDER BY created_at DESC LIMIT 10""",
            [self.project_id],
        )
        return [dict(r) for r in rows]
