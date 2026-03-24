"""Batch LLM enrichment endpoint — retroactively link existing entries."""

from __future__ import annotations

import asyncio
import logging
import subprocess
import uuid
import tempfile
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends

from rka.api.deps import require_project

router = APIRouter()
logger = logging.getLogger(__name__)

# In-progress job tracking (job_id -> {"status": str, "result": dict | None})
_enrich_jobs: dict[str, dict[str, str]] = {}

SCRIPT = """
import asyncio
import sqlite3
from rka.config import RKAConfig
from rka.infra.llm import LLMClient
from rka.infra.database import Database
from rka.services.notes import NoteService
from rka.services.role_events import RoleEventService
from rka.services.agent_roles import AgentRoleService

async def main():
    project_id = "{project_id}"
    limit = {limit}
    fix_types = {fix_types}

    config = RKAConfig()
    llm = LLMClient(config)
    db_url = config.database_url
    db = Database(db_url)
    await db.connect()

    revs = RoleEventService(db, project_id=project_id)
    arls = AgentRoleService(db, project_id=project_id)
    note_svc = NoteService(db, llm=llm, project_id=project_id, role_event_service=revs, agent_role_service=arls)

    rows = await db.fetchall(
        \"\"\"SELECT id, type, content FROM journal
           WHERE (related_decisions IS NULL OR related_decisions = '[]')
             AND (related_literature IS NULL OR related_literature = '[]')
             AND related_mission IS NULL
             AND project_id = ?
             AND confidence != 'superseded'
           ORDER BY created_at DESC LIMIT ?\"\"\",
        [project_id, limit],
    )

    updated = 0
    type_fixes = 0

    for row in rows:
        links = await note_svc._auto_link(row["content"], row["type"])
        if not links:
            continue
        updates = {{}}
        if links.related_decision_ids:
            updates["related_decisions"] = note_svc._json_dumps(links.related_decision_ids)
        if links.related_literature_ids:
            updates["related_literature"] = note_svc._json_dumps(links.related_literature_ids)
        if links.related_mission_id:
            updates["related_mission"] = links.related_mission_id
        if fix_types and links.suggested_type and links.suggested_type != row["type"]:
            _allowed = {{"finding", "insight", "pi_instruction", "exploration",
                        "idea", "observation", "hypothesis", "methodology", "summary"}}
            if links.suggested_type in _allowed:
                updates["type"] = links.suggested_type
                type_fixes += 1
        if updates:
            from rka.services.base import _now
            updates["updated_at"] = _now()
            set_clause = ", ".join(f"{{k}} = ?" for k in updates)
            await db.execute(
                f"UPDATE journal SET {{set_clause}} WHERE id = ? AND project_id = ?",
                list(updates.values()) + [row["id"], project_id],
            )
            await db.commit()
            updated += 1
            for dec_id in links.related_decision_ids:
                await note_svc.add_link("journal", row["id"], "references", "decision", dec_id, created_by="llm")
            for lit_id in links.related_literature_ids:
                await note_svc.add_link("journal", row["id"], "cites", "literature", lit_id, created_by="llm")
            if links.related_mission_id:
                await note_svc.add_link("mission", links.related_mission_id, "produced", "journal", row["id"], created_by="llm")

    await db.close()
    print(f"ENRICH_DONE: {{updated}} updated, {{type_fixes}} type_fixes, {{len(rows)}} scanned")

asyncio.run(main())
"""


@router.post("/enrich")
async def enrich_all(
    background_tasks: BackgroundTasks,
    limit: int = 50,
    fix_types: bool = True,
    project_id: str = Depends(require_project),
):
    """Re-run semantic linking on journal entries that have no relationships set.

    Returns a job ID immediately. Poll GET /enrich/<job_id> for results.
    The job runs as a subprocess so it doesn't block the HTTP response.
    """
    job_id = str(uuid.uuid4())[:8]
    _enrich_jobs[job_id] = {"status": "running", "result": "", "error": ""}

    def run_subprocess():
        import sys
        script = SCRIPT.format(project_id=project_id, limit=limit, fix_types=fix_types)
        try:
            proc = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if proc.returncode == 0:
                # Parse output: last line should be "ENRICH_DONE: ..."
                output = proc.stdout.strip()
                _enrich_jobs[job_id]["status"] = "done"
                _enrich_jobs[job_id]["result"] = output
            else:
                _enrich_jobs[job_id]["status"] = "failed"
                _enrich_jobs[job_id]["error"] = proc.stderr.strip()[-500:]
        except subprocess.TimeoutExpired:
            _enrich_jobs[job_id]["status"] = "failed"
            _enrich_jobs[job_id]["error"] = "Timed out after 300 seconds"
        except Exception as e:
            _enrich_jobs[job_id]["status"] = "failed"
            _enrich_jobs[job_id]["error"] = str(e)[:500]

    background_tasks.add_task(run_subprocess)
    return {"job_id": job_id, "status": "accepted"}


@router.get("/enrich/{job_id}")
async def enrich_status(job_id: str):
    """Poll the status/result of an enrichment job."""
    job = _enrich_jobs.get(job_id)
    if not job:
        return {"status": "not_found"}
    return {"job_id": job_id, "status": job["status"], "result": job.get("result"), "error": job.get("error")}
