"""CRUD over the orchestrator-owned SQLite tables.

Two tables, both defined in `db/schema.sql`:

  - **workflow_runs** — one row per `orchestrator_run_start` call,
    keyed on `workflow_thread_id`. Holds run lifecycle (status,
    current_node, terminal_state, usd_spent).

  - **parked_interrupts** — one row per PI `interrupt()` event,
    keyed on `interrupt_id`. Holds the structured payload + the
    PI's response once `answer_interrupt` is called.

Three-storage discipline: this DB is orchestrator-owned only. The
LangGraph SqliteSaver keeps a separate file for workflow position;
RKA domain truth lives in `rka.db`. No cross-DB joins.

The store is sqlite3-synchronous (no async wrapper) because all our
operations are single-row reads/writes and the LangGraph SqliteSaver
also uses sync sqlite3. Keeping both on the same model avoids any
event-loop interaction between the two writers.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Literal, Optional

SCHEMA_PATH = Path(__file__).resolve().parent / "db" / "schema.sql"

InterruptType = Literal[
    # Mission-level interrupts (Phase A)
    "pi_greenlight",
    "pi_decision_select",
    "pi_acceptance",
    # Onboarding subgraph interrupts (Phase D)
    "pi_onboarding_topic",
    "pi_toolkit_ratify",
    "pi_credentials_ready",
    "pi_extend_toolkit",
    # Phase O — project-onboarding workflow interrupts
    "pi_idea_capture",
    "pi_scope_ratify",
    "pi_deepresearch_prompt",
    "pi_claims_review",
    "pi_plan_ratify",
    "pi_phase_entry_ack",
    # Phase B — orchestrator-level bootstrap (orchestrator/.env)
    "pi_bootstrap_intent",
    "pi_bootstrap_ratify",
    "pi_bootstrap_fill_ack",
]
ResponseAction = Literal["accept", "reject", "correct"]
RunStatus = Literal[
    "running", "awaiting_pi", "complete", "escalated", "failed", "cancelled"
]


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_id(prefix: str) -> str:
    """Compact ULID-ish ID. Time-prefixed for natural sort, hex tail for uniqueness."""
    return f"{prefix}_{int(time.time() * 1000):x}{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Connection management
# ---------------------------------------------------------------------------


class ParkedStore:
    """Sync sqlite3 store for workflow_runs + parked_interrupts.

    Pass `db_path=":memory:"` for tests; pass an absolute file path in
    production. The constructor initializes the schema idempotently
    (`CREATE TABLE IF NOT EXISTS`).
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._conn = sqlite3.connect(
            db_path,
            check_same_thread=False,
            isolation_level=None,  # autocommit; we manage transactions explicitly
        )
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        sql = SCHEMA_PATH.read_text(encoding="utf-8")
        with self._conn:
            self._conn.executescript(sql)
        self._migrate_pre_phase_o_if_needed()
        self._migrate_project_workspaces_columns_if_needed()

    def _migrate_project_workspaces_columns_if_needed(self) -> None:
        """Add manifest_json, manifest_hash, audit_journal_id, updated_at
        columns to project_workspaces if missing. Idempotent."""
        row = self._conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='project_workspaces'"
        ).fetchone()
        if row is None:
            return
        create_sql = row[0] or ""
        with self._conn:
            if "manifest_json" not in create_sql:
                self._conn.execute(
                    "ALTER TABLE project_workspaces ADD COLUMN manifest_json TEXT"
                )
            if "manifest_hash" not in create_sql:
                self._conn.execute(
                    "ALTER TABLE project_workspaces ADD COLUMN manifest_hash TEXT"
                )
            if "audit_journal_id" not in create_sql:
                self._conn.execute(
                    "ALTER TABLE project_workspaces ADD COLUMN audit_journal_id TEXT"
                )
            if "updated_at" not in create_sql:
                # SQLite rejects ALTER TABLE ADD COLUMN with non-constant
                # defaults. Add the column nullable, then backfill.
                self._conn.execute(
                    "ALTER TABLE project_workspaces ADD COLUMN updated_at TEXT"
                )
                self._conn.execute(
                    "UPDATE project_workspaces SET updated_at = "
                    "strftime('%Y-%m-%dT%H:%M:%SZ', 'now') "
                    "WHERE updated_at IS NULL"
                )

    def _migrate_pre_phase_o_if_needed(self) -> None:
        """Detect a parked_interrupts CHECK constraint missing Phase-O
        types and rebuild with the current schema.sql shape.

        Each schema version is a strict superset of the previous, so a
        single sentinel check (`pi_idea_capture` present) is enough to
        cover both the Phase-A → Phase-O and Phase-D → Phase-O paths.
        SQLite doesn't support ALTER TABLE for CHECK constraints, so we
        rebuild the table.

        Idempotent: safe to call on every startup. Only does work when
        the legacy constraint is detected.

        Rows are preserved across the rebuild via INSERT...SELECT — any
        in-flight workflows survive the migration. The Phase-O CHECK is
        a strict superset of all earlier shapes, so every legacy row
        satisfies the new constraint.
        """
        row = self._conn.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE type='table' AND name='parked_interrupts'"
        ).fetchone()
        if row is None:
            return  # Table doesn't exist yet — schema.sql will create it next pass.
        create_sql = row[0] or ""
        if "pi_bootstrap_intent" in create_sql:
            return  # Already Phase-B shape (sentinel: first Phase-B interrupt type).

        # Legacy shape detected: rebuild with the new CHECK.
        with self._conn:
            self._conn.execute(
                "ALTER TABLE parked_interrupts RENAME TO _parked_interrupts_pre_o"
            )
            # Re-run schema.sql; the CREATE IF NOT EXISTS picks up the new shape.
            sql = SCHEMA_PATH.read_text(encoding="utf-8")
            self._conn.executescript(sql)
            self._conn.execute(
                "INSERT INTO parked_interrupts "
                "(interrupt_id, workflow_thread_id, mission_id, interrupt_type, "
                " payload_json, status, response_action, response_text, "
                " parked_at, responded_at) "
                "SELECT interrupt_id, workflow_thread_id, mission_id, interrupt_type, "
                "       payload_json, status, response_action, response_text, "
                "       parked_at, responded_at "
                "FROM _parked_interrupts_pre_o"
            )
            self._conn.execute("DROP TABLE _parked_interrupts_pre_o")

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        """Single-statement transaction context."""
        try:
            self._conn.execute("BEGIN")
            yield self._conn
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    # -----------------------------------------------------------------
    # workflow_runs
    # -----------------------------------------------------------------

    def create_run(
        self,
        *,
        mission_id: str,
        project_id: str,
        budget_usd: float = 5.0,
        workflow_thread_id: Optional[str] = None,
    ) -> str:
        """Insert a new workflow_runs row. Returns the workflow_thread_id."""
        thread_id = workflow_thread_id or _new_id("thr")
        with self._tx() as c:
            c.execute(
                """INSERT INTO workflow_runs
                   (workflow_thread_id, mission_id, project_id, budget_usd)
                   VALUES (?, ?, ?, ?)""",
                (thread_id, mission_id, project_id, budget_usd),
            )
        return thread_id

    def get_run(self, workflow_thread_id: str) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT * FROM workflow_runs WHERE workflow_thread_id = ?",
            (workflow_thread_id,),
        ).fetchone()
        return dict(row) if row else None

    def list_runs(
        self,
        *,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        if status:
            rows = self._conn.execute(
                "SELECT * FROM workflow_runs WHERE status = ? "
                "ORDER BY updated_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM workflow_runs ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def update_run(
        self,
        workflow_thread_id: str,
        **fields: Any,
    ) -> None:
        """Patch arbitrary columns. Always bumps updated_at.

        Allowed columns are restricted to the schema; passing an unknown
        key raises ValueError so a typo can't silently no-op.
        """
        allowed = {
            "status",
            "current_node",
            "terminal_state",
            "final_report_id",
            "usd_spent",
            "last_error",
        }
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"update_run: unknown columns {sorted(bad)}")
        if not fields:
            return
        cols = ", ".join(f"{k} = ?" for k in fields)
        params = list(fields.values())
        params.append(_now_iso())
        params.append(workflow_thread_id)
        with self._tx() as c:
            c.execute(
                f"UPDATE workflow_runs SET {cols}, updated_at = ? "
                f"WHERE workflow_thread_id = ?",
                params,
            )

    # -----------------------------------------------------------------
    # parked_interrupts
    # -----------------------------------------------------------------

    def park_interrupt(
        self,
        *,
        workflow_thread_id: str,
        mission_id: str,
        interrupt_type: InterruptType,
        payload: dict,
    ) -> str:
        """Insert a pending interrupt row. Also flips the run's status to
        'awaiting_pi'. Returns the interrupt_id."""
        interrupt_id = _new_id("int")
        with self._tx() as c:
            c.execute(
                """INSERT INTO parked_interrupts
                   (interrupt_id, workflow_thread_id, mission_id,
                    interrupt_type, payload_json)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    interrupt_id,
                    workflow_thread_id,
                    mission_id,
                    interrupt_type,
                    json.dumps(payload),
                ),
            )
            c.execute(
                "UPDATE workflow_runs SET status = 'awaiting_pi', "
                "updated_at = ? WHERE workflow_thread_id = ?",
                (_now_iso(), workflow_thread_id),
            )
        return interrupt_id

    def get_interrupt(self, interrupt_id: str) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT * FROM parked_interrupts WHERE interrupt_id = ?",
            (interrupt_id,),
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["payload"] = json.loads(d.pop("payload_json"))
        return d

    def list_pending_interrupts(
        self,
        workflow_thread_id: Optional[str] = None,
    ) -> list[dict]:
        if workflow_thread_id:
            rows = self._conn.execute(
                "SELECT * FROM parked_interrupts "
                "WHERE status = 'pending' AND workflow_thread_id = ? "
                "ORDER BY parked_at ASC",
                (workflow_thread_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM parked_interrupts "
                "WHERE status = 'pending' ORDER BY parked_at ASC"
            ).fetchall()
        out: list[dict] = []
        for r in rows:
            d = dict(r)
            d["payload"] = json.loads(d.pop("payload_json"))
            out.append(d)
        return out

    def answer_interrupt(
        self,
        *,
        interrupt_id: str,
        response_action: ResponseAction,
        response_text: str,
    ) -> dict:
        """Mark a pending interrupt as answered. Returns the updated row.

        Raises ValueError if the interrupt is not in 'pending' state — the
        caller should treat this as a conflict (already answered / cancelled).
        """
        with self._tx() as c:
            row = c.execute(
                "SELECT status FROM parked_interrupts WHERE interrupt_id = ?",
                (interrupt_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"interrupt {interrupt_id} not found")
            if row["status"] != "pending":
                raise ValueError(
                    f"interrupt {interrupt_id} already in status={row['status']!r}"
                )
            c.execute(
                """UPDATE parked_interrupts
                   SET status = 'answered',
                       response_action = ?,
                       response_text = ?,
                       responded_at = ?
                   WHERE interrupt_id = ?""",
                (response_action, response_text, _now_iso(), interrupt_id),
            )
        result = self.get_interrupt(interrupt_id)
        assert result is not None
        return result

    def cancel_run(self, workflow_thread_id: str) -> int:
        """Mark all pending interrupts for the run as cancelled, set run
        status='cancelled'. Returns the count of cancelled interrupts."""
        with self._tx() as c:
            cur = c.execute(
                "UPDATE parked_interrupts SET status = 'cancelled', "
                "responded_at = ? "
                "WHERE workflow_thread_id = ? AND status = 'pending'",
                (_now_iso(), workflow_thread_id),
            )
            count = cur.rowcount
            c.execute(
                "UPDATE workflow_runs SET status = 'cancelled', "
                "updated_at = ? WHERE workflow_thread_id = ?",
                (_now_iso(), workflow_thread_id),
            )
        return count

    # -----------------------------------------------------------------
    # project_workspaces — PI-provided workspace path per project
    # -----------------------------------------------------------------

    def set_project_workspace(self, project_id: str, workspace_path: str) -> None:
        """Record the workspace path the PI provided for this project."""
        with self._tx() as c:
            c.execute(
                """INSERT INTO project_workspaces (project_id, workspace_path)
                   VALUES (?, ?)
                   ON CONFLICT(project_id) DO UPDATE
                     SET workspace_path = excluded.workspace_path,
                         updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')""",
                (project_id, workspace_path),
            )

    def get_project_workspace(self, project_id: str) -> Optional[str]:
        """Return the PI-provided workspace path for this project, or None."""
        row = self._conn.execute(
            "SELECT workspace_path FROM project_workspaces WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        return row["workspace_path"] if row else None

    def set_project_manifest(
        self,
        project_id: str,
        manifest_json: str,
        manifest_hash: str,
        *,
        workspace_path: Optional[str] = None,
    ) -> None:
        """Persist the project's tool manifest content in the orchestrator
        store. Called by draft_manifest_node so get_manifest can return
        the content without depending on host-filesystem access."""
        with self._tx() as c:
            if workspace_path:
                c.execute(
                    """INSERT INTO project_workspaces
                         (project_id, workspace_path, manifest_json, manifest_hash)
                       VALUES (?, ?, ?, ?)
                       ON CONFLICT(project_id) DO UPDATE
                         SET workspace_path = excluded.workspace_path,
                             manifest_json = excluded.manifest_json,
                             manifest_hash = excluded.manifest_hash,
                             updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')""",
                    (project_id, workspace_path, manifest_json, manifest_hash),
                )
            else:
                # Update manifest fields only; workspace_path must already exist.
                c.execute(
                    """UPDATE project_workspaces
                       SET manifest_json = ?, manifest_hash = ?,
                           updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
                       WHERE project_id = ?""",
                    (manifest_json, manifest_hash, project_id),
                )

    def get_project_manifest(self, project_id: str) -> Optional[dict]:
        """Return the stored manifest (project_id, workspace_path,
        manifest_json, manifest_hash, audit_journal_id) for the project,
        or None if no manifest is registered yet."""
        row = self._conn.execute(
            """SELECT project_id, workspace_path, manifest_json, manifest_hash,
                      audit_journal_id, registered_at, updated_at
               FROM project_workspaces WHERE project_id = ?""",
            (project_id,),
        ).fetchone()
        return dict(row) if row else None

    def set_project_audit_id(self, project_id: str, audit_journal_id: str) -> None:
        """Stamp the finalize-time audit journal id onto the manifest record."""
        with self._tx() as c:
            c.execute(
                """UPDATE project_workspaces
                   SET audit_journal_id = ?,
                       updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
                   WHERE project_id = ?""",
                (audit_journal_id, project_id),
            )
