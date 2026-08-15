"""Durable semantic change cursor and manuscript dependency impact.

The cursor is a read-only projection of trigger-maintained ``change_events``.
It is deliberately not a scientific-validity score: callers receive exact
changed dependencies and categorical impact state so they can decide which
Writer projections or verification attestations must be refreshed.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

from rka.services.base import BaseService
from rka.services.manuscript_native import ManuscriptNotFoundError


CHANGE_CURSOR_SCHEMA_VERSION = "rka-change-cursor/v1"
MANUSCRIPT_IMPACT_SCHEMA_VERSION = "rka-manuscript-impact/v1"
_DEFAULT_LIMIT = 100
_MAX_LIMIT = 1000
_NATIVE_ENTITY_TYPES = {
    "manuscript",
    "manuscript_claim",
    "manuscript_claim_ratification",
    "manuscript_unit",
    "manuscript_checkpoint",
    "manuscript_claim_verification",
    "manuscript_reference",
    "manuscript_planning_branch",
    "manuscript_planning_artifact",
    "manuscript_planning_artifact_version",
    "semantic_patch_proposal",
}


def _validate_window(cursor: int, limit: int) -> None:
    if isinstance(cursor, bool) or not isinstance(cursor, int) or cursor < 0:
        raise ValueError("cursor must be a non-negative integer")
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValueError("limit must be an integer")
    if not 1 <= limit <= _MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {_MAX_LIMIT}")


def _parse_details(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return dict(parsed) if isinstance(parsed, Mapping) else {}


def _chunks(values: Iterable[str], size: int = 250) -> Iterable[list[str]]:
    ordered = sorted(set(values))
    for start in range(0, len(ordered), size):
        yield ordered[start : start + size]


def _add_reason(
    target: dict[str, dict[str, set[Any]]],
    entity_id: str,
    *,
    cursor: int,
    reason: str,
    evidence_claim_ids: Iterable[str] = (),
) -> None:
    entry = target.setdefault(
        entity_id,
        {
            "change_cursors": set(),
            "reasons": set(),
            "evidence_claim_ids": set(),
        },
    )
    entry["change_cursors"].add(cursor)
    entry["reasons"].add(reason)
    entry["evidence_claim_ids"].update(evidence_claim_ids)


class ChangeTrackingService(BaseService):
    """Read the project-scoped semantic ledger and compute Writer impact."""

    async def changes_since(
        self,
        cursor: int = 0,
        *,
        limit: int = _DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        """Return one deterministic page strictly after ``cursor``.

        Cursors are globally monotonic but results are project scoped.  The
        returned ``next_cursor`` is the final delivered row, so callers neither
        skip same-project events nor need to know about other projects.
        """
        _validate_window(cursor, limit)
        async with self.db.transaction(write=False):
            rows = await self.db.fetchall(
                """SELECT cursor, project_id, source_table, operation,
                          entity_type, entity_id, manuscript_id,
                          manuscript_claim_id, manuscript_unit_id,
                          related_entity_type, related_entity_id, details,
                          changed_at
                   FROM change_events
                   WHERE project_id = ? AND cursor > ?
                   ORDER BY cursor ASC
                   LIMIT ?""",
                [self.project_id, cursor, limit + 1],
            )
            latest = await self.db.fetchone(
                """SELECT COALESCE(MAX(cursor), 0) AS cursor
                   FROM change_events WHERE project_id = ?""",
                [self.project_id],
            )
        has_more = len(rows) > limit
        delivered = rows[:limit]
        changes = []
        for raw in delivered:
            row = dict(raw)
            row["cursor"] = int(row["cursor"])
            row["details"] = _parse_details(row.get("details"))
            changes.append(row)
        next_cursor = changes[-1]["cursor"] if changes else cursor
        return {
            "schema_version": CHANGE_CURSOR_SCHEMA_VERSION,
            "project_id": self.project_id,
            "from_cursor": cursor,
            "next_cursor": next_cursor,
            "latest_cursor": int(latest["cursor"]) if latest else 0,
            "has_more": has_more,
            "changes": changes,
        }

    async def get_manuscript_impact(
        self,
        manuscript_id: str,
        *,
        since_cursor: int = 0,
        limit: int = _DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        """Map changed RKA dependencies to manuscript claims and file units.

        The page boundary is the same as :meth:`changes_since`.  A caller must
        continue while ``has_more`` is true even when one page contains no
        relevant changes, because unrelated project entities may share the
        project-scoped ledger.
        """
        _validate_window(since_cursor, limit)
        manuscript = await self.db.fetchone(
            """SELECT *
               FROM manuscripts
               WHERE project_id = ?
                 AND (id = ? OR legacy_journal_id = ?)
               LIMIT 1""",
            [self.project_id, manuscript_id, manuscript_id],
        )
        if manuscript is None:
            raise ManuscriptNotFoundError(
                f"manuscript {manuscript_id!r} not found"
            )
        canonical_id = str(manuscript["id"])

        page = await self.changes_since(since_cursor, limit=limit)
        changes = page["changes"]
        topology = await self._load_manuscript_topology(canonical_id)
        endpoint_sets = [self._event_endpoints(event) for event in changes]
        await self._expand_graph_endpoints(endpoint_sets)

        journal_claims = await self._claims_for_journal_endpoints(endpoint_sets)
        cluster_claims = await self._claims_for_cluster_endpoints(endpoint_sets)
        decision_claims, decision_units, manuscript_wide_decisions = (
            await self._decision_impacts(canonical_id, endpoint_sets)
        )

        claim_impacts: dict[str, dict[str, set[Any]]] = {}
        unit_impacts: dict[str, dict[str, set[Any]]] = {}
        changed_evidence_claims: set[str] = set()
        changed_sources: set[tuple[str, str]] = set()
        native_entities: list[dict[str, Any]] = []
        relevant_changes: list[dict[str, Any]] = []

        for event, endpoints in zip(changes, endpoint_sets):
            event_cursor = int(event["cursor"])
            reason = f"{event['source_table']}:{event['operation']}"
            event_changed_sources: set[tuple[str, str]] = set()
            core_claims = {
                entity_id
                for entity_type, entity_id in endpoints
                if entity_type == "claim"
            }
            for entity_type, entity_id in endpoints:
                if entity_type == "journal":
                    core_claims.update(journal_claims.get(entity_id, ()))
                elif entity_type == "cluster":
                    core_claims.update(cluster_claims.get(entity_id, ()))
                if entity_type not in _NATIVE_ENTITY_TYPES:
                    event_changed_sources.add((entity_type, entity_id))

            affected_claim_ids: set[str] = set()
            affected_unit_ids: set[str] = set()
            bound_core_claims: set[str] = set()
            manuscript_wide = False

            for core_claim_id in core_claims:
                direct_claims = topology["evidence_to_claims"].get(
                    core_claim_id, set()
                )
                direct_units = topology["evidence_to_units"].get(
                    core_claim_id, set()
                )
                if direct_claims or direct_units:
                    bound_core_claims.add(core_claim_id)
                affected_claim_ids.update(direct_claims)
                affected_unit_ids.update(direct_units)

            if any(
                entity_type == "literature"
                and entity_id in topology["reference_literature_ids"]
                for entity_type, entity_id in endpoints
            ):
                # Current reference membership is a manuscript-wide
                # dependency. Literature metadata/status changes can stale the
                # validation attestation and the reference-set checkpoint even
                # though the event itself carries no manuscript_id.
                manuscript_wide = True

            # Native rows carry exact aggregate identity even after a binding
            # was deleted and can no longer be found in the current topology.
            if event.get("manuscript_id") == canonical_id:
                native_entities.append(
                    {
                        "cursor": event_cursor,
                        "source_table": event["source_table"],
                        "operation": event["operation"],
                        "entity_type": event["entity_type"],
                        "entity_id": event["entity_id"],
                    }
                )
                if event.get("manuscript_claim_id"):
                    affected_claim_ids.add(event["manuscript_claim_id"])
                if event.get("manuscript_unit_id"):
                    affected_unit_ids.add(event["manuscript_unit_id"])
                if event["entity_type"] in {
                    "manuscript",
                    "manuscript_reference",
                }:
                    manuscript_wide = True
                if (
                    event["entity_type"] == "manuscript_checkpoint"
                    and not event.get("manuscript_unit_id")
                ):
                    manuscript_wide = True

            # Reference validation is manuscript-wide.  New attestations carry
            # the canonical aggregate identity; migrated historical rows may
            # still be discoverable only through the exact legacy alias.
            if (
                event["source_table"] == "reference_validation_attestations"
                and (
                    event.get("manuscript_id") == canonical_id
                    or (
                        manuscript.get("legacy_journal_id")
                        and (
                            "journal",
                            str(manuscript["legacy_journal_id"]),
                        )
                        in endpoints
                    )
                )
            ):
                manuscript_wide = True

            for entity_type, entity_id in endpoints:
                if entity_type != "decision":
                    continue
                affected_claim_ids.update(decision_claims.get(entity_id, set()))
                affected_unit_ids.update(decision_units.get(entity_id, set()))
                if entity_id in manuscript_wide_decisions:
                    manuscript_wide = True

            if manuscript_wide:
                affected_claim_ids.update(topology["active_claim_ids"])
                affected_unit_ids.update(topology["active_unit_ids"])

            # Claim/unit adjacency makes file impact explicit in both
            # directions: evidence changes on a claim identify its units, and
            # a unit edit identifies the manuscript claims it can alter.
            for claim_id in tuple(affected_claim_ids):
                affected_unit_ids.update(
                    topology["claim_to_units"].get(claim_id, set())
                )
            for unit_id in tuple(affected_unit_ids):
                affected_claim_ids.update(
                    topology["unit_to_claims"].get(unit_id, set())
                )

            if not (
                affected_claim_ids
                or affected_unit_ids
                or manuscript_wide
                or bound_core_claims
            ):
                continue

            changed_sources.update(event_changed_sources)
            changed_evidence_claims.update(bound_core_claims)
            for core_claim_id in bound_core_claims:
                source_id = topology["claim_sources"].get(core_claim_id)
                if source_id:
                    changed_sources.add(("journal", source_id))

            for claim_id in affected_claim_ids:
                _add_reason(
                    claim_impacts,
                    claim_id,
                    cursor=event_cursor,
                    reason=reason,
                    evidence_claim_ids=bound_core_claims,
                )
            for unit_id in affected_unit_ids:
                _add_reason(
                    unit_impacts,
                    unit_id,
                    cursor=event_cursor,
                    reason=reason,
                    evidence_claim_ids=bound_core_claims,
                )
            relevant_changes.append(
                {
                    "cursor": event_cursor,
                    "source_table": event["source_table"],
                    "operation": event["operation"],
                    "entity_type": event["entity_type"],
                    "entity_id": event["entity_id"],
                    "manuscript_wide": manuscript_wide,
                    "evidence_claim_ids": sorted(bound_core_claims),
                    "affected_manuscript_claim_ids": sorted(affected_claim_ids),
                    "affected_unit_ids": sorted(affected_unit_ids),
                }
            )

        claims = [
            self._serialize_claim_impact(
                claim_id,
                impact,
                topology["claims"].get(claim_id),
            )
            for claim_id, impact in sorted(claim_impacts.items())
        ]
        units = [
            self._serialize_unit_impact(
                unit_id,
                impact,
                topology["units"].get(unit_id),
            )
            for unit_id, impact in sorted(unit_impacts.items())
        ]
        file_locations = sorted(
            {
                item["location"]
                for item in units
                if isinstance(item.get("location"), str)
                and item["location"].strip()
            }
        )
        artifact_refs = sorted(
            {
                item["artifact_ref"]
                for item in units
                if isinstance(item.get("artifact_ref"), str)
                and item["artifact_ref"].strip()
            }
        )

        if page["has_more"]:
            impact_state = "partial"
        elif relevant_changes:
            impact_state = "relevant_changes"
        else:
            impact_state = "no_relevant_changes"
        return {
            "schema_version": MANUSCRIPT_IMPACT_SCHEMA_VERSION,
            "project_id": self.project_id,
            "manuscript_id": canonical_id,
            "requested_manuscript_id": manuscript_id,
            "from_cursor": since_cursor,
            "next_cursor": page["next_cursor"],
            "latest_cursor": page["latest_cursor"],
            "has_more": page["has_more"],
            "impact_state": impact_state,
            "relevant_changes": relevant_changes,
            "changed_evidence_claim_ids": sorted(changed_evidence_claims),
            "changed_sources": [
                {"entity_type": entity_type, "entity_id": entity_id}
                for entity_type, entity_id in sorted(changed_sources)
            ],
            "changed_native_entities": native_entities,
            "affected_manuscript_claims": claims,
            "affected_units": units,
            "file_locations": file_locations,
            "artifact_refs": artifact_refs,
        }

    async def _load_manuscript_topology(
        self, manuscript_id: str
    ) -> dict[str, Any]:
        claim_rows = await self.db.fetchall(
            """SELECT c.id, c.local_key, c.kind, c.state,
                      v.version, v.exact_wording
               FROM manuscript_claims AS c
               LEFT JOIN manuscript_claim_versions AS v
                 ON v.claim_id = c.id
                AND v.version = (
                    SELECT MAX(v2.version)
                    FROM manuscript_claim_versions AS v2
                    WHERE v2.claim_id = c.id
                )
               WHERE c.manuscript_id = ? AND c.project_id = ?
               ORDER BY c.local_key, c.id""",
            [manuscript_id, self.project_id],
        )
        unit_rows = await self.db.fetchall(
            """SELECT id, local_key, kind, location, artifact_ref, status,
                      sequence
               FROM manuscript_units
               WHERE manuscript_id = ? AND project_id = ?
               ORDER BY sequence, local_key, id""",
            [manuscript_id, self.project_id],
        )
        claim_unit_rows = await self.db.fetchall(
            """SELECT cu.manuscript_claim_id, cu.unit_id
               FROM manuscript_claim_units AS cu
               WHERE cu.manuscript_id = ? AND cu.project_id = ?
                 AND cu.claim_version = (
                     SELECT MAX(v.version)
                     FROM manuscript_claim_versions AS v
                     WHERE v.claim_id = cu.manuscript_claim_id
                 )""",
            [manuscript_id, self.project_id],
        )
        claim_evidence_rows = await self.db.fetchall(
            """SELECT ce.manuscript_claim_id, ce.evidence_claim_id
               FROM manuscript_claim_evidence AS ce
               WHERE ce.manuscript_id = ? AND ce.project_id = ?
                 AND ce.claim_version = (
                     SELECT MAX(v.version)
                     FROM manuscript_claim_versions AS v
                     WHERE v.claim_id = ce.manuscript_claim_id
                 )""",
            [manuscript_id, self.project_id],
        )
        unit_evidence_rows = await self.db.fetchall(
            """SELECT unit_id, evidence_claim_id
               FROM manuscript_unit_evidence
               WHERE manuscript_id = ? AND project_id = ?""",
            [manuscript_id, self.project_id],
        )
        reference_rows = await self.db.fetchall(
            """SELECT literature_id
               FROM manuscript_reference_members
               WHERE manuscript_id = ? AND project_id = ?
                 AND state = 'active'""",
            [manuscript_id, self.project_id],
        )

        claim_to_units: dict[str, set[str]] = defaultdict(set)
        unit_to_claims: dict[str, set[str]] = defaultdict(set)
        for row in claim_unit_rows:
            claim_to_units[row["manuscript_claim_id"]].add(row["unit_id"])
            unit_to_claims[row["unit_id"]].add(row["manuscript_claim_id"])

        evidence_to_claims: dict[str, set[str]] = defaultdict(set)
        evidence_to_units: dict[str, set[str]] = defaultdict(set)
        for row in claim_evidence_rows:
            evidence_to_claims[row["evidence_claim_id"]].add(
                row["manuscript_claim_id"]
            )
        for row in unit_evidence_rows:
            evidence_to_units[row["evidence_claim_id"]].add(row["unit_id"])

        evidence_ids = set(evidence_to_claims) | set(evidence_to_units)
        claim_sources: dict[str, str] = {}
        for batch in _chunks(evidence_ids):
            placeholders = ", ".join("?" for _ in batch)
            rows = await self.db.fetchall(
                f"""SELECT id, source_entry_id
                    FROM claims
                    WHERE project_id = ? AND id IN ({placeholders})""",
                [self.project_id, *batch],
            )
            claim_sources.update(
                {row["id"]: row["source_entry_id"] for row in rows}
            )

        return {
            "claims": {row["id"]: row for row in claim_rows},
            "units": {row["id"]: row for row in unit_rows},
            "active_claim_ids": {
                row["id"] for row in claim_rows if row["state"] != "retired"
            },
            "active_unit_ids": {
                row["id"] for row in unit_rows if row["status"] != "removed"
            },
            "claim_to_units": claim_to_units,
            "unit_to_claims": unit_to_claims,
            "evidence_to_claims": evidence_to_claims,
            "evidence_to_units": evidence_to_units,
            "claim_sources": claim_sources,
            "reference_literature_ids": {
                row["literature_id"] for row in reference_rows
            },
        }

    @staticmethod
    def _event_endpoints(event: Mapping[str, Any]) -> set[tuple[str, str]]:
        endpoints: set[tuple[str, str]] = set()

        def add(entity_type: Any, entity_id: Any) -> None:
            if isinstance(entity_type, str) and isinstance(entity_id, str):
                if entity_type and entity_id:
                    endpoints.add((entity_type, entity_id))

        add(event.get("entity_type"), event.get("entity_id"))
        add(event.get("related_entity_type"), event.get("related_entity_id"))
        details = _parse_details(event.get("details"))
        add(details.get("previous_source_type"), details.get("previous_source_id"))
        add(details.get("previous_target_type"), details.get("previous_target_id"))
        add("claim", details.get("previous_source_claim_id"))
        add("claim", details.get("previous_target_claim_id"))
        add("cluster", details.get("previous_cluster_id"))
        add("claim", details.get("previous_evidence_claim_id"))
        add("literature", details.get("literature_id"))
        return endpoints

    async def _expand_graph_endpoints(
        self, endpoint_sets: list[set[tuple[str, str]]]
    ) -> None:
        endpoint_to_pages: dict[tuple[str, str], set[int]] = defaultdict(set)
        for index, endpoints in enumerate(endpoint_sets):
            for endpoint in endpoints:
                endpoint_to_pages[endpoint].add(index)
        entity_ids = {entity_id for _, entity_id in endpoint_to_pages}
        for batch in _chunks(entity_ids):
            placeholders = ", ".join("?" for _ in batch)
            rows = await self.db.fetchall(
                f"""SELECT source_type, source_id, target_type, target_id
                    FROM entity_links
                    WHERE project_id = ?
                      AND (
                          source_id IN ({placeholders})
                          OR target_id IN ({placeholders})
                      )""",
                [self.project_id, *batch, *batch],
            )
            for row in rows:
                source = (row["source_type"], row["source_id"])
                target = (row["target_type"], row["target_id"])
                for index in endpoint_to_pages.get(source, set()):
                    endpoint_sets[index].add(target)
                for index in endpoint_to_pages.get(target, set()):
                    endpoint_sets[index].add(source)

        # Experiment evidence uses a reviewed relation table rather than a
        # generic graph edge so revocation can remain auditable without a
        # stale active edge. Expand run -> observation -> active canonical
        # claim explicitly for manuscript impact.
        run_to_pages: dict[str, set[int]] = defaultdict(set)
        observation_to_pages: dict[str, set[int]] = defaultdict(set)
        for index, endpoints in enumerate(endpoint_sets):
            for entity_type, entity_id in endpoints:
                if entity_type == "experiment_run":
                    run_to_pages[entity_id].add(index)
                elif entity_type == "experiment_observation":
                    observation_to_pages[entity_id].add(index)

        for batch in _chunks(run_to_pages):
            placeholders = ", ".join("?" for _ in batch)
            rows = await self.db.fetchall(
                f"""SELECT id, run_id FROM experiment_observations
                    WHERE project_id = ? AND run_id IN ({placeholders})""",
                [self.project_id, *batch],
            )
            for row in rows:
                for index in run_to_pages.get(row["run_id"], set()):
                    endpoint_sets[index].add(("experiment_observation", row["id"]))
                    observation_to_pages[row["id"]].add(index)

        for batch in _chunks(observation_to_pages):
            placeholders = ", ".join("?" for _ in batch)
            rows = await self.db.fetchall(
                f"""SELECT observation_id, claim_id
                    FROM claim_evidence_relations
                    WHERE project_id = ? AND status = 'active'
                      AND observation_id IN ({placeholders})""",
                [self.project_id, *batch],
            )
            for row in rows:
                for index in observation_to_pages.get(row["observation_id"], set()):
                    endpoint_sets[index].add(("claim", row["claim_id"]))

    async def _claims_for_journal_endpoints(
        self, endpoint_sets: list[set[tuple[str, str]]]
    ) -> dict[str, set[str]]:
        journal_ids = {
            entity_id
            for endpoints in endpoint_sets
            for entity_type, entity_id in endpoints
            if entity_type == "journal"
        }
        result: dict[str, set[str]] = defaultdict(set)
        for batch in _chunks(journal_ids):
            placeholders = ", ".join("?" for _ in batch)
            rows = await self.db.fetchall(
                f"""SELECT id, source_entry_id
                    FROM claims
                    WHERE project_id = ?
                      AND source_entry_id IN ({placeholders})""",
                [self.project_id, *batch],
            )
            for row in rows:
                result[row["source_entry_id"]].add(row["id"])
        return result

    async def _claims_for_cluster_endpoints(
        self, endpoint_sets: list[set[tuple[str, str]]]
    ) -> dict[str, set[str]]:
        cluster_ids = {
            entity_id
            for endpoints in endpoint_sets
            for entity_type, entity_id in endpoints
            if entity_type == "cluster"
        }
        result: dict[str, set[str]] = defaultdict(set)
        for batch in _chunks(cluster_ids):
            placeholders = ", ".join("?" for _ in batch)
            rows = await self.db.fetchall(
                f"""SELECT cluster_id, source_claim_id, target_claim_id
                    FROM claim_edges
                    WHERE project_id = ?
                      AND cluster_id IN ({placeholders})""",
                [self.project_id, *batch],
            )
            for row in rows:
                result[row["cluster_id"]].add(row["source_claim_id"])
                if row.get("target_claim_id"):
                    result[row["cluster_id"]].add(row["target_claim_id"])
        return result

    async def _decision_impacts(
        self,
        manuscript_id: str,
        endpoint_sets: list[set[tuple[str, str]]],
    ) -> tuple[dict[str, set[str]], dict[str, set[str]], set[str]]:
        decision_ids = {
            entity_id
            for endpoints in endpoint_sets
            for entity_type, entity_id in endpoints
            if entity_type == "decision"
        }
        claim_impacts: dict[str, set[str]] = defaultdict(set)
        unit_impacts: dict[str, set[str]] = defaultdict(set)
        manuscript_wide: set[str] = set()
        for batch in _chunks(decision_ids):
            placeholders = ", ".join("?" for _ in batch)
            ratifications = await self.db.fetchall(
                f"""SELECT decision_id, claim_id
                    FROM manuscript_claim_ratifications
                    WHERE project_id = ? AND manuscript_id = ?
                      AND decision_id IN ({placeholders})""",
                [self.project_id, manuscript_id, *batch],
            )
            for row in ratifications:
                claim_impacts[row["decision_id"]].add(row["claim_id"])

            checkpoints = await self.db.fetchall(
                f"""SELECT decision_id, unit_id
                    FROM manuscript_checkpoints
                    WHERE project_id = ? AND manuscript_id = ?
                      AND decision_id IN ({placeholders})""",
                [self.project_id, manuscript_id, *batch],
            )
            for row in checkpoints:
                if row.get("unit_id"):
                    unit_impacts[row["decision_id"]].add(row["unit_id"])
                else:
                    manuscript_wide.add(row["decision_id"])
        return claim_impacts, unit_impacts, manuscript_wide

    @staticmethod
    def _serialize_claim_impact(
        claim_id: str,
        impact: Mapping[str, set[Any]],
        row: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        result = {
            "id": claim_id,
            "change_cursors": sorted(impact["change_cursors"]),
            "reasons": sorted(impact["reasons"]),
            "evidence_claim_ids": sorted(impact["evidence_claim_ids"]),
        }
        if row:
            result.update(
                {
                    "local_key": row.get("local_key"),
                    "kind": row.get("kind"),
                    "state": row.get("state"),
                    "current_version": row.get("version"),
                    "exact_wording": row.get("exact_wording"),
                }
            )
        return result

    @staticmethod
    def _serialize_unit_impact(
        unit_id: str,
        impact: Mapping[str, set[Any]],
        row: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        result = {
            "id": unit_id,
            "change_cursors": sorted(impact["change_cursors"]),
            "reasons": sorted(impact["reasons"]),
            "evidence_claim_ids": sorted(impact["evidence_claim_ids"]),
        }
        if row:
            result.update(
                {
                    "local_key": row.get("local_key"),
                    "kind": row.get("kind"),
                    "status": row.get("status"),
                    "location": row.get("location"),
                    "artifact_ref": row.get("artifact_ref"),
                }
            )
        return result
