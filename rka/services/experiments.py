"""Experiment-plan, execution-run, observation, and evidence-locator service."""

from __future__ import annotations

import json
from typing import Any

from rka.infra.ids import generate_id
from rka.models.experiment import (
    ClaimEvidenceRelation,
    EvidenceLocator,
    EvidenceLocatorCreate,
    Experiment,
    ExperimentCreate,
    ExperimentDetail,
    ExperimentObservation,
    ExperimentObservationCreate,
    ExperimentObservationDetail,
    ExperimentPlanAppend,
    ExperimentPlanVersion,
    ExperimentRun,
    ExperimentRunCreate,
    ExperimentRunDetail,
    ExperimentRunEvent,
    ExperimentRunTransition,
    ExperimentTransition,
)
from rka.services.base import BaseService, _precise_now
from rka.services.interpretation import InterpretationService


class ExperimentNotFoundError(ValueError):
    """Requested experiment-substrate entity is absent from this project."""


class ExperimentConflictError(ValueError):
    """Optimistic revision or lifecycle transition is stale/invalid."""


class ExperimentService(BaseService):
    """Manage research execution facts without inferring scientific support."""

    _EXPERIMENT_TRANSITIONS = {
        "planned": {"active", "abandoned"},
        "active": {"completed", "abandoned"},
        "completed": set(),
        "abandoned": set(),
    }
    _RUN_TRANSITIONS = {
        "queued": {"start": "running", "cancel": "cancelled"},
        "running": {
            "succeed": "succeeded",
            "fail": "failed",
            "cancel": "cancelled",
        },
        "succeeded": {},
        "failed": {},
        "cancelled": {},
    }

    async def create_experiment(self, data: ExperimentCreate) -> ExperimentDetail:
        experiment_id = generate_id("experiment")
        plan_id = generate_id("experiment_plan_version")
        now = _precise_now()
        async with self.db.transaction():
            await self.db.execute(
                """INSERT INTO experiments (
                       id, project_id, title, status, current_plan_version,
                       revision, created_by, created_at, updated_at
                   ) VALUES (?, ?, ?, 'planned', 1, 1, ?, ?, ?)""",
                [experiment_id, self.project_id, data.title, data.created_by, now, now],
            )
            await self._insert_plan(
                plan_id=plan_id,
                experiment_id=experiment_id,
                version=1,
                data=data,
                supersedes_plan_id=None,
                now=now,
            )
            await self.audit(
                "create",
                "experiment",
                experiment_id,
                self._audit_actor(data.created_by),
                {"plan_id": plan_id, "plan_version": 1},
            )
        detail = await self.get_experiment(experiment_id)
        assert detail is not None
        return detail

    async def list_experiments(
        self,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Experiment]:
        conditions = ["project_id = ?"]
        params: list[Any] = [self.project_id]
        if status is not None:
            conditions.append("status = ?")
            params.append(status)
        params.extend([limit, offset])
        rows = await self.db.fetchall(
            f"""SELECT * FROM experiments
                WHERE {' AND '.join(conditions)}
                ORDER BY updated_at DESC, id DESC LIMIT ? OFFSET ?""",
            params,
        )
        return [Experiment(**dict(row)) for row in rows]

    async def get_experiment(self, experiment_id: str) -> ExperimentDetail | None:
        row = await self.db.fetchone(
            "SELECT * FROM experiments WHERE id = ? AND project_id = ?",
            [experiment_id, self.project_id],
        )
        if row is None:
            return None
        plan_rows = await self.db.fetchall(
            """SELECT * FROM experiment_plan_versions
               WHERE experiment_id = ? AND project_id = ?
               ORDER BY version DESC""",
            [experiment_id, self.project_id],
        )
        run_rows = await self.db.fetchall(
            """SELECT * FROM experiment_runs
               WHERE experiment_id = ? AND project_id = ?
               ORDER BY created_at DESC, id DESC""",
            [experiment_id, self.project_id],
        )
        plans = [self._plan_from_row(item) for item in plan_rows]
        experiment = Experiment(**dict(row))
        current = next(
            plan for plan in plans if plan.version == experiment.current_plan_version
        )
        return ExperimentDetail(
            **experiment.model_dump(),
            current_plan=current,
            plan_versions=plans,
            runs=[self._run_from_row(item) for item in run_rows],
        )

    async def append_plan(
        self,
        experiment_id: str,
        data: ExperimentPlanAppend,
    ) -> ExperimentDetail:
        now = _precise_now()
        async with self.db.transaction():
            experiment = await self._require_experiment_revision(
                experiment_id, data.expected_revision
            )
            if experiment["status"] in {"completed", "abandoned"}:
                raise ExperimentConflictError(
                    "completed or abandoned experiments cannot receive new plan versions"
                )
            current_version = int(experiment["current_plan_version"])
            previous = await self.db.fetchone(
                """SELECT id FROM experiment_plan_versions
                   WHERE experiment_id = ? AND project_id = ? AND version = ?""",
                [experiment_id, self.project_id, current_version],
            )
            if previous is None:
                raise ExperimentConflictError("experiment plan head is inconsistent")
            next_version = current_version + 1
            plan_id = generate_id("experiment_plan_version")
            await self._insert_plan(
                plan_id=plan_id,
                experiment_id=experiment_id,
                version=next_version,
                data=data,
                supersedes_plan_id=previous["id"],
                now=now,
            )
            cursor = await self.db.execute(
                """UPDATE experiments
                   SET current_plan_version = ?, revision = ?, updated_at = ?
                   WHERE id = ? AND project_id = ? AND revision = ?""",
                [
                    next_version,
                    data.expected_revision + 1,
                    now,
                    experiment_id,
                    self.project_id,
                    data.expected_revision,
                ],
            )
            if cursor.rowcount != 1:
                raise ExperimentConflictError(
                    "experiment revision changed; reload before appending a plan"
                )
            await self.audit(
                "update",
                "experiment",
                experiment_id,
                self._audit_actor(data.created_by),
                {"operation": "append_plan", "plan_version": next_version},
            )
        detail = await self.get_experiment(experiment_id)
        assert detail is not None
        return detail

    async def transition_experiment(
        self,
        experiment_id: str,
        data: ExperimentTransition,
    ) -> ExperimentDetail:
        now = _precise_now()
        async with self.db.transaction():
            experiment = await self._require_experiment_revision(
                experiment_id, data.expected_revision
            )
            current = experiment["status"]
            if data.target_status not in self._EXPERIMENT_TRANSITIONS[current]:
                raise ExperimentConflictError(
                    f"cannot transition experiment from {current} to {data.target_status}"
                )
            if data.target_status in {"completed", "abandoned"}:
                active = await self.db.fetchone(
                    """SELECT 1 FROM experiment_runs
                       WHERE experiment_id = ? AND project_id = ?
                         AND status IN ('queued', 'running') LIMIT 1""",
                    [experiment_id, self.project_id],
                )
                if active is not None:
                    raise ExperimentConflictError(
                        "cannot close an experiment with queued or running runs"
                    )
            if data.target_status == "completed":
                terminal = await self.db.fetchone(
                    """SELECT 1 FROM experiment_runs
                       WHERE experiment_id = ? AND project_id = ?
                         AND status IN ('succeeded', 'failed') LIMIT 1""",
                    [experiment_id, self.project_id],
                )
                if terminal is None:
                    raise ExperimentConflictError(
                        "completed experiments require at least one succeeded or failed run"
                    )
            cursor = await self.db.execute(
                """UPDATE experiments
                   SET status = ?, revision = ?, updated_at = ?
                   WHERE id = ? AND project_id = ? AND revision = ?""",
                [
                    data.target_status,
                    data.expected_revision + 1,
                    now,
                    experiment_id,
                    self.project_id,
                    data.expected_revision,
                ],
            )
            if cursor.rowcount != 1:
                raise ExperimentConflictError(
                    "experiment revision changed; reload before transitioning"
                )
            await self.audit(
                "update",
                "experiment",
                experiment_id,
                self._audit_actor(data.actor),
                {
                    "operation": "transition",
                    "from_status": current,
                    "to_status": data.target_status,
                    "reason": data.reason,
                },
            )
        detail = await self.get_experiment(experiment_id)
        assert detail is not None
        return detail

    async def create_run(self, data: ExperimentRunCreate) -> ExperimentRunDetail:
        run_id = generate_id("experiment_run")
        event_id = generate_id("experiment_run_event")
        now = _precise_now()
        async with self.db.transaction():
            experiment = await self.db.fetchone(
                "SELECT status FROM experiments WHERE id = ? AND project_id = ?",
                [data.experiment_id, self.project_id],
            )
            if experiment is None:
                raise ExperimentNotFoundError(
                    f"experiment {data.experiment_id!r} not found"
                )
            if experiment["status"] in {"completed", "abandoned"}:
                raise ExperimentConflictError(
                    "completed or abandoned experiments cannot receive new runs"
                )
            plan = await self.db.fetchone(
                """SELECT 1 FROM experiment_plan_versions
                   WHERE experiment_id = ? AND project_id = ? AND version = ?""",
                [data.experiment_id, self.project_id, data.plan_version],
            )
            if plan is None:
                raise ExperimentNotFoundError(
                    "plan version is not available for this experiment and project"
                )
            await self.db.execute(
                """INSERT INTO experiment_runs (
                       id, experiment_id, project_id, plan_version, label,
                       runner, command, config, environment, repository_url,
                       commit_sha, working_tree_state, status, revision,
                       created_by, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', 1,
                             ?, ?, ?)""",
                [
                    run_id,
                    data.experiment_id,
                    self.project_id,
                    data.plan_version,
                    data.label,
                    data.runner,
                    data.command,
                    self._json_object(data.config),
                    self._json_object(data.environment),
                    data.repository_url,
                    data.commit_sha,
                    data.working_tree_state,
                    data.created_by,
                    now,
                    now,
                ],
            )
            await self.db.execute(
                """INSERT INTO experiment_run_events (
                       id, run_id, project_id, action, from_status, to_status,
                       run_revision, actor, reason, created_at
                   ) VALUES (?, ?, ?, 'created', NULL, 'queued', 1, ?, ?, ?)""",
                [event_id, run_id, self.project_id, data.created_by, data.reason, now],
            )
            await self.audit(
                "create",
                "experiment_run",
                run_id,
                self._audit_actor(data.created_by),
                {
                    "experiment_id": data.experiment_id,
                    "plan_version": data.plan_version,
                },
            )
        detail = await self.get_run(run_id)
        assert detail is not None
        return detail

    async def list_runs(
        self,
        *,
        experiment_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ExperimentRun]:
        conditions = ["project_id = ?"]
        params: list[Any] = [self.project_id]
        if experiment_id is not None:
            conditions.append("experiment_id = ?")
            params.append(experiment_id)
        if status is not None:
            conditions.append("status = ?")
            params.append(status)
        params.extend([limit, offset])
        rows = await self.db.fetchall(
            f"""SELECT * FROM experiment_runs
                WHERE {' AND '.join(conditions)}
                ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?""",
            params,
        )
        return [self._run_from_row(row) for row in rows]

    async def get_run(self, run_id: str) -> ExperimentRunDetail | None:
        row = await self.db.fetchone(
            "SELECT * FROM experiment_runs WHERE id = ? AND project_id = ?",
            [run_id, self.project_id],
        )
        if row is None:
            return None
        events = await self.db.fetchall(
            """SELECT * FROM experiment_run_events
               WHERE run_id = ? AND project_id = ?
               ORDER BY run_revision, created_at, id""",
            [run_id, self.project_id],
        )
        observations = await self.db.fetchall(
            """SELECT * FROM experiment_observations
               WHERE run_id = ? AND project_id = ?
               ORDER BY created_at, id""",
            [run_id, self.project_id],
        )
        run = self._run_from_row(row)
        return ExperimentRunDetail(
            **run.model_dump(),
            events=[ExperimentRunEvent(**dict(event)) for event in events],
            observations=[ExperimentObservation(**dict(item)) for item in observations],
        )

    async def transition_run(
        self,
        run_id: str,
        data: ExperimentRunTransition,
    ) -> ExperimentRunDetail:
        now = _precise_now()
        async with self.db.transaction():
            row = await self._require_run_revision(run_id, data.expected_revision)
            current = row["status"]
            target = self._RUN_TRANSITIONS[current].get(data.action)
            if target is None:
                raise ExperimentConflictError(
                    f"cannot {data.action} a run in {current} status"
                )
            next_revision = data.expected_revision + 1
            started_at = row.get("started_at")
            completed_at = row.get("completed_at")
            exit_code = row.get("exit_code")
            failure_summary = row.get("failure_summary")
            if data.action == "start":
                started_at = data.started_at or now
            else:
                completed_at = data.completed_at or now
                if data.action == "succeed":
                    exit_code = 0 if data.exit_code is None else data.exit_code
                    failure_summary = None
                elif data.action == "fail":
                    exit_code = data.exit_code
                    failure_summary = data.failure_summary
                else:
                    exit_code = data.exit_code
                    failure_summary = None
            cursor = await self.db.execute(
                """UPDATE experiment_runs
                   SET status = ?, started_at = ?, completed_at = ?,
                       exit_code = ?, failure_summary = ?, revision = ?,
                       updated_at = ?
                   WHERE id = ? AND project_id = ? AND revision = ?""",
                [
                    target,
                    started_at,
                    completed_at,
                    exit_code,
                    failure_summary,
                    next_revision,
                    now,
                    run_id,
                    self.project_id,
                    data.expected_revision,
                ],
            )
            if cursor.rowcount != 1:
                raise ExperimentConflictError(
                    "run revision changed; reload before transitioning"
                )
            event_id = generate_id("experiment_run_event")
            await self.db.execute(
                """INSERT INTO experiment_run_events (
                       id, run_id, project_id, action, from_status, to_status,
                       run_revision, actor, reason, exit_code, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    event_id,
                    run_id,
                    self.project_id,
                    data.action,
                    current,
                    target,
                    next_revision,
                    data.actor,
                    data.reason,
                    exit_code,
                    now,
                ],
            )
            await self.audit(
                "update",
                "experiment_run",
                run_id,
                self._audit_actor(data.actor),
                {
                    "action": data.action,
                    "from_status": current,
                    "to_status": target,
                    "revision": next_revision,
                },
            )
        detail = await self.get_run(run_id)
        assert detail is not None
        return detail

    async def create_observation(
        self,
        data: ExperimentObservationCreate,
    ) -> ExperimentObservationDetail:
        observation_id = generate_id("experiment_observation")
        async with self.db.transaction():
            run = await self.db.fetchone(
                "SELECT status FROM experiment_runs WHERE id = ? AND project_id = ?",
                [data.run_id, self.project_id],
            )
            if run is None:
                raise ExperimentNotFoundError(f"run {data.run_id!r} not found")
            if run["status"] == "queued":
                raise ExperimentConflictError(
                    "queued runs cannot have observations; start or terminate the run first"
                )
            await self.db.execute(
                """INSERT INTO experiment_observations (
                       id, run_id, project_id, name, kind, direction, summary,
                       value_real, value_text, unit, sample_size,
                       uncertainty_note, observed_at, recorded_by
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    observation_id,
                    data.run_id,
                    self.project_id,
                    data.name,
                    data.kind,
                    data.direction,
                    data.summary,
                    data.value_real,
                    data.value_text,
                    data.unit,
                    data.sample_size,
                    data.uncertainty_note,
                    data.observed_at,
                    data.recorded_by,
                ],
            )
            await self.audit(
                "create",
                "experiment_observation",
                observation_id,
                self._audit_actor(data.recorded_by),
                {"run_id": data.run_id, "kind": data.kind, "direction": data.direction},
            )
        detail = await self.get_observation(observation_id)
        assert detail is not None
        return detail

    async def list_observations(
        self,
        *,
        run_id: str | None = None,
        direction: str | None = None,
        kind: str | None = None,
        claim_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ExperimentObservation]:
        conditions = ["o.project_id = ?"]
        params: list[Any] = [self.project_id]
        if run_id is not None:
            conditions.append("o.run_id = ?")
            params.append(run_id)
        if direction is not None:
            conditions.append("o.direction = ?")
            params.append(direction)
        if kind is not None:
            conditions.append("o.kind = ?")
            params.append(kind)
        if claim_id is not None:
            conditions.append(
                """EXISTS (
                    SELECT 1 FROM claim_evidence_relations AS relation
                    WHERE relation.project_id = o.project_id
                      AND relation.observation_id = o.id
                      AND relation.claim_id = ?
                      AND relation.status = 'active'
                )"""
            )
            params.append(claim_id)
        params.extend([limit, offset])
        rows = await self.db.fetchall(
            f"""SELECT o.* FROM experiment_observations AS o
                WHERE {' AND '.join(conditions)}
                ORDER BY o.created_at DESC, o.id DESC LIMIT ? OFFSET ?""",
            params,
        )
        return [ExperimentObservation(**dict(row)) for row in rows]

    async def get_observation(
        self,
        observation_id: str,
    ) -> ExperimentObservationDetail | None:
        row = await self.db.fetchone(
            """SELECT * FROM experiment_observations
               WHERE id = ? AND project_id = ?""",
            [observation_id, self.project_id],
        )
        if row is None:
            return None
        locator_rows = await self.db.fetchall(
            """SELECT * FROM evidence_locators
               WHERE observation_id = ? AND project_id = ?
               ORDER BY created_at, id""",
            [observation_id, self.project_id],
        )
        relation_rows = await self.db.fetchall(
            """SELECT * FROM claim_evidence_relations
               WHERE observation_id = ? AND project_id = ?
               ORDER BY created_at, id""",
            [observation_id, self.project_id],
        )
        candidates = await InterpretationService(
            self.db,
            embeddings=self.embeddings,
            project_id=self.project_id,
        ).list(
            source_type="experiment_observation",
            source_id=observation_id,
            limit=200,
        )
        return ExperimentObservationDetail(
            **dict(row),
            locators=[EvidenceLocator(**dict(item)) for item in locator_rows],
            interpretation_candidates=[item.model_dump() for item in candidates],
            claim_relations=[ClaimEvidenceRelation(**dict(item)) for item in relation_rows],
        )

    async def add_locator(self, data: EvidenceLocatorCreate) -> EvidenceLocator:
        locator_id = generate_id("evidence_locator")
        async with self.db.transaction():
            observation = await self.db.fetchone(
                """SELECT 1 FROM experiment_observations
                   WHERE id = ? AND project_id = ?""",
                [data.observation_id, self.project_id],
            )
            if observation is None:
                raise ExperimentNotFoundError(
                    f"observation {data.observation_id!r} not found"
                )
            content_hash = data.content_hash
            if data.source_kind == "artifact":
                artifact = await self.db.fetchone(
                    """SELECT content_hash FROM artifacts
                       WHERE id = ? AND project_id = ?""",
                    [data.artifact_id, self.project_id],
                )
                if artifact is None:
                    raise ExperimentNotFoundError(
                        "artifact is not available in this project"
                    )
                artifact_hash = str(artifact.get("content_hash") or "").lower()
                if len(artifact_hash) != 64:
                    raise ValueError(
                        "artifact must have a 64-character content hash before it can be exact evidence"
                    )
                if content_hash is not None and content_hash.lower() != artifact_hash:
                    raise ExperimentConflictError(
                        "provided content_hash does not match the registered artifact"
                    )
                content_hash = artifact_hash
            assert content_hash is not None
            await self.db.execute(
                """INSERT INTO evidence_locators (
                       id, observation_id, project_id, source_kind, artifact_id,
                       repository_url, commit_sha, relative_path, locator_kind,
                       locator_start, locator_end, locator_value, content_hash,
                       label, created_by
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    locator_id,
                    data.observation_id,
                    self.project_id,
                    data.source_kind,
                    data.artifact_id,
                    data.repository_url,
                    data.commit_sha,
                    data.relative_path,
                    data.locator_kind,
                    data.locator_start,
                    data.locator_end,
                    data.locator_value,
                    content_hash.lower(),
                    data.label,
                    data.created_by,
                ],
            )
            await self.audit(
                "create",
                "evidence_locator",
                locator_id,
                self._audit_actor(data.created_by),
                {
                    "observation_id": data.observation_id,
                    "source_kind": data.source_kind,
                    "locator_kind": data.locator_kind,
                },
            )
        row = await self.db.fetchone(
            "SELECT * FROM evidence_locators WHERE id = ? AND project_id = ?",
            [locator_id, self.project_id],
        )
        assert row is not None
        return EvidenceLocator(**dict(row))

    async def _require_experiment_revision(
        self,
        experiment_id: str,
        revision: int,
    ) -> dict:
        row = await self.db.fetchone(
            "SELECT * FROM experiments WHERE id = ? AND project_id = ?",
            [experiment_id, self.project_id],
        )
        if row is None:
            raise ExperimentNotFoundError(f"experiment {experiment_id!r} not found")
        if int(row["revision"]) != revision:
            raise ExperimentConflictError(
                f"experiment revision is {row['revision']}, not expected {revision}"
            )
        return row

    async def _require_run_revision(self, run_id: str, revision: int) -> dict:
        row = await self.db.fetchone(
            "SELECT * FROM experiment_runs WHERE id = ? AND project_id = ?",
            [run_id, self.project_id],
        )
        if row is None:
            raise ExperimentNotFoundError(f"run {run_id!r} not found")
        if int(row["revision"]) != revision:
            raise ExperimentConflictError(
                f"run revision is {row['revision']}, not expected {revision}"
            )
        return row

    async def _insert_plan(
        self,
        *,
        plan_id: str,
        experiment_id: str,
        version: int,
        data: ExperimentCreate | ExperimentPlanAppend,
        supersedes_plan_id: str | None,
        now: str,
    ) -> None:
        await self.db.execute(
            """INSERT INTO experiment_plan_versions (
                   id, experiment_id, project_id, version, objective,
                   hypothesis, protocol, conditions, variables, metrics,
                   baselines, success_criteria, failure_criteria,
                   repository_url, commit_sha, working_tree_state, created_by,
                   reason, supersedes_plan_id, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                plan_id,
                experiment_id,
                self.project_id,
                version,
                data.objective,
                data.hypothesis,
                data.protocol,
                self._json_array(data.conditions),
                self._json_array(data.variables),
                self._json_array(data.metrics),
                self._json_array(data.baselines),
                self._json_array(data.success_criteria),
                self._json_array(data.failure_criteria),
                data.repository_url,
                data.commit_sha,
                data.working_tree_state,
                data.created_by,
                data.reason,
                supersedes_plan_id,
                now,
            ],
        )

    @staticmethod
    def _json_array(value: list[Any]) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _json_object(value: dict[str, Any]) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _json_load(value: Any, default: Any) -> Any:
        if isinstance(value, (dict, list)):
            return value
        try:
            parsed = json.loads(value) if isinstance(value, str) else default
        except (TypeError, json.JSONDecodeError):
            return default
        return parsed

    @classmethod
    def _plan_from_row(cls, row: dict) -> ExperimentPlanVersion:
        data = dict(row)
        for key in (
            "conditions",
            "variables",
            "metrics",
            "baselines",
            "success_criteria",
            "failure_criteria",
        ):
            data[key] = cls._json_load(data.get(key), [])
        return ExperimentPlanVersion(**data)

    @classmethod
    def _run_from_row(cls, row: dict) -> ExperimentRun:
        data = dict(row)
        data["config"] = cls._json_load(data.get("config"), {})
        data["environment"] = cls._json_load(data.get("environment"), {})
        return ExperimentRun(**data)

    @staticmethod
    def _audit_actor(actor: str) -> str:
        return "system" if actor == "import" else actor
