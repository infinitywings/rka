"""Native manuscript aggregate and server-authoritative argument spine.

The native manuscript model makes RKA authoritative for manuscript identity,
claim wording versions, evidence roles, PI ratifications, units, checkpoints,
and verification attestations.  Writer files remain projections of this
aggregate; they are not an independent semantic store.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from rka.infra.ids import generate_id
from rka.models.manuscript_native import (
    Manuscript,
    ManuscriptCheckpoint,
    ManuscriptCheckpointCreate,
    ManuscriptCheckpointResolve,
    ManuscriptClaimRatification,
    ManuscriptClaimVerificationAttestation,
    ManuscriptClaimVerificationAttestationCreate,
    ManuscriptCreate,
    ManuscriptReferenceManifestReplace,
    ManuscriptUpdate,
)
from rka.services.base import BaseService, _now


def _normalized_reference_doi(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().casefold()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :].strip()
            break
    return normalized or None


def _normalized_reference_title(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split()).casefold()
    return normalized or None


def _timestamp_is_strictly_after(later: Any, earlier: Any) -> bool:
    """Compare ISO timestamps chronologically and fail closed on ambiguity."""

    def parse(value: Any) -> datetime | None:
        if not isinstance(value, str) or not value.strip():
            return None
        normalized = value.strip()
        if normalized.endswith("Z"):
            normalized = f"{normalized[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    parsed_later = parse(later)
    parsed_earlier = parse(earlier)
    return bool(
        parsed_later is not None
        and parsed_earlier is not None
        and parsed_later > parsed_earlier
    )


def _validation_identity_matches_literature(
    *,
    input_doi: Any,
    input_title: Any,
    literature_doi: Any,
    literature_title: Any,
) -> bool:
    expected_doi = _normalized_reference_doi(literature_doi)
    actual_doi = _normalized_reference_doi(input_doi)
    expected_title = _normalized_reference_title(literature_title)
    actual_title = _normalized_reference_title(input_title)
    if expected_doi is not None and actual_doi != expected_doi:
        return False
    if expected_doi is None and actual_title != expected_title:
        return False
    if actual_title is not None and actual_title != expected_title:
        return False
    return True


class ManuscriptRevisionConflict(ValueError):
    """Raised when an optimistic manuscript revision no longer matches."""


class ManuscriptNotFoundError(ValueError):
    """Raised when a manuscript is absent from the active project scope."""


class ManuscriptCheckpointNotFoundError(ManuscriptNotFoundError):
    """Raised when a native checkpoint is absent from the active project."""


class NativeManuscriptService(BaseService):
    """Transactional service for the native ``man_`` manuscript aggregate."""

    _READY_EVIDENCE_STATUSES = {"supported", "partially_supported"}
    _INACTIVE_SOURCE_STATUSES = {"superseded", "retracted"}
    _PHASE_ORDER = ("planning", "drafting", "review", "final", "submitted")
    _CHECKPOINTS_BY_TARGET = {
        "planning": (),
        "drafting": ("venue", "outline"),
        "review": ("venue", "outline", "table_figure_plan", "reference_set"),
        "final": (
            "venue",
            "outline",
            "table_figure_plan",
            "reference_set",
            "draft_section",
        ),
        "submitted": (
            "venue",
            "outline",
            "table_figure_plan",
            "reference_set",
            "draft_section",
            "final_layout",
        ),
    }

    async def resolve_id(self, manuscript_id: str) -> str | None:
        """Resolve a canonical ``man_`` id or a legacy ``jrn_`` alias."""
        if manuscript_id.startswith("man_"):
            row = await self.db.fetchone(
                "SELECT id FROM manuscripts WHERE id = ? AND project_id = ?",
                [manuscript_id, self.project_id],
            )
        elif manuscript_id.startswith("jrn_"):
            row = await self.db.fetchone(
                """SELECT id FROM manuscripts
                   WHERE legacy_journal_id = ? AND project_id = ?""",
                [manuscript_id, self.project_id],
            )
        else:
            return None
        return str(row["id"]) if row else None

    async def create(
        self,
        data: ManuscriptCreate,
        *,
        actor: str = "executor",
    ) -> Manuscript:
        """Create one native manuscript; never infer legacy ratifications."""
        self._validate_actor(actor)
        manuscript_id = generate_id("manuscript")
        async with self.db.transaction():
            if data.legacy_journal_id is not None:
                legacy = await self.db.fetchone(
                    """SELECT j.id
                       FROM journal AS j
                       JOIN tags AS t
                         ON t.entity_type = 'journal'
                        AND t.entity_id = j.id
                        AND t.project_id = j.project_id
                        AND lower(t.tag) = 'manuscript'
                       WHERE j.id = ? AND j.project_id = ?""",
                    [data.legacy_journal_id, self.project_id],
                )
                if legacy is None:
                    raise ValueError(
                        f"legacy manuscript {data.legacy_journal_id!r} is not "
                        f"a same-project journal tagged manuscript"
                    )

            await self.db.execute(
                """INSERT INTO manuscripts
                   (id, project_id, title, abstract, venue, phase, state,
                    workspace_ref, legacy_journal_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    manuscript_id,
                    self.project_id,
                    data.title,
                    data.abstract,
                    data.venue,
                    data.phase,
                    data.state,
                    data.workspace_ref,
                    data.legacy_journal_id,
                ],
            )
            await self.audit(
                "create",
                "manuscript",
                manuscript_id,
                actor,
                {"native": True, "legacy_journal_id": data.legacy_journal_id},
            )
            created = await self.get(manuscript_id)
            if created is None:  # pragma: no cover - guards impossible DB drift
                raise RuntimeError("native manuscript insert was not readable")
            return created

    async def get(self, manuscript_id: str) -> Manuscript | None:
        canonical_id = await self.resolve_id(manuscript_id)
        if canonical_id is None:
            return None
        row = await self.db.fetchone(
            "SELECT * FROM manuscripts WHERE id = ? AND project_id = ?",
            [canonical_id, self.project_id],
        )
        return Manuscript.model_validate(row) if row else None

    async def update(
        self,
        manuscript_id: str,
        data: ManuscriptUpdate,
        *,
        actor: str = "executor",
        allow_lifecycle: bool = False,
    ) -> Manuscript:
        """Update manuscript metadata with optimistic concurrency."""
        self._validate_actor(actor)
        lifecycle_fields = {"phase", "state"} & data.model_fields_set
        if lifecycle_fields and not allow_lifecycle:
            raise ValueError(
                "phase and state are lifecycle fields; use transition_phase"
            )
        canonical_id = await self._require_id(manuscript_id)
        updates = data.model_dump(
            exclude={"expected_revision"},
            exclude_unset=True,
        )
        updates["updated_at"] = _now()
        set_clause = ", ".join(f"{field} = ?" for field in updates)
        async with self.db.transaction():
            cursor = await self.db.execute(
                f"""UPDATE manuscripts
                    SET {set_clause}, revision = revision + 1
                    WHERE id = ? AND project_id = ? AND revision = ?""",
                [
                    *updates.values(),
                    canonical_id,
                    self.project_id,
                    data.expected_revision,
                ],
            )
            if cursor.rowcount != 1:
                await self._raise_revision_conflict(
                    canonical_id, data.expected_revision
                )
            if "venue" in updates:
                await self._invalidate_resolved_checkpoints(
                    canonical_id,
                    kinds=set(self._CHECKPOINTS_BY_TARGET["submitted"]),
                )
            elif {"title", "abstract"} & updates.keys():
                await self._invalidate_resolved_checkpoints(
                    canonical_id,
                    kinds={"final_layout"},
                )
            await self.audit(
                "update",
                "manuscript",
                canonical_id,
                actor,
                {"fields": sorted(updates), "expected_revision": data.expected_revision},
            )
            updated = await self.get(canonical_id)
            if updated is None:  # pragma: no cover
                raise RuntimeError("updated manuscript disappeared")
            return updated

    async def transition_phase(
        self,
        manuscript_id: str,
        *,
        expected_revision: int,
        target_phase: str,
        target_state: str | None = None,
        actor: str = "executor",
    ) -> Manuscript:
        """Advance lifecycle only when the target phase is mechanically ready."""
        async with self.db.transaction():
            current = await self.get(manuscript_id)
            if current is None:
                raise ManuscriptNotFoundError(
                    f"manuscript {manuscript_id!r} not found"
                )
            if current.phase not in self._PHASE_ORDER:
                raise ValueError(
                    f"current manuscript phase {current.phase!r} is not managed"
                )
            current_index = self._PHASE_ORDER.index(current.phase)
            target_index = (
                self._PHASE_ORDER.index(target_phase)
                if target_phase in self._PHASE_ORDER
                else -1
            )
            if target_index <= current_index:
                raise ValueError(
                    "manuscript phase transitions must advance from "
                    f"{current.phase!r}; got {target_phase!r}"
                )
            if target_phase == "submitted":
                if target_state not in {None, "submitted"}:
                    raise ValueError(
                        "transitioning to submitted may only set state='submitted'"
                    )
                target_state = "submitted"
            elif target_state not in {None, "active"}:
                raise ValueError(
                    "pre-submission phase transitions may only retain "
                    "state='active'"
                )
            readiness = await self.get_readiness(
                manuscript_id,
                target_phase=target_phase,
            )
            if not readiness["ready"]:
                codes = sorted({item["code"] for item in readiness["findings"]})
                raise ValueError(
                    f"manuscript cannot transition to {target_phase!r}: "
                    + ", ".join(codes)
                )
            payload: dict[str, Any] = {
                "expected_revision": expected_revision,
                "phase": target_phase,
            }
            if target_state is not None:
                payload["state"] = target_state
            return await self.update(
                manuscript_id,
                ManuscriptUpdate.model_validate(payload),
                actor=actor,
                allow_lifecycle=True,
            )

    async def upsert_argument_spine(
        self,
        manuscript_id: str,
        *,
        expected_revision: int,
        spine: Mapping[str, Any],
        actor: str = "executor",
    ) -> dict[str, Any]:
        """Replace the current argument-spine projection in one transaction.

        Claim wording history is append-only.  Existing identities are matched
        by stable ``local_key``.  Missing claims are retired and missing units
        are marked removed rather than deleted.  The operation never creates a
        ratification: PI decisions must be bound separately.
        """
        self._validate_actor(actor)
        canonical_id = await self._require_id(manuscript_id)
        claims = self._normalize_claim_specs(spine.get("claims"))
        units = self._normalize_unit_specs(spine.get("units"))
        self._assert_unique_local_keys(claims, "claim")
        self._assert_unique_local_keys(units, "unit")

        async with self.db.transaction():
            await self._assert_revision(canonical_id, expected_revision)
            claim_versions = await self._upsert_claims(canonical_id, claims)
            unit_ids = await self._upsert_units(canonical_id, units)
            await self._replace_claim_unit_bindings(
                canonical_id,
                claims,
                claim_versions=claim_versions,
                unit_ids=unit_ids,
            )
            await self._invalidate_resolved_checkpoints(
                canonical_id,
                kinds={
                    "outline",
                    "table_figure_plan",
                    "reference_set",
                    "draft_section",
                    "final_layout",
                },
            )
            await self._bump_revision(canonical_id, expected_revision)
            await self.audit(
                "update",
                "manuscript",
                canonical_id,
                actor,
                {
                    "action": "upsert_argument_spine",
                    "claim_count": len(claims),
                    "unit_count": len(units),
                    "expected_revision": expected_revision,
                },
            )
            return await self.get_context(canonical_id)

    async def ratify_claim(
        self,
        manuscript_id: str,
        *,
        claim_id: str | None = None,
        local_key: str | None = None,
        claim_version: int | None = None,
        decision_id: str,
        expected_revision: int,
        ratified_at: str | None = None,
        actor: str = "executor",
    ) -> ManuscriptClaimRatification:
        """Bind an exact claim version to an active same-project PI decision."""
        self._validate_actor(actor)
        canonical_id = await self._require_id(manuscript_id)
        if bool(claim_id) == bool(local_key):
            raise ValueError("provide exactly one of claim_id or local_key")
        async with self.db.transaction():
            await self._assert_revision(canonical_id, expected_revision)
            claim = await self._find_claim(
                canonical_id, claim_id=claim_id, local_key=local_key
            )
            if claim is None:
                raise ValueError("manuscript claim not found")
            version = claim_version or await self._latest_claim_version(claim["id"])
            if version is None:
                raise ValueError("manuscript claim has no wording version")

            existing = await self.db.fetchone(
                """SELECT r.id
                   FROM manuscript_claim_ratifications AS r
                   JOIN decisions AS d
                     ON d.id = r.decision_id AND d.project_id = r.project_id
                   WHERE r.claim_id = ? AND r.manuscript_id = ?
                     AND r.project_id = ? AND d.status = 'active'
                   LIMIT 1""",
                [claim["id"], canonical_id, self.project_id],
            )
            if existing is not None:
                raise ValueError(
                    "claim already has an active ratification; supersede the "
                    "existing PI decision before binding a new wording"
                )

            ratification_id = generate_id("manuscript_claim_ratification")
            timestamp = ratified_at or _now()
            await self.db.execute(
                """INSERT INTO manuscript_claim_ratifications
                   (id, manuscript_id, project_id, claim_id, claim_version,
                    decision_id, ratified_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [
                    ratification_id,
                    canonical_id,
                    self.project_id,
                    claim["id"],
                    version,
                    decision_id,
                    timestamp,
                ],
            )
            await self._bump_revision(canonical_id, expected_revision)
            await self.audit(
                "update",
                "manuscript_claim",
                claim["id"],
                actor,
                {
                    "manuscript_id": canonical_id,
                    "operation": "ratify_claim",
                    "claim_version": version,
                    "decision_id": decision_id,
                    "expected_revision": expected_revision,
                },
            )
            row = await self.db.fetchone(
                "SELECT * FROM manuscript_claim_ratifications WHERE id = ?",
                [ratification_id],
            )
            return ManuscriptClaimRatification.model_validate(row)

    async def replace_reference_manifest(
        self,
        manuscript_id: str,
        data: ManuscriptReferenceManifestReplace,
        *,
        actor: str = "executor",
    ) -> dict[str, Any]:
        """Replace the active citation-key set without rewriting its history."""
        self._validate_actor(actor)
        canonical_id = await self._require_id(manuscript_id)
        desired = {
            member.citation_key: member.literature_id for member in data.members
        }

        async with self.db.transaction():
            await self._assert_revision(canonical_id, data.expected_revision)
            literature_ids = sorted(set(desired.values()))
            found_literature: set[str] = set()
            for start in range(0, len(literature_ids), 400):
                chunk = literature_ids[start : start + 400]
                placeholders = ", ".join("?" for _ in chunk)
                rows = await self.db.fetchall(
                    f"""SELECT id FROM literature
                        WHERE project_id = ? AND id IN ({placeholders})""",
                    [self.project_id, *chunk],
                )
                found_literature.update(str(row["id"]) for row in rows)
            missing = sorted(set(literature_ids) - found_literature)
            if missing:
                # Keep the project boundary opaque: a foreign row and a missing
                # row produce the same caller-visible failure.
                raise ValueError(
                    "reference manifest contains literature that is not "
                    "available in this project"
                )

            active_rows = await self.db.fetchall(
                """SELECT id, citation_key, literature_id
                   FROM manuscript_reference_members
                   WHERE manuscript_id = ? AND project_id = ?
                     AND state = 'active'
                   ORDER BY citation_key COLLATE NOCASE, id""",
                [canonical_id, self.project_id],
            )
            active_exact = {
                (str(row["citation_key"]), str(row["literature_id"]))
                for row in active_rows
            }
            desired_exact = set(desired.items())
            changed = active_exact != desired_exact
            if changed:
                timestamp = _now()
                for row in active_rows:
                    binding = (
                        str(row["citation_key"]),
                        str(row["literature_id"]),
                    )
                    if binding in desired_exact:
                        continue
                    await self.db.execute(
                        """UPDATE manuscript_reference_members
                           SET state = 'retired', retired_at = ?, updated_at = ?
                           WHERE id = ? AND manuscript_id = ? AND project_id = ?
                             AND state = 'active'""",
                        [
                            timestamp,
                            timestamp,
                            row["id"],
                            canonical_id,
                            self.project_id,
                        ],
                    )

                for citation_key, literature_id in sorted(
                    desired_exact, key=lambda item: (item[0].casefold(), item[0])
                ):
                    if (citation_key, literature_id) in active_exact:
                        continue
                    await self.db.execute(
                        """INSERT INTO manuscript_reference_members
                           (id, manuscript_id, project_id, citation_key,
                            literature_id, state)
                           VALUES (?, ?, ?, ?, ?, 'active')""",
                        [
                            generate_id("manuscript_reference"),
                            canonical_id,
                            self.project_id,
                            citation_key,
                            literature_id,
                        ],
                    )

                await self._invalidate_resolved_checkpoints(
                    canonical_id,
                    kinds={"reference_set", "draft_section", "final_layout"},
                )
                await self._bump_revision(canonical_id, data.expected_revision)
                await self.audit(
                    "update",
                    "manuscript",
                    canonical_id,
                    actor,
                    {
                        "action": "replace_reference_manifest",
                        "active_reference_count": len(desired),
                        "expected_revision": data.expected_revision,
                    },
                )

            return await self._get_reference_manifest_snapshot(canonical_id)

    async def get_reference_manifest(
        self, manuscript_id: str
    ) -> dict[str, Any]:
        """Read the authoritative active citation set and validation currency."""
        async with self.db.transaction(write=False):
            canonical_id = await self._require_id(manuscript_id)
            return await self._get_reference_manifest_snapshot(canonical_id)

    async def _get_reference_manifest_snapshot(
        self, canonical_id: str
    ) -> dict[str, Any]:
        manuscript = await self.db.fetchone(
            """SELECT revision FROM manuscripts
               WHERE id = ? AND project_id = ?""",
            [canonical_id, self.project_id],
        )
        if manuscript is None:
            raise ManuscriptNotFoundError(
                f"manuscript {canonical_id!r} not found"
            )
        rows = await self.db.fetchall(
            """WITH ranked_validations AS (
                   SELECT rv.*,
                          row_number() OVER (
                              PARTITION BY rv.literature_id
                              ORDER BY rv.completed_at DESC,
                                       rv.created_at DESC,
                                       rv.id DESC
                          ) AS validation_rank
                   FROM reference_validation_attestations AS rv
                   WHERE rv.project_id = ?
                     AND rv.canonical_manuscript_id = ?
                     AND rv.literature_id IS NOT NULL
               )
               SELECT mr.id, mr.manuscript_id, mr.project_id,
                      mr.citation_key, mr.literature_id, mr.state,
                      mr.created_at, mr.updated_at, mr.retired_at,
                      l.title AS literature_title,
                      l.authors AS literature_authors,
                      l.year AS literature_year,
                      l.venue AS literature_venue,
                      l.doi AS literature_doi,
                      l.url AS literature_url,
                      l.status AS literature_status,
                      l.updated_at AS literature_updated_at,
                      rv.id AS validation_id,
                      rv.input_doi AS validation_input_doi,
                      rv.input_title AS validation_input_title,
                      rv.status AS validation_status,
                      rv.retraction_check_enabled,
                      rv.retraction_checked,
                      rv.sources_confirmed AS validation_sources_confirmed,
                      rv.pipeline_version AS validation_pipeline_version,
                      rv.completed_at AS validation_completed_at
               FROM manuscript_reference_members AS mr
               JOIN literature AS l
                 ON l.id = mr.literature_id
                AND l.project_id = mr.project_id
               LEFT JOIN ranked_validations AS rv
                 ON rv.literature_id = mr.literature_id
                AND rv.validation_rank = 1
               WHERE mr.manuscript_id = ? AND mr.project_id = ?
                 AND mr.state = 'active'
               ORDER BY mr.citation_key COLLATE NOCASE, mr.citation_key, mr.id""",
            [
                self.project_id,
                canonical_id,
                canonical_id,
                self.project_id,
            ],
        )
        members: list[dict[str, Any]] = []
        approved_keys: list[str] = []
        for raw in rows:
            row = dict(raw)
            validation_id = row.pop("validation_id", None)
            validation_input_doi = row.pop("validation_input_doi", None)
            validation_input_title = row.pop("validation_input_title", None)
            validation_status = row.pop("validation_status", None)
            retraction_enabled = row.pop("retraction_check_enabled", None)
            retraction_checked = row.pop("retraction_checked", None)
            sources_confirmed = self._json_loads(
                row.pop("validation_sources_confirmed", None), []
            )
            pipeline_version = row.pop("validation_pipeline_version", None)
            completed_at = row.pop("validation_completed_at", None)
            literature_updated_at = row.get("literature_updated_at")
            identity_matches = bool(
                validation_id
                and _validation_identity_matches_literature(
                    input_doi=validation_input_doi,
                    input_title=validation_input_title,
                    literature_doi=row.get("literature_doi"),
                    literature_title=row.get("literature_title"),
                )
            )
            validation_current = bool(
                validation_id
                and identity_matches
                and validation_status == "VERIFIED"
                and (
                    retraction_enabled != 1
                    or retraction_checked == 1
                )
                and row.get("literature_status") != "excluded"
                and (
                    not literature_updated_at
                    or _timestamp_is_strictly_after(
                        completed_at,
                        literature_updated_at,
                    )
                )
            )
            row["validation"] = {
                "id": validation_id,
                "input_doi": validation_input_doi,
                "input_title": validation_input_title,
                "identity_matches": identity_matches,
                "status": validation_status,
                "retraction_check_enabled": retraction_enabled,
                "retraction_checked": retraction_checked,
                "sources_confirmed": sources_confirmed,
                "pipeline_version": pipeline_version,
                "completed_at": completed_at,
                "current": validation_current,
            }
            if validation_current:
                approved_keys.append(str(row["citation_key"]))
            members.append(row)
        return {
            "schema_version": "rka.manuscript-reference-manifest/v1",
            "project_id": self.project_id,
            "manuscript_id": canonical_id,
            "manuscript_revision": int(manuscript["revision"]),
            "members": members,
            "active_citation_keys": [
                str(member["citation_key"]) for member in members
            ],
            "approved_citation_keys": approved_keys,
            "all_members_verified": bool(members)
            and len(approved_keys) == len(members),
            "authoritative_source": "rka",
        }

    async def create_checkpoint(
        self,
        data: ManuscriptCheckpointCreate,
        *,
        expected_revision: int,
        actor: str = "executor",
    ) -> ManuscriptCheckpoint:
        self._validate_actor(actor)
        canonical_id = await self._require_id(data.manuscript_id)
        checkpoint_id = generate_id("manuscript_checkpoint")
        async with self.db.transaction():
            await self._assert_revision(canonical_id, expected_revision)
            existing_head = await self.db.fetchone(
                """SELECT cp.id, cp.kind, cp.unit_id, cp.status
                   FROM manuscript_checkpoints AS cp
                   WHERE cp.manuscript_id = ? AND cp.project_id = ?
                     AND cp.kind = ?
                     AND cp.unit_id IS ?
                     AND cp.status <> 'superseded'
                     AND NOT EXISTS (
                         SELECT 1
                         FROM manuscript_checkpoints AS successor
                         WHERE successor.supersedes_id = cp.id
                           AND successor.manuscript_id = cp.manuscript_id
                           AND successor.project_id = cp.project_id
                     )
                   ORDER BY cp.created_at DESC, cp.id DESC
                   LIMIT 1""",
                [canonical_id, self.project_id, data.kind, data.unit_id],
            )
            if data.supersedes_id is None and existing_head is not None:
                raise ValueError(
                    "an active checkpoint head already exists; set "
                    "supersedes_id explicitly"
                )
            if data.supersedes_id is not None:
                prior = await self.db.fetchone(
                    """SELECT id, kind, unit_id, status
                       FROM manuscript_checkpoints
                       WHERE id = ? AND manuscript_id = ? AND project_id = ?""",
                    [data.supersedes_id, canonical_id, self.project_id],
                )
                if prior is None:
                    raise ValueError("superseded checkpoint is not in this manuscript")
                if (
                    prior["kind"] != data.kind
                    or prior.get("unit_id") != data.unit_id
                ):
                    raise ValueError(
                        "a checkpoint may supersede only the same kind and unit"
                    )
                if prior["status"] == "pending":
                    raise ValueError(
                        "a pending checkpoint must be resolved before replacement"
                    )
                if (
                    existing_head is None
                    or existing_head["id"] != data.supersedes_id
                ):
                    raise ValueError(
                        "supersedes_id must name the current checkpoint head"
                    )
                await self.db.execute(
                    """UPDATE manuscript_checkpoints
                       SET status = 'superseded'
                       WHERE id = ? AND manuscript_id = ? AND project_id = ?""",
                    [data.supersedes_id, canonical_id, self.project_id],
                )
            await self.db.execute(
                """INSERT INTO manuscript_checkpoints
                   (id, manuscript_id, project_id, kind, unit_id, supersedes_id)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [
                    checkpoint_id,
                    canonical_id,
                    self.project_id,
                    data.kind,
                    data.unit_id,
                    data.supersedes_id,
                ],
            )
            await self._bump_revision(canonical_id, expected_revision)
            await self.audit(
                "create",
                "manuscript_checkpoint",
                checkpoint_id,
                actor,
                {
                    "manuscript_id": canonical_id,
                    "kind": data.kind,
                    "unit_id": data.unit_id,
                    "expected_revision": expected_revision,
                },
            )
            row = await self.db.fetchone(
                "SELECT * FROM manuscript_checkpoints WHERE id = ?",
                [checkpoint_id],
            )
            return ManuscriptCheckpoint.model_validate(row)

    async def resolve_checkpoint(
        self,
        checkpoint_id: str,
        data: ManuscriptCheckpointResolve,
        *,
        expected_revision: int,
        actor: str = "executor",
    ) -> ManuscriptCheckpoint:
        self._validate_actor(actor)
        async with self.db.transaction():
            row = await self.db.fetchone(
                """SELECT manuscript_id, kind, unit_id
                   FROM manuscript_checkpoints
                   WHERE id = ? AND project_id = ?""",
                [checkpoint_id, self.project_id],
            )
            if row is None:
                raise ManuscriptCheckpointNotFoundError(
                    f"manuscript checkpoint {checkpoint_id!r} not found"
                )
            manuscript_id = row["manuscript_id"]
            await self._assert_revision(manuscript_id, expected_revision)
            decision = await self.db.fetchone(
                """SELECT chosen
                   FROM decisions
                   WHERE id = ? AND project_id = ?
                     AND decided_by = 'pi'
                     AND status = 'active'
                     AND phase = 'paper_writing'
                     AND length(trim(coalesce(chosen, ''))) > 0""",
                [data.decision_id, self.project_id],
            )
            if decision is None:
                raise ValueError(
                    "checkpoint resolution requires an active same-project "
                    "paper_writing PI decision with a non-empty choice"
                )
            dependency_snapshot = await self._checkpoint_dependency_snapshot(
                manuscript_id,
                kind=row["kind"],
                unit_id=row.get("unit_id"),
            )
            cursor = await self.db.execute(
                """UPDATE manuscript_checkpoints
                   SET decision_id = ?, approved_choice = ?,
                       dependency_snapshot = ?, status = ?, resolved_at = ?
                   WHERE id = ? AND manuscript_id = ? AND project_id = ?
                     AND status = 'pending'""",
                [
                    data.decision_id,
                    decision["chosen"],
                    json.dumps(dependency_snapshot, sort_keys=True),
                    data.status,
                    data.resolved_at,
                    checkpoint_id,
                    manuscript_id,
                    self.project_id,
                ],
            )
            if cursor.rowcount != 1:
                raise ValueError("checkpoint is not pending")
            await self._bump_revision(manuscript_id, expected_revision)
            await self.audit(
                "update",
                "manuscript_checkpoint",
                checkpoint_id,
                actor,
                {
                    "manuscript_id": manuscript_id,
                    "operation": "resolve_checkpoint",
                    "decision_id": data.decision_id,
                    "status": data.status,
                    "expected_revision": expected_revision,
                },
            )
            updated = await self.db.fetchone(
                "SELECT * FROM manuscript_checkpoints WHERE id = ?",
                [checkpoint_id],
            )
            return ManuscriptCheckpoint.model_validate(updated)

    async def record_verification_attestation(
        self,
        data: ManuscriptClaimVerificationAttestationCreate,
        *,
        expected_revision: int,
        actor: str = "executor",
    ) -> ManuscriptClaimVerificationAttestation:
        self._validate_actor(actor)
        canonical_id = await self._require_id(data.manuscript_id)
        attestation_id = generate_id("manuscript_verification")
        async with self.db.transaction():
            await self._assert_revision(canonical_id, expected_revision)
            await self.db.execute(
                """INSERT INTO manuscript_claim_verification_attestations
                   (id, manuscript_id, project_id, claim_id, claim_version,
                    overall_verdict, grounding_verdict, evidence_verdict,
                    contradiction_verdict, currency_verdict,
                    ratification_verdict, unit_coverage_verdict,
                    changelog_cursor, dependency_snapshot, full_json_payload,
                    validator_version, started_at, completed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    attestation_id,
                    canonical_id,
                    self.project_id,
                    data.claim_id,
                    data.claim_version,
                    data.overall_verdict,
                    data.grounding_verdict,
                    data.evidence_verdict,
                    data.contradiction_verdict,
                    data.currency_verdict,
                    data.ratification_verdict,
                    data.unit_coverage_verdict,
                    data.changelog_cursor,
                    json.dumps(data.dependency_snapshot, sort_keys=True),
                    json.dumps(data.full_json_payload, sort_keys=True),
                    data.validator_version,
                    data.started_at,
                    data.completed_at,
                ],
            )
            await self._bump_revision(canonical_id, expected_revision)
            await self.audit(
                "create",
                "manuscript_claim_verification_attestation",
                attestation_id,
                actor,
                {
                    "manuscript_id": canonical_id,
                    "claim_id": data.claim_id,
                    "claim_version": data.claim_version,
                    "expected_revision": expected_revision,
                },
            )
            row = await self.db.fetchone(
                """SELECT * FROM manuscript_claim_verification_attestations
                   WHERE id = ?""",
                [attestation_id],
            )
            return ManuscriptClaimVerificationAttestation.model_validate(row)

    async def get_context(self, manuscript_id: str) -> dict[str, Any]:
        """Return one transactionally consistent manuscript aggregate snapshot."""
        async with self.db.transaction(write=False):
            return await self._get_context_snapshot(manuscript_id)

    async def _get_context_snapshot(self, manuscript_id: str) -> dict[str, Any]:
        """Read the full current native manuscript aggregate."""
        manuscript = await self.get(manuscript_id)
        if manuscript is None:
            raise ManuscriptNotFoundError(
                f"manuscript {manuscript_id!r} not found"
            )
        canonical_id = manuscript.id

        claim_rows = await self.db.fetchall(
            """SELECT c.*, v.version, v.exact_wording, v.allowed_wording,
                      v.prohibited_wording, v.created_at AS version_created_at
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
            [canonical_id, self.project_id],
        )
        claims: list[dict[str, Any]] = []
        for row in claim_rows:
            claim = dict(row)
            claim["prohibited_wording"] = self._json_loads(
                claim.get("prohibited_wording"), []
            )
            claim["ratifications"] = await self.db.fetchall(
                """SELECT r.*, d.status AS decision_status,
                          d.decided_by, d.chosen, d.superseded_by
                   FROM manuscript_claim_ratifications AS r
                   JOIN decisions AS d
                     ON d.id = r.decision_id AND d.project_id = r.project_id
                   WHERE r.claim_id = ? AND r.project_id = ?
                   ORDER BY r.ratified_at, r.id""",
                [row["id"], self.project_id],
            )
            claim["evidence"] = await self._claim_evidence(
                canonical_id, row["id"], row.get("version")
            )
            claim["unit_links"] = await self.db.fetchall(
                """SELECT cu.*, u.local_key AS unit_local_key,
                          u.kind AS unit_kind, u.location AS unit_location
                   FROM manuscript_claim_units AS cu
                   JOIN manuscript_units AS u
                     ON u.id = cu.unit_id
                    AND u.manuscript_id = cu.manuscript_id
                    AND u.project_id = cu.project_id
                   WHERE cu.manuscript_claim_id = ?
                     AND cu.claim_version = ?
                     AND cu.project_id = ?
                   ORDER BY u.sequence, u.local_key, cu.relationship""",
                [row["id"], row.get("version"), self.project_id],
            ) if row.get("version") is not None else []
            claims.append(claim)

        unit_rows = await self.db.fetchall(
            """SELECT * FROM manuscript_units
               WHERE manuscript_id = ? AND project_id = ?
               ORDER BY sequence, local_key, id""",
            [canonical_id, self.project_id],
        )
        units: list[dict[str, Any]] = []
        for row in unit_rows:
            unit = dict(row)
            unit["evidence"] = await self._unit_evidence(canonical_id, row["id"])
            if unit.get("kind") == "result":
                unit["artifact_binding"] = await self._artifact_binding(
                    unit.get("artifact_ref")
                )
            units.append(unit)

        checkpoints = await self.db.fetchall(
            """SELECT cp.*, d.status AS decision_status,
                      d.decided_by, d.chosen, d.superseded_by
               FROM manuscript_checkpoints AS cp
               LEFT JOIN decisions AS d
                 ON d.id = cp.decision_id AND d.project_id = cp.project_id
               WHERE cp.manuscript_id = ? AND cp.project_id = ?
               ORDER BY cp.created_at, cp.id""",
            [canonical_id, self.project_id],
        )
        for checkpoint in checkpoints:
            checkpoint["dependency_snapshot"] = self._json_loads(
                checkpoint.get("dependency_snapshot"), {}
            )
            checkpoint["dependency_current"] = (
                checkpoint.get("status") in {"resolved", "rejected"}
                and checkpoint["dependency_snapshot"]
                == await self._checkpoint_dependency_snapshot(
                    canonical_id,
                    kind=checkpoint["kind"],
                    unit_id=checkpoint.get("unit_id"),
                )
            )
        verifications = await self.db.fetchall(
            """SELECT * FROM manuscript_claim_verification_attestations
               WHERE manuscript_id = ? AND project_id = ?
               ORDER BY created_at, id""",
            [canonical_id, self.project_id],
        )
        for row in verifications:
            row["dependency_snapshot"] = self._json_loads(
                row.get("dependency_snapshot"), {}
            )
            row["full_json_payload"] = self._json_loads(
                row.get("full_json_payload"), {}
            )
        reference_validations = await self.db.fetchall(
            """SELECT rv.*, l.title AS literature_title,
                      l.authors AS literature_authors,
                      l.year AS literature_year,
                      l.venue AS literature_venue,
                      l.doi AS literature_doi,
                      l.url AS literature_url,
                      l.status AS literature_status,
                      l.updated_at AS literature_updated_at
               FROM reference_validation_attestations AS rv
               LEFT JOIN literature AS l
                 ON l.id = rv.literature_id
                AND l.project_id = rv.project_id
               WHERE rv.canonical_manuscript_id = ?
                 AND rv.project_id = ?
               ORDER BY rv.completed_at, rv.id""",
            [canonical_id, self.project_id],
        )
        for row in reference_validations:
            for field, default in (
                ("input_authors", []),
                ("sources_tried", []),
                ("sources_confirmed", []),
                ("notes", []),
                ("stage_trace", {}),
                ("full_json_payload", {}),
            ):
                row[field] = self._json_loads(row.get(field), default)
        reference_manifest = await self._get_reference_manifest_snapshot(
            canonical_id
        )

        return {
            "schema_version": "rka.manuscript-context/v1",
            "project_id": self.project_id,
            "manuscript": manuscript.model_dump(),
            "claims": claims,
            "units": units,
            "checkpoints": checkpoints,
            "verification_attestations": verifications,
            "reference_validations": reference_validations,
            "reference_manifest": reference_manifest,
            "authoritative_source": "rka",
        }

    async def get_readiness(
        self,
        manuscript_id: str,
        *,
        target_phase: str = "drafting",
    ) -> dict[str, Any]:
        """Return categorical, evidence-linked readiness findings."""
        if target_phase not in self._CHECKPOINTS_BY_TARGET:
            raise ValueError(
                f"target_phase must be one of {sorted(self._CHECKPOINTS_BY_TARGET)}"
            )
        context = await self.get_context(manuscript_id)
        findings: list[dict[str, Any]] = []
        manuscript = context["manuscript"]

        def add(
            verdict: str,
            code: str,
            message: str,
            *,
            claim_id: str | None = None,
            unit_id: str | None = None,
            citation_key: str | None = None,
            literature_id: str | None = None,
        ) -> None:
            finding = {"verdict": verdict, "code": code, "message": message}
            if claim_id:
                finding["claim_id"] = claim_id
            if unit_id:
                finding["unit_id"] = unit_id
            if citation_key:
                finding["citation_key"] = citation_key
            if literature_id:
                finding["literature_id"] = literature_id
            findings.append(finding)

        if manuscript["state"] != "active":
            add(
                "BLOCK",
                "MANUSCRIPT_NOT_ACTIVE",
                f"manuscript state is {manuscript['state']!r}",
            )
        if target_phase != "planning" and not manuscript.get("venue"):
            add("BLOCK", "VENUE_REQUIRED", "target venue is not set")

        active_claims = [
            claim for claim in context["claims"] if claim.get("state") == "active"
        ]
        if not active_claims:
            add("BLOCK", "NO_ACTIVE_CLAIMS", "argument spine has no active claims")

        active_unit_ids = {
            unit["id"]
            for unit in context["units"]
            if unit.get("status") != "removed"
        }
        result_units = {
            unit["id"]: unit
            for unit in context["units"]
            if unit.get("kind") == "result" and unit.get("status") != "removed"
        }
        linked_result_units: set[str] = set()

        for claim in active_claims:
            claim_id = claim["id"]
            version = claim.get("version")
            if version is None:
                add(
                    "BLOCK",
                    "CLAIM_VERSION_REQUIRED",
                    "active claim has no wording version",
                    claim_id=claim_id,
                )
                continue

            current_ratifications = [
                ratification
                for ratification in claim.get("ratifications", [])
                if ratification.get("claim_version") == version
                and ratification.get("decision_status") == "active"
                and ratification.get("decided_by") == "pi"
                and not ratification.get("superseded_by")
                and ratification.get("chosen") == claim.get("exact_wording")
            ]
            if not current_ratifications:
                add(
                    "BLOCK",
                    "CLAIM_NOT_RATIFIED",
                    "latest exact wording lacks a current PI ratification",
                    claim_id=claim_id,
                )

            evidence = claim.get("evidence", [])
            support = [item for item in evidence if item.get("role") == "support"]
            counterevidence = [
                item
                for item in evidence
                if item.get("role") == "counterevidence"
            ]
            if counterevidence:
                add(
                    "BLOCK",
                    "COUNTEREVIDENCE_REQUIRES_DISPOSITION",
                    "active claim has explicit counterevidence; revise or bound "
                    "the claim, move the source to a qualifier, or retire it",
                    claim_id=claim_id,
                )
            if not support:
                add(
                    "BLOCK",
                    (
                        "EMPIRICAL_SUPPORT_REQUIRED"
                        if claim.get("kind") == "empirical"
                        else "CLAIM_SUPPORT_REQUIRED"
                    ),
                    "active claim has no positive support evidence",
                    claim_id=claim_id,
                )
            for item in support:
                if (
                    item.get("verified") != 1
                    or item.get("evidence_status")
                    not in self._READY_EVIDENCE_STATUSES
                    or item.get("stale") != 0
                    or item.get("contradicted") != 0
                    or item.get("source_current") != 1
                    or item.get("source_is_manuscript") != 0
                ):
                    add(
                        "BLOCK",
                        "EVIDENCE_NOT_MANUSCRIPT_READY",
                        f"support claim {item.get('evidence_claim_id')} is not "
                        "grounded, supported, current, and uncontested",
                        claim_id=claim_id,
                    )

            result_links = [
                link
                for link in claim.get("unit_links", [])
                if link.get("unit_id") in active_unit_ids
                and link.get("unit_kind") == "result"
                and link.get("relationship") in {"advances", "tests"}
            ]
            linked_result_units.update(link["unit_id"] for link in result_links)
            if claim.get("kind") == "empirical" and not result_links:
                add(
                    "BLOCK",
                    "EMPIRICAL_RESULT_UNIT_REQUIRED",
                    "empirical claim is not mapped to a result unit",
                    claim_id=claim_id,
                )

        for unit_id, unit in result_units.items():
            if unit_id not in linked_result_units:
                add(
                    "BLOCK",
                    "ORPHAN_RESULT_UNIT",
                    "result unit is not linked to an active claim",
                    unit_id=unit_id,
                )
            support = [
                item for item in unit.get("evidence", [])
                if item.get("role") == "support"
            ]
            counterevidence = [
                item
                for item in unit.get("evidence", [])
                if item.get("role") == "counterevidence"
            ]
            if counterevidence:
                add(
                    "BLOCK",
                    "RESULT_COUNTEREVIDENCE_REQUIRES_DISPOSITION",
                    "result unit has explicit counterevidence; revise its "
                    "interpretation boundary or remove the counterevidence link",
                    unit_id=unit_id,
                )
            if not support:
                add(
                    "BLOCK",
                    "RESULT_UNIT_SUPPORT_REQUIRED",
                    "result unit has no positive support evidence",
                    unit_id=unit_id,
                )
            for item in support:
                if (
                    item.get("verified") != 1
                    or item.get("evidence_status")
                    not in self._READY_EVIDENCE_STATUSES
                    or item.get("stale") != 0
                    or item.get("contradicted") != 0
                    or item.get("source_current") != 1
                    or item.get("source_is_manuscript") != 0
                ):
                    add(
                        "BLOCK",
                        "RESULT_EVIDENCE_NOT_READY",
                        f"result support claim {item.get('evidence_claim_id')} "
                        "is not grounded, supported, current, and uncontested",
                        unit_id=unit_id,
                    )
            if target_phase in {"review", "final", "submitted"}:
                binding = unit.get("artifact_binding") or {}
                if not binding.get("verified"):
                    add(
                        "BLOCK",
                        "RESULT_ARTIFACT_NOT_VERIFIED",
                        "result artifact_ref must resolve to a same-project "
                        "complete art_ or fig_ record with a content hash",
                        unit_id=unit_id,
                    )

        if target_phase in {"review", "final", "submitted"}:
            manifest = context.get("reference_manifest") or {}
            reference_members = manifest.get("members") or []
            if not reference_members:
                add(
                    "BLOCK",
                    "REFERENCE_MANIFEST_REQUIRED",
                    "review readiness requires an explicit authoritative "
                    "citation-key manifest",
                )
            for member in reference_members:
                citation_key = member.get("citation_key")
                literature_id = member.get("literature_id")
                validation = member.get("validation") or {}
                if not validation.get("id"):
                    add(
                        "BLOCK",
                        "REFERENCE_VALIDATION_MISSING",
                        "active citation has no validation attestation bound to "
                        "this manuscript and literature record",
                        citation_key=citation_key,
                        literature_id=literature_id,
                    )
                    continue
                if validation.get("status") != "VERIFIED":
                    add(
                        "BLOCK",
                        "REFERENCE_NOT_VERIFIED",
                        "the latest validation attempt for this active citation "
                        "is not VERIFIED",
                        citation_key=citation_key,
                        literature_id=literature_id,
                    )
                if validation.get("identity_matches") is not True:
                    add(
                        "BLOCK",
                        "REFERENCE_IDENTITY_MISMATCH",
                        "the latest validation input does not match the "
                        "current bound literature identity",
                        citation_key=citation_key,
                        literature_id=literature_id,
                    )
                if (
                    validation.get("retraction_check_enabled") == 1
                    and validation.get("retraction_checked") != 1
                ):
                    add(
                        "BLOCK",
                        "REFERENCE_RETRACTION_CHECK_INCOMPLETE",
                        "a requested retraction check did not complete",
                        citation_key=citation_key,
                        literature_id=literature_id,
                    )
                if member.get("literature_status") == "excluded":
                    add(
                        "BLOCK",
                        "REFERENCE_LITERATURE_EXCLUDED",
                        "active citation points to excluded literature",
                        citation_key=citation_key,
                        literature_id=literature_id,
                    )
                literature_updated = member.get("literature_updated_at")
                completed_at = validation.get("completed_at")
                if (
                    literature_updated
                    and not _timestamp_is_strictly_after(
                        completed_at,
                        literature_updated,
                    )
                ):
                    add(
                        "BLOCK",
                        "REFERENCE_VALIDATION_STALE",
                        "literature metadata changed after reference validation",
                        citation_key=citation_key,
                        literature_id=literature_id,
                    )

        required_checkpoints = self._CHECKPOINTS_BY_TARGET[target_phase]
        for checkpoint_kind in required_checkpoints:
            approved = [
                checkpoint
                for checkpoint in context["checkpoints"]
                if checkpoint.get("kind") == checkpoint_kind
                and checkpoint.get("status") == "resolved"
                and checkpoint.get("decision_status") == "active"
                and checkpoint.get("decided_by") == "pi"
                and not checkpoint.get("superseded_by")
                and checkpoint.get("chosen")
                == checkpoint.get("approved_choice")
            ]
            resolved = [
                checkpoint
                for checkpoint in approved
                if checkpoint.get("dependency_current") is True
            ]
            if checkpoint_kind == "draft_section":
                resolved_units = {
                    checkpoint.get("unit_id") for checkpoint in resolved
                }
                missing = sorted(active_unit_ids - resolved_units)
                for unit_id in missing:
                    add(
                        "BLOCK",
                        "DRAFT_CHECKPOINT_REQUIRED",
                        "active manuscript unit lacks a resolved draft checkpoint",
                        unit_id=unit_id,
                    )
                stale_units = sorted({
                    checkpoint.get("unit_id")
                    for checkpoint in approved
                    if checkpoint.get("dependency_current") is not True
                    and checkpoint.get("unit_id") in active_unit_ids
                })
                for unit_id in stale_units:
                    add(
                        "BLOCK",
                        "CHECKPOINT_STALE",
                        "draft checkpoint dependencies changed after PI approval",
                        unit_id=unit_id,
                    )
            elif approved and not resolved:
                add(
                    "BLOCK",
                    "CHECKPOINT_STALE",
                    f"checkpoint {checkpoint_kind!r} dependencies changed "
                    "after PI approval",
                )
            elif not resolved:
                add(
                    "BLOCK",
                    "CHECKPOINT_REQUIRED",
                    f"checkpoint {checkpoint_kind!r} is not currently resolved",
                )

        severity = {"PASS": 0, "WARN": 1, "BLOCK": 2, "ERROR": 3}
        verdict = max(
            (finding["verdict"] for finding in findings),
            key=lambda item: severity[item],
            default="PASS",
        )
        return {
            "schema_version": "rka.manuscript-readiness/v1",
            "project_id": self.project_id,
            "manuscript_id": context["manuscript"]["id"],
            "manuscript_revision": context["manuscript"]["revision"],
            "target_phase": target_phase,
            "verdict": verdict,
            "ready": verdict not in {"BLOCK", "ERROR"},
            "findings": findings,
        }

    async def get_writing_candidates(
        self,
        manuscript_id: str,
    ) -> dict[str, Any]:
        """Distill noisy research records into reviewable paper candidates.

        Journal entries are never promoted directly.  Candidate wording comes
        only from a Brain-reviewed, current evidence-cluster synthesis bound
        to a current research question.  Individual claims remain the
        provenance layer, and unresolved contradictions are surfaced as
        blockers rather than filtered away.
        """
        async with self.db.transaction(write=False):
            canonical_id = await self._require_id(manuscript_id)
            manuscript = await self.get(canonical_id)
            if manuscript is None:  # pragma: no cover - guarded by _require_id
                raise ManuscriptNotFoundError(
                    f"manuscript {manuscript_id!r} not found"
                )
            cluster_rows = await self.db.fetchall(
                """SELECT ec.*, rq.question AS research_question,
                          rq.status AS rq_status,
                          rq.superseded_by AS rq_superseded_by,
                          (
                              SELECT t.tag
                              FROM tags AS t
                              WHERE t.project_id = ec.project_id
                                AND t.entity_type = 'decision'
                                AND t.entity_id = ec.research_question_id
                                AND t.tag LIKE 'rq:%'
                              ORDER BY t.tag
                              LIMIT 1
                          ) AS rq_lifecycle,
                          (
                              SELECT count(*)
                              FROM review_queue AS review
                              WHERE review.project_id = ec.project_id
                                AND review.item_type = 'cluster'
                                AND review.item_id = ec.id
                                AND review.status = 'pending'
                          ) AS pending_reviews
                   FROM evidence_clusters AS ec
                   LEFT JOIN decisions AS rq
                     ON rq.id = ec.research_question_id
                    AND rq.project_id = ec.project_id
                    AND rq.kind = 'research_question'
                   WHERE ec.project_id = ?
                   ORDER BY coalesce(rq.question, ''), ec.label, ec.id""",
                [self.project_id],
            )
            membership_rows = await self.db.fetchall(
                """SELECT ce.cluster_id, c.id, c.claim_type, c.content,
                          c.confidence, c.verified, c.evidence_status,
                          c.stale, coalesce(c.staleness, 'green') AS staleness,
                          c.source_entry_id,
                          CASE
                              WHEN j.id IS NOT NULL
                               AND j.status = 'active'
                               AND j.confidence NOT IN (
                                   'superseded', 'retracted'
                               )
                               AND j.superseded_by IS NULL
                              THEN 1 ELSE 0
                          END AS source_current,
                          (
                              EXISTS (
                                  SELECT 1
                                  FROM tags AS manuscript_tag
                                  WHERE manuscript_tag.project_id = c.project_id
                                    AND manuscript_tag.entity_type = 'journal'
                                    AND manuscript_tag.entity_id =
                                        c.source_entry_id
                                    AND lower(manuscript_tag.tag) = 'manuscript'
                              )
                              OR EXISTS (
                                  SELECT 1
                                  FROM manuscripts AS source_manuscript
                                  WHERE source_manuscript.project_id =
                                        c.project_id
                                    AND source_manuscript.legacy_journal_id =
                                        c.source_entry_id
                              )
                          ) AS source_is_manuscript
                   FROM claim_edges AS ce
                   JOIN claims AS c
                     ON c.id = ce.source_claim_id
                    AND c.project_id = ce.project_id
                   LEFT JOIN journal AS j
                     ON j.id = c.source_entry_id
                    AND j.project_id = c.project_id
                   WHERE ce.project_id = ? AND ce.relation = 'member_of'
                   ORDER BY ce.cluster_id, c.content, c.id""",
                [self.project_id],
            )
            relation_rows = await self.db.fetchall(
                """SELECT cluster_id, source_claim_id, target_claim_id, relation
                   FROM claim_edges
                   WHERE project_id = ?
                     AND relation IN ('qualifies', 'contradicts')
                   ORDER BY cluster_id, relation, source_claim_id,
                            target_claim_id""",
                [self.project_id],
            )

        members: dict[str, list[dict[str, Any]]] = {}
        claim_clusters: dict[str, set[str]] = {}
        for row in membership_rows:
            members.setdefault(row["cluster_id"], []).append(row)
            claim_clusters.setdefault(row["id"], set()).add(row["cluster_id"])
        qualifiers: dict[str, set[str]] = {}
        contradictions: dict[str, set[str]] = {}
        for row in relation_rows:
            cluster_ids: set[str] = set()
            if row.get("cluster_id"):
                cluster_ids.add(row["cluster_id"])
            for field in ("source_claim_id", "target_claim_id"):
                claim_id = row.get(field)
                if claim_id:
                    cluster_ids.update(claim_clusters.get(claim_id, set()))
            for cluster_id in cluster_ids:
                if row["relation"] == "qualifies":
                    qualifiers.setdefault(cluster_id, set()).add(
                        row["source_claim_id"]
                    )
                else:
                    touched = contradictions.setdefault(cluster_id, set())
                    touched.add(row["source_claim_id"])
                    if row.get("target_claim_id"):
                        touched.add(row["target_claim_id"])

        clusters: list[dict[str, Any]] = []
        candidate_claims: list[dict[str, Any]] = []
        candidate_lineage: dict[str, dict[str, Any]] = {}
        excluded_claims: list[dict[str, Any]] = []
        for cluster in cluster_rows:
            cluster_id = cluster["id"]
            cluster_members = members.get(cluster_id, [])
            cluster_qualifiers = qualifiers.get(cluster_id, set())
            cluster_counterevidence = contradictions.get(cluster_id, set())
            ready_support: list[dict[str, Any]] = []
            for claim in cluster_members:
                reasons: list[str] = []
                if claim.get("verified") != 1:
                    reasons.append("SOURCE_GROUNDING_NOT_VERIFIED")
                if claim.get("evidence_status") not in self._READY_EVIDENCE_STATUSES:
                    reasons.append("SCIENTIFIC_SUPPORT_NOT_READY")
                if claim.get("stale") != 0 or claim.get("staleness") not in {
                    "green",
                    "dismissed",
                }:
                    reasons.append("CLAIM_NOT_CURRENT")
                if claim.get("source_current") != 1:
                    reasons.append("SOURCE_NOT_CURRENT")
                if claim.get("source_is_manuscript") != 0:
                    reasons.append("MANUSCRIPT_DERIVED")
                if claim["id"] in cluster_counterevidence:
                    reasons.append("UNRESOLVED_CONTRADICTION")
                if reasons:
                    excluded_claims.append({
                        "claim_id": claim["id"],
                        "cluster_id": cluster_id,
                        "reasons": sorted(set(reasons)),
                    })
                else:
                    ready_support.append(claim)

            normalized_groups: dict[str, list[dict[str, Any]]] = {}
            for claim in ready_support:
                normalized = " ".join(
                    str(claim.get("content") or "").casefold().split()
                )
                normalized_groups.setdefault(normalized, []).append(claim)
            representative_ids = [
                sorted(
                    group,
                    key=lambda item: (
                        -float(item.get("confidence") or 0),
                        item["id"],
                    ),
                )[0]["id"]
                for _normalized, group in sorted(normalized_groups.items())
            ]

            blockers: list[str] = []
            if not cluster.get("research_question_id") or not cluster.get(
                "research_question"
            ):
                blockers.append("RESEARCH_QUESTION_REQUIRED")
            elif (
                cluster.get("rq_status") != "active"
                or cluster.get("rq_superseded_by")
            ):
                blockers.append("RESEARCH_QUESTION_NOT_CURRENT")
            if cluster.get("synthesized_by") != "brain" or not str(
                cluster.get("synthesis") or ""
            ).strip():
                blockers.append("BRAIN_CLUSTER_REVIEW_REQUIRED")
            if cluster.get("needs_reprocessing") == 1 or cluster.get(
                "staleness"
            ) not in {"green", "dismissed"}:
                blockers.append("CLUSTER_NOT_CURRENT")
            if cluster.get("confidence") not in {"strong", "moderate"}:
                blockers.append("CLUSTER_EVIDENCE_NOT_READY")
            if int(cluster.get("pending_reviews") or 0) > 0:
                blockers.append("CLUSTER_REVIEW_ITEMS_PENDING")
            if cluster_counterevidence:
                blockers.append("UNRESOLVED_COUNTEREVIDENCE")
            if not ready_support:
                blockers.append("NO_MANUSCRIPT_READY_SUPPORT")

            disposition = "eligible" if not blockers else "needs_review"
            cluster_record = {
                "cluster_id": cluster_id,
                "research_question_id": cluster.get("research_question_id"),
                "research_question": cluster.get("research_question"),
                "rq_lifecycle": (
                    str(cluster.get("rq_lifecycle"))[3:]
                    if str(cluster.get("rq_lifecycle") or "").startswith("rq:")
                    else cluster.get("rq_status")
                ),
                "label": cluster.get("label"),
                "synthesis": cluster.get("synthesis"),
                "confidence": cluster.get("confidence"),
                "synthesized_by": cluster.get("synthesized_by"),
                "support_claim_ids": [
                    claim["id"] for claim in ready_support
                ],
                "representative_claim_ids": representative_ids,
                "qualifier_claim_ids": sorted(cluster_qualifiers),
                "counterevidence_claim_ids": sorted(cluster_counterevidence),
                "duplicate_support_groups": [
                    sorted(claim["id"] for claim in group)
                    for _normalized, group in sorted(normalized_groups.items())
                    if len(group) > 1
                ],
                "disposition": disposition,
                "blockers": sorted(set(blockers)),
            }
            clusters.append(cluster_record)
            if disposition == "eligible":
                local_key = f"C{len(candidate_claims) + 1}"
                claim_kinds = {
                    claim.get("claim_type") for claim in ready_support
                }
                claim_type = (
                    "methodological"
                    if claim_kinds and claim_kinds <= {"method"}
                    else "empirical"
                )
                candidate_claims.append({
                    "claim_id": local_key,
                    "claim_type": claim_type,
                    "status": "candidate",
                    "text": str(cluster["synthesis"]).strip(),
                    "allowed_wording": str(cluster["synthesis"]).strip(),
                    "prohibited_wording": [],
                    "ratified_by": None,
                    "evidence_ids": [
                        claim["id"] for claim in ready_support
                    ],
                    "qualifier_ids": sorted(cluster_qualifiers),
                    "counterevidence_ids": [],
                    "manuscript_units": [],
                })
                candidate_lineage[local_key] = {
                    "cluster_id": cluster_id,
                    "research_question_id": cluster.get(
                        "research_question_id"
                    ),
                    "representative_claim_ids": representative_ids,
                }

        return {
            "schema_version": "rka.writing-evidence-candidates/v1",
            "project_id": self.project_id,
            "manuscript_id": canonical_id,
            "manuscript_revision": manuscript.revision,
            "policy": {
                "candidate_scope": "project_research_map",
                "journal_entries_are_candidates": False,
                "cluster_synthesis_requires": "brain",
                "eligible_cluster_confidence": ["strong", "moderate"],
                "contradictions_fail_closed": True,
                "proposal_creates_ratification": False,
            },
            "clusters": clusters,
            "excluded_claims": sorted(
                excluded_claims,
                key=lambda item: (
                    item["cluster_id"],
                    item["claim_id"],
                ),
            ),
            "candidate_spine": {
                "schema_version": "rka-writer-candidate-spine/v1",
                "project_id": self.project_id,
                "manuscript_id": canonical_id,
                "manuscript_revision": manuscript.revision,
                "claims": candidate_claims,
                "units": [],
            },
            "candidate_lineage": candidate_lineage,
            "summary": {
                "clusters_total": len(clusters),
                "clusters_eligible": sum(
                    item["disposition"] == "eligible" for item in clusters
                ),
                "clusters_needing_review": sum(
                    item["disposition"] != "eligible" for item in clusters
                ),
                "claims_excluded": len(excluded_claims),
            },
            "required_human_actions": [
                "Select only research questions in scope for this manuscript.",
                "Assign orphaned clusters to a research question.",
                "Use Brain review for stale, emerging, or LLM-only syntheses.",
                "Resolve contradiction edges before promoting a cluster.",
                "PI must bound prohibited wording and ratify exact wording.",
                "Map ratified claims to manuscript units before drafting.",
            ],
            "mode": "server_attested_read_only_proposal",
        }

    async def _artifact_binding(
        self,
        artifact_ref: str | None,
    ) -> dict[str, Any]:
        """Resolve portable result evidence to a same-project content identity."""
        if not artifact_ref:
            return {"verified": False, "reason": "missing"}
        if artifact_ref.startswith("art_"):
            row = await self.db.fetchone(
                """SELECT filename, filetype, file_size, mime, content_hash,
                          extraction_status
                   FROM artifacts
                   WHERE id = ? AND project_id = ?""",
                [artifact_ref, self.project_id],
            )
            if row is None:
                return {"verified": False, "reason": "not_found"}
            binding = {"entity_type": "artifact", **dict(row)}
        elif artifact_ref.startswith("fig_"):
            row = await self.db.fetchone(
                """SELECT f.page, f.caption, f.caption_confidence, f.summary,
                          a.filename, a.filetype, a.file_size, a.mime,
                          a.content_hash, a.extraction_status
                   FROM figures AS f
                   JOIN artifacts AS a
                     ON a.id = f.artifact_id
                    AND a.project_id = f.project_id
                   WHERE f.id = ? AND f.project_id = ?""",
                [artifact_ref, self.project_id],
            )
            if row is None:
                return {"verified": False, "reason": "not_found"}
            binding = {"entity_type": "figure", **dict(row)}
        else:
            return {"verified": False, "reason": "untyped_reference"}
        binding["verified"] = bool(
            binding.get("content_hash")
            and binding.get("extraction_status") == "complete"
        )
        return binding

    async def _checkpoint_dependency_snapshot(
        self,
        manuscript_id: str,
        *,
        kind: str,
        unit_id: str | None,
    ) -> dict[str, Any]:
        """Hash only the semantic inputs governed by one PI checkpoint."""
        components: dict[str, Any] = {}
        manuscript = await self.db.fetchone(
            """SELECT title, abstract, venue, workspace_ref
               FROM manuscripts
               WHERE id = ? AND project_id = ?""",
            [manuscript_id, self.project_id],
        )
        if kind == "venue":
            components["venue"] = manuscript.get("venue") if manuscript else None
        elif kind == "outline":
            components["claims"] = await self.db.fetchall(
                """SELECT c.local_key, c.kind, c.state, v.version,
                          v.exact_wording, v.allowed_wording,
                          v.prohibited_wording, d.chosen AS ratified_choice,
                          d.status AS ratification_status
                   FROM manuscript_claims AS c
                   LEFT JOIN manuscript_claim_versions AS v
                     ON v.claim_id = c.id
                    AND v.version = (
                        SELECT max(v2.version)
                        FROM manuscript_claim_versions AS v2
                        WHERE v2.claim_id = c.id
                    )
                   LEFT JOIN manuscript_claim_ratifications AS r
                     ON r.claim_id = c.id AND r.claim_version = v.version
                   LEFT JOIN decisions AS d
                     ON d.id = r.decision_id AND d.project_id = r.project_id
                   WHERE c.manuscript_id = ? AND c.project_id = ?
                   ORDER BY c.local_key""",
                [manuscript_id, self.project_id],
            )
            components["units"] = await self.db.fetchall(
                """SELECT local_key, kind, location, title, sequence, status
                   FROM manuscript_units
                   WHERE manuscript_id = ? AND project_id = ?
                   ORDER BY sequence, local_key""",
                [manuscript_id, self.project_id],
            )
            components["claim_unit_map"] = await self.db.fetchall(
                """SELECT c.local_key AS claim_key,
                          u.local_key AS unit_key, cu.relationship
                   FROM manuscript_claim_units AS cu
                   JOIN manuscript_claims AS c
                     ON c.id = cu.manuscript_claim_id
                   JOIN manuscript_units AS u ON u.id = cu.unit_id
                   WHERE cu.manuscript_id = ? AND cu.project_id = ?
                   ORDER BY claim_key, unit_key, cu.relationship""",
                [manuscript_id, self.project_id],
            )
        elif kind == "table_figure_plan":
            rows = await self.db.fetchall(
                """SELECT local_key, kind, location, title, artifact_ref,
                          allowed_interpretation, prohibited_interpretation,
                          sequence, status
                   FROM manuscript_units
                   WHERE manuscript_id = ? AND project_id = ?
                     AND kind IN ('result', 'caption')
                   ORDER BY sequence, local_key""",
                [manuscript_id, self.project_id],
            )
            for row in rows:
                row["artifact_binding"] = await self._artifact_binding(
                    row.get("artifact_ref")
                )
                row.pop("artifact_ref", None)
            components["result_units"] = rows
        elif kind == "reference_set":
            manifest = await self._get_reference_manifest_snapshot(
                manuscript_id
            )
            components["reference_manifest"] = [
                {
                    "citation_key": member["citation_key"],
                    "literature_title": member.get("literature_title"),
                    "literature_authors": member.get("literature_authors"),
                    "literature_year": member.get("literature_year"),
                    "literature_venue": member.get("literature_venue"),
                    "literature_doi": member.get("literature_doi"),
                    "literature_url": member.get("literature_url"),
                    "literature_status": member.get("literature_status"),
                    "literature_updated_at": member.get(
                        "literature_updated_at"
                    ),
                    # Checkpoints approve the semantic reference set, not
                    # installation-local row identities. Knowledge-pack import
                    # intentionally re-keys memberships, literature, and
                    # validation attestations, so including any of those IDs
                    # would make a lossless round trip look like dependency
                    # drift.
                    "validation": {
                        key: value
                        for key, value in (member.get("validation") or {}).items()
                        if key != "id"
                    },
                }
                for member in manifest["members"]
            ]
        elif kind == "draft_section":
            unit = await self.db.fetchone(
                """SELECT local_key, kind, location, title, artifact_ref,
                          allowed_interpretation, prohibited_interpretation,
                          sequence, status
                   FROM manuscript_units
                   WHERE id = ? AND manuscript_id = ? AND project_id = ?""",
                [unit_id, manuscript_id, self.project_id],
            )
            if unit is not None:
                unit["artifact_binding"] = await self._artifact_binding(
                    unit.get("artifact_ref")
                )
                unit.pop("artifact_ref", None)
            components["unit"] = unit
            components["claims"] = await self.db.fetchall(
                """SELECT c.local_key, c.kind, c.state, v.version,
                          v.exact_wording, v.allowed_wording,
                          v.prohibited_wording, cu.relationship
                   FROM manuscript_claim_units AS cu
                   JOIN manuscript_claims AS c
                     ON c.id = cu.manuscript_claim_id
                   JOIN manuscript_claim_versions AS v
                     ON v.claim_id = cu.manuscript_claim_id
                    AND v.version = cu.claim_version
                   WHERE cu.unit_id = ? AND cu.manuscript_id = ?
                     AND cu.project_id = ?
                   ORDER BY c.local_key, cu.relationship""",
                [unit_id, manuscript_id, self.project_id],
            )
            components["evidence"] = await self.db.fetchall(
                """SELECT e.role, c.content, c.confidence, c.verified,
                          c.evidence_status, c.stale, j.content AS source_content,
                          j.status AS source_status
                   FROM manuscript_unit_evidence AS e
                   JOIN claims AS c
                     ON c.id = e.evidence_claim_id
                    AND c.project_id = e.project_id
                   LEFT JOIN journal AS j
                     ON j.id = c.source_entry_id
                    AND j.project_id = c.project_id
                   WHERE e.unit_id = ? AND e.manuscript_id = ?
                     AND e.project_id = ?
                   ORDER BY e.role, c.content""",
                [unit_id, manuscript_id, self.project_id],
            )
        elif kind == "final_layout":
            components["manuscript"] = manuscript or {}
            rows = await self.db.fetchall(
                """SELECT local_key, kind, location, title, artifact_ref,
                          sequence, status
                   FROM manuscript_units
                   WHERE manuscript_id = ? AND project_id = ?
                     AND status <> 'removed'
                   ORDER BY sequence, local_key""",
                [manuscript_id, self.project_id],
            )
            for row in rows:
                if row.get("artifact_ref"):
                    row["artifact_binding"] = await self._artifact_binding(
                        row["artifact_ref"]
                    )
                row.pop("artifact_ref", None)
            components["units"] = rows
        else:
            raise ValueError(f"unsupported checkpoint kind {kind!r}")
        encoded = json.dumps(
            components,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode()
        return {
            "schema_version": "rka.checkpoint-dependencies/v1",
            "kind": kind,
            "unit_key": (
                components.get("unit", {}).get("local_key")
                if isinstance(components.get("unit"), Mapping)
                else None
            ),
            "sha256": hashlib.sha256(encoded).hexdigest(),
        }

    async def export_spine_projection(self, manuscript_id: str) -> dict[str, Any]:
        """Export the current RKA aggregate as a deterministic Writer cache."""
        context = await self.get_context(manuscript_id)
        claims = []
        unit_claims: dict[str, list[str]] = {}
        for claim in context["claims"]:
            evidence_by_role = {
                role: [
                    item["evidence_claim_id"]
                    for item in claim["evidence"]
                    if item["role"] == role
                ]
                for role in ("support", "qualifier", "counterevidence")
            }
            current_ratification = next(
                (
                    item
                    for item in reversed(claim["ratifications"])
                    if item.get("claim_version") == claim.get("version")
                    and item.get("decision_status") == "active"
                    and item.get("decided_by") == "pi"
                    and not item.get("superseded_by")
                    and item.get("chosen") == claim.get("exact_wording")
                ),
                None,
            )
            local_claim_id = claim["local_key"]
            for link in claim["unit_links"]:
                unit_claims.setdefault(link["unit_local_key"], []).append(
                    local_claim_id
                )
            claims.append({
                "claim_id": local_claim_id,
                "rka_manuscript_claim_id": claim["id"],
                "version": claim.get("version"),
                "claim_type": claim["kind"],
                "status": claim["state"],
                "text": claim.get("exact_wording"),
                "allowed_wording": claim.get("allowed_wording"),
                "prohibited_wording": claim.get("prohibited_wording") or [],
                "ratified_by": (
                    current_ratification.get("decision_id")
                    if current_ratification else None
                ),
                "evidence_ids": evidence_by_role["support"],
                "qualifier_ids": evidence_by_role["qualifier"],
                "counterevidence_ids": evidence_by_role["counterevidence"],
                "manuscript_units": [
                    link["unit_local_key"] for link in claim["unit_links"]
                ],
            })
        units = []
        for unit in context["units"]:
            units.append({
                "unit_id": unit["local_key"],
                "rka_manuscript_unit_id": unit["id"],
                "kind": unit["kind"],
                "location": unit["location"],
                "artifact_ref": unit.get("artifact_ref"),
                "allowed_interpretation": unit.get("allowed_interpretation"),
                "prohibited_interpretation": unit.get("prohibited_interpretation"),
                "status": unit["status"],
                "evidence_ids": [
                    item["evidence_claim_id"]
                    for item in unit["evidence"]
                    if item["role"] == "support"
                ],
                "claim_ids": sorted(set(unit_claims.get(unit["local_key"], []))),
            })
        return {
            "schema_version": "rka-claim-spine/v2",
            "authoritative_source": "rka",
            "project_id": self.project_id,
            "manuscript_id": context["manuscript"]["id"],
            "manuscript_revision": context["manuscript"]["revision"],
            "claims": claims,
            "units": units,
            "reference_manifest": context["reference_manifest"],
        }

    async def _require_id(self, manuscript_id: str) -> str:
        canonical_id = await self.resolve_id(manuscript_id)
        if canonical_id is None:
            raise ManuscriptNotFoundError(
                f"manuscript {manuscript_id!r} does not belong to project "
                f"{self.project_id}"
            )
        return canonical_id

    async def _assert_revision(self, manuscript_id: str, expected_revision: int) -> None:
        row = await self.db.fetchone(
            "SELECT revision FROM manuscripts WHERE id = ? AND project_id = ?",
            [manuscript_id, self.project_id],
        )
        if row is None:
            raise ManuscriptNotFoundError(
                f"manuscript {manuscript_id!r} not found"
            )
        if int(row["revision"]) != expected_revision:
            raise ManuscriptRevisionConflict(
                f"manuscript {manuscript_id} revision is {row['revision']}, "
                f"expected {expected_revision}"
            )

    async def _raise_revision_conflict(
        self, manuscript_id: str, expected_revision: int
    ) -> None:
        row = await self.db.fetchone(
            "SELECT revision FROM manuscripts WHERE id = ? AND project_id = ?",
            [manuscript_id, self.project_id],
        )
        if row is None:
            raise ManuscriptNotFoundError(
                f"manuscript {manuscript_id!r} not found"
            )
        raise ManuscriptRevisionConflict(
            f"manuscript {manuscript_id} revision is {row['revision']}, "
            f"expected {expected_revision}"
        )

    async def _bump_revision(
        self, manuscript_id: str, expected_revision: int
    ) -> None:
        cursor = await self.db.execute(
            """UPDATE manuscripts
               SET revision = revision + 1, updated_at = ?
               WHERE id = ? AND project_id = ? AND revision = ?""",
            [_now(), manuscript_id, self.project_id, expected_revision],
        )
        if cursor.rowcount != 1:
            await self._raise_revision_conflict(manuscript_id, expected_revision)

    async def _invalidate_resolved_checkpoints(
        self,
        manuscript_id: str,
        *,
        kinds: set[str],
    ) -> None:
        """Invalidate only approvals whose semantic dependency changed."""
        if not kinds:
            return
        placeholders = ", ".join("?" for _ in kinds)
        checkpoints = await self.db.fetchall(
            f"""SELECT id, kind, unit_id, dependency_snapshot
                FROM manuscript_checkpoints
                WHERE manuscript_id = ? AND project_id = ?
                  AND status = 'resolved'
                  AND kind IN ({placeholders})
                ORDER BY id""",
            [manuscript_id, self.project_id, *sorted(kinds)],
        )
        stale_ids: list[str] = []
        for checkpoint in checkpoints:
            stored_snapshot = self._json_loads(
                checkpoint.get("dependency_snapshot"), {}
            )
            current_snapshot = await self._checkpoint_dependency_snapshot(
                manuscript_id,
                kind=checkpoint["kind"],
                unit_id=checkpoint.get("unit_id"),
            )
            if stored_snapshot != current_snapshot:
                stale_ids.append(str(checkpoint["id"]))
        if not stale_ids:
            return
        stale_placeholders = ", ".join("?" for _ in stale_ids)
        await self.db.execute(
            f"""UPDATE manuscript_checkpoints
                SET status = 'superseded'
                WHERE manuscript_id = ? AND project_id = ?
                  AND status = 'resolved'
                  AND id IN ({stale_placeholders})""",
            [manuscript_id, self.project_id, *stale_ids],
        )

    @staticmethod
    def _spec_list(value: Any, name: str) -> list[Mapping[str, Any]]:
        if value is None:
            return []
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            raise ValueError(f"spine {name} must be a list")
        result = []
        for index, item in enumerate(value):
            if not isinstance(item, Mapping):
                raise ValueError(f"spine {name}[{index}] must be an object")
            result.append(item)
        return result

    def _normalize_claim_specs(self, value: Any) -> list[dict[str, Any]]:
        normalized = []
        for raw in self._spec_list(value, "claims"):
            local_key = str(raw.get("local_key") or raw.get("claim_id") or "").strip()
            exact = str(raw.get("exact_wording") or raw.get("text") or "").strip()
            allowed = str(raw.get("allowed_wording") or "").strip()
            prohibited = raw.get("prohibited_wording")
            kind = str(raw.get("kind") or raw.get("claim_type") or "").strip()
            state = str(raw.get("state") or raw.get("status") or "candidate").strip()
            if state == "ratified":
                state = "active"
            if (
                not local_key
                or not exact
                or not allowed
                or kind not in {
                    "empirical", "methodological", "theoretical", "survey", "position"
                }
                or state not in {"candidate", "active", "retired"}
                or not isinstance(prohibited, list)
                or not prohibited
                or any(not isinstance(item, str) or not item.strip() for item in prohibited)
            ):
                raise ValueError(
                    f"invalid native manuscript claim specification {local_key!r}"
                )
            evidence = raw.get("evidence") or {}
            if not isinstance(evidence, Mapping):
                raise ValueError(f"claim {local_key} evidence must be an object")
            support = evidence.get("support", raw.get("evidence_ids", []))
            qualifier = evidence.get("qualifier", raw.get("qualifier_ids", []))
            counter = evidence.get(
                "counterevidence", raw.get("counterevidence_ids", [])
            )
            raw_links = raw.get("unit_links", raw.get("manuscript_units", []))
            links = []
            for item in raw_links or []:
                if isinstance(item, str):
                    links.append({"unit_key": item, "relationship": "advances"})
                elif isinstance(item, Mapping):
                    links.append({
                        "unit_key": item.get("unit_key") or item.get("unit_id"),
                        "relationship": item.get("relationship", "advances"),
                    })
                else:
                    raise ValueError(f"claim {local_key} has an invalid unit link")
            normalized.append({
                "local_key": local_key,
                "kind": kind,
                "state": state,
                "exact_wording": exact,
                "allowed_wording": allowed,
                "prohibited_wording": [item.strip() for item in prohibited],
                "evidence": {
                    "support": self._id_list(support, f"claim {local_key} support"),
                    "qualifier": self._id_list(
                        qualifier, f"claim {local_key} qualifiers"
                    ),
                    "counterevidence": self._id_list(
                        counter, f"claim {local_key} counterevidence"
                    ),
                },
                "unit_links": links,
            })
        return normalized

    def _normalize_unit_specs(self, value: Any) -> list[dict[str, Any]]:
        normalized = []
        valid_kinds = {
            "abstract", "introduction", "related_work", "background", "method",
            "result", "discussion", "limitation", "conclusion", "caption",
            "appendix", "other",
        }
        valid_statuses = {"planned", "drafted", "reviewed", "final", "removed"}
        for raw in self._spec_list(value, "units"):
            local_key = str(raw.get("local_key") or raw.get("unit_id") or "").strip()
            kind = str(raw.get("kind") or "").strip()
            location = str(
                raw.get("location") or raw.get("source_location") or ""
            ).strip()
            status = str(raw.get("status") or "planned").strip()
            if not local_key or kind not in valid_kinds or not location:
                raise ValueError(
                    f"invalid native manuscript unit specification {local_key!r}"
                )
            if status not in valid_statuses:
                raise ValueError(f"unit {local_key} has invalid status {status!r}")
            if kind == "result":
                for field in (
                    "artifact_ref",
                    "allowed_interpretation",
                    "prohibited_interpretation",
                ):
                    if not str(raw.get(field) or "").strip():
                        raise ValueError(f"result unit {local_key} requires {field}")
            evidence = raw.get("evidence") or {}
            if not isinstance(evidence, Mapping):
                raise ValueError(f"unit {local_key} evidence must be an object")
            normalized.append({
                "local_key": local_key,
                "kind": kind,
                "location": location,
                "title": raw.get("title"),
                "artifact_ref": raw.get("artifact_ref"),
                "allowed_interpretation": raw.get("allowed_interpretation"),
                "prohibited_interpretation": raw.get("prohibited_interpretation"),
                "sequence": int(raw.get("sequence", 0)),
                "status": status,
                "evidence": {
                    "support": self._id_list(
                        evidence.get("support", raw.get("evidence_ids", [])),
                        f"unit {local_key} support",
                    ),
                    "qualifier": self._id_list(
                        evidence.get("qualifier", raw.get("qualifier_ids", [])),
                        f"unit {local_key} qualifiers",
                    ),
                    "counterevidence": self._id_list(
                        evidence.get(
                            "counterevidence", raw.get("counterevidence_ids", [])
                        ),
                        f"unit {local_key} counterevidence",
                    ),
                },
            })
        return normalized

    @staticmethod
    def _id_list(value: Any, name: str) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            raise ValueError(f"{name} must be a list")
        ids = []
        for item in value:
            if not isinstance(item, str) or not item.startswith("clm_"):
                raise ValueError(f"{name} contains a non-claim id")
            ids.append(item)
        return sorted(set(ids))

    @staticmethod
    def _assert_unique_local_keys(specs: list[dict[str, Any]], label: str) -> None:
        keys = [spec["local_key"] for spec in specs]
        if len(keys) != len(set(keys)):
            raise ValueError(f"duplicate {label} local_key in argument spine")

    async def _upsert_claims(
        self,
        manuscript_id: str,
        claims: list[dict[str, Any]],
    ) -> dict[str, tuple[str, int]]:
        existing_rows = await self.db.fetchall(
            """SELECT * FROM manuscript_claims
               WHERE manuscript_id = ? AND project_id = ?""",
            [manuscript_id, self.project_id],
        )
        existing = {row["local_key"]: row for row in existing_rows}
        seen: set[str] = set()
        result: dict[str, tuple[str, int]] = {}
        for spec in claims:
            local_key = spec["local_key"]
            seen.add(local_key)
            row = existing.get(local_key)
            if row is None:
                claim_id = generate_id("manuscript_claim")
                await self.db.execute(
                    """INSERT INTO manuscript_claims
                       (id, manuscript_id, project_id, local_key, kind, state)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    [
                        claim_id,
                        manuscript_id,
                        self.project_id,
                        local_key,
                        spec["kind"],
                        spec["state"],
                    ],
                )
                previous_version = 0
            else:
                claim_id = row["id"]
                if row["kind"] != spec["kind"]:
                    raise ValueError(
                        f"claim {local_key} kind is immutable; retire it and "
                        "create a new local_key"
                    )
                await self.db.execute(
                    """UPDATE manuscript_claims
                       SET state = ?, updated_at = ?
                       WHERE id = ? AND manuscript_id = ? AND project_id = ?""",
                    [
                        spec["state"],
                        _now(),
                        claim_id,
                        manuscript_id,
                        self.project_id,
                    ],
                )
                previous_version = await self._latest_claim_version(claim_id) or 0

            latest = None
            if previous_version:
                latest = await self.db.fetchone(
                    """SELECT exact_wording, allowed_wording, prohibited_wording
                       FROM manuscript_claim_versions
                       WHERE claim_id = ? AND version = ?""",
                    [claim_id, previous_version],
                )
            same_wording = bool(
                latest
                and latest["exact_wording"] == spec["exact_wording"]
                and latest["allowed_wording"] == spec["allowed_wording"]
                and self._json_loads(latest["prohibited_wording"], [])
                == spec["prohibited_wording"]
            )
            version = previous_version if same_wording else previous_version + 1
            if not same_wording:
                await self.db.execute(
                    """INSERT INTO manuscript_claim_versions
                       (claim_id, version, manuscript_id, project_id,
                        exact_wording, allowed_wording, prohibited_wording)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    [
                        claim_id,
                        version,
                        manuscript_id,
                        self.project_id,
                        spec["exact_wording"],
                        spec["allowed_wording"],
                        json.dumps(spec["prohibited_wording"], sort_keys=True),
                    ],
                )
            await self._replace_claim_evidence(
                manuscript_id, claim_id, version, spec["evidence"]
            )
            result[local_key] = (claim_id, version)

        for local_key, row in existing.items():
            if local_key not in seen and row["state"] != "retired":
                await self.db.execute(
                    """UPDATE manuscript_claims
                       SET state = 'retired', updated_at = ?
                       WHERE id = ? AND project_id = ?""",
                    [_now(), row["id"], self.project_id],
                )
        return result

    async def _upsert_units(
        self,
        manuscript_id: str,
        units: list[dict[str, Any]],
    ) -> dict[str, str]:
        existing_rows = await self.db.fetchall(
            """SELECT * FROM manuscript_units
               WHERE manuscript_id = ? AND project_id = ?""",
            [manuscript_id, self.project_id],
        )
        existing = {row["local_key"]: row for row in existing_rows}
        seen: set[str] = set()
        result: dict[str, str] = {}
        for spec in units:
            local_key = spec["local_key"]
            seen.add(local_key)
            row = existing.get(local_key)
            fields = [
                spec["kind"],
                spec["location"],
                spec["title"],
                spec["artifact_ref"],
                spec["allowed_interpretation"],
                spec["prohibited_interpretation"],
                spec["sequence"],
                spec["status"],
            ]
            if row is None:
                unit_id = generate_id("manuscript_unit")
                await self.db.execute(
                    """INSERT INTO manuscript_units
                       (id, manuscript_id, project_id, local_key, kind,
                        location, title, artifact_ref, allowed_interpretation,
                        prohibited_interpretation, sequence, status)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [
                        unit_id,
                        manuscript_id,
                        self.project_id,
                        local_key,
                        *fields,
                    ],
                )
            else:
                unit_id = row["id"]
                await self.db.execute(
                    """UPDATE manuscript_units
                       SET kind = ?, location = ?, title = ?, artifact_ref = ?,
                           allowed_interpretation = ?,
                           prohibited_interpretation = ?, sequence = ?,
                           status = ?, updated_at = ?
                       WHERE id = ? AND manuscript_id = ? AND project_id = ?""",
                    [
                        *fields,
                        _now(),
                        unit_id,
                        manuscript_id,
                        self.project_id,
                    ],
                )
            await self._replace_unit_evidence(
                manuscript_id, unit_id, spec["evidence"]
            )
            result[local_key] = unit_id

        for local_key, row in existing.items():
            if local_key not in seen and row["status"] != "removed":
                await self.db.execute(
                    """UPDATE manuscript_units
                       SET status = 'removed', updated_at = ?
                       WHERE id = ? AND project_id = ?""",
                    [_now(), row["id"], self.project_id],
                )
        return result

    async def _replace_claim_evidence(
        self,
        manuscript_id: str,
        claim_id: str,
        version: int,
        evidence: Mapping[str, list[str]],
    ) -> None:
        await self.db.execute(
            """DELETE FROM manuscript_claim_evidence
               WHERE manuscript_claim_id = ? AND claim_version = ?
                 AND project_id = ?""",
            [claim_id, version, self.project_id],
        )
        for role in ("support", "qualifier", "counterevidence"):
            for ordinal, evidence_id in enumerate(evidence[role]):
                await self.db.execute(
                    """INSERT INTO manuscript_claim_evidence
                       (manuscript_id, project_id, manuscript_claim_id,
                        claim_version, evidence_claim_id, role, ordinal)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    [
                        manuscript_id,
                        self.project_id,
                        claim_id,
                        version,
                        evidence_id,
                        role,
                        ordinal,
                    ],
                )

    async def _replace_unit_evidence(
        self,
        manuscript_id: str,
        unit_id: str,
        evidence: Mapping[str, list[str]],
    ) -> None:
        await self.db.execute(
            """DELETE FROM manuscript_unit_evidence
               WHERE unit_id = ? AND project_id = ?""",
            [unit_id, self.project_id],
        )
        for role in ("support", "qualifier", "counterevidence"):
            for ordinal, evidence_id in enumerate(evidence[role]):
                await self.db.execute(
                    """INSERT INTO manuscript_unit_evidence
                       (manuscript_id, project_id, unit_id, evidence_claim_id,
                        role, ordinal)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    [
                        manuscript_id,
                        self.project_id,
                        unit_id,
                        evidence_id,
                        role,
                        ordinal,
                    ],
                )

    async def _replace_claim_unit_bindings(
        self,
        manuscript_id: str,
        claims: list[dict[str, Any]],
        *,
        claim_versions: Mapping[str, tuple[str, int]],
        unit_ids: Mapping[str, str],
    ) -> None:
        for spec in claims:
            claim_id, version = claim_versions[spec["local_key"]]
            await self.db.execute(
                """DELETE FROM manuscript_claim_units
                   WHERE manuscript_claim_id = ? AND claim_version = ?
                     AND project_id = ?""",
                [claim_id, version, self.project_id],
            )
            for link in spec["unit_links"]:
                unit_key = str(link.get("unit_key") or "").strip()
                relationship = str(link.get("relationship") or "").strip()
                if unit_key not in unit_ids:
                    raise ValueError(
                        f"claim {spec['local_key']} references unknown unit {unit_key!r}"
                    )
                if relationship not in {"advances", "tests", "bounds", "mentions"}:
                    raise ValueError(
                        f"claim {spec['local_key']} has invalid unit relationship"
                    )
                await self.db.execute(
                    """INSERT INTO manuscript_claim_units
                       (manuscript_id, project_id, manuscript_claim_id,
                        claim_version, unit_id, relationship)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    [
                        manuscript_id,
                        self.project_id,
                        claim_id,
                        version,
                        unit_ids[unit_key],
                        relationship,
                    ],
                )

    async def _find_claim(
        self,
        manuscript_id: str,
        *,
        claim_id: str | None,
        local_key: str | None,
    ) -> dict[str, Any] | None:
        if claim_id is not None:
            return await self.db.fetchone(
                """SELECT * FROM manuscript_claims
                   WHERE id = ? AND manuscript_id = ? AND project_id = ?""",
                [claim_id, manuscript_id, self.project_id],
            )
        return await self.db.fetchone(
            """SELECT * FROM manuscript_claims
               WHERE local_key = ? AND manuscript_id = ? AND project_id = ?""",
            [local_key, manuscript_id, self.project_id],
        )

    async def _latest_claim_version(self, claim_id: str) -> int | None:
        row = await self.db.fetchone(
            "SELECT MAX(version) AS version FROM manuscript_claim_versions WHERE claim_id = ?",
            [claim_id],
        )
        return int(row["version"]) if row and row.get("version") is not None else None

    async def _claim_evidence(
        self, manuscript_id: str, claim_id: str, version: int | None
    ) -> list[dict[str, Any]]:
        if version is None:
            return []
        return await self.db.fetchall(
            """SELECT e.*, c.content, c.claim_type, c.confidence, c.verified,
                      c.evidence_status, c.stale, c.source_entry_id,
                      EXISTS (
                          SELECT 1 FROM claim_edges AS ce
                          WHERE ce.project_id = c.project_id
                            AND ce.relation = 'contradicts'
                            AND (
                                ce.source_claim_id = c.id
                                OR ce.target_claim_id = c.id
                            )
                      ) AS contradicted,
                      CASE
                          WHEN j.id IS NOT NULL
                           AND j.status = 'active'
                           AND j.confidence NOT IN ('superseded', 'retracted')
                           AND j.superseded_by IS NULL
                          THEN 1 ELSE 0
                      END AS source_current,
                      (
                          EXISTS (
                              SELECT 1 FROM tags AS t
                              WHERE t.project_id = c.project_id
                                AND t.entity_type = 'journal'
                                AND t.entity_id = c.source_entry_id
                                AND lower(t.tag) = 'manuscript'
                          )
                          OR EXISTS (
                              SELECT 1 FROM manuscripts AS source_manuscript
                              WHERE source_manuscript.project_id = c.project_id
                                AND source_manuscript.legacy_journal_id =
                                    c.source_entry_id
                          )
                      ) AS source_is_manuscript
               FROM manuscript_claim_evidence AS e
               JOIN claims AS c
                 ON c.id = e.evidence_claim_id
                AND c.project_id = e.project_id
               LEFT JOIN journal AS j
                 ON j.id = c.source_entry_id
                AND j.project_id = c.project_id
               WHERE e.manuscript_id = ?
                 AND e.manuscript_claim_id = ?
                 AND e.claim_version = ?
                 AND e.project_id = ?
               ORDER BY e.role, e.ordinal, e.evidence_claim_id""",
            [manuscript_id, claim_id, version, self.project_id],
        )

    async def _unit_evidence(
        self, manuscript_id: str, unit_id: str
    ) -> list[dict[str, Any]]:
        return await self.db.fetchall(
            """SELECT e.*, c.content, c.claim_type, c.confidence, c.verified,
                      c.evidence_status, c.stale, c.source_entry_id,
                      EXISTS (
                          SELECT 1 FROM claim_edges AS ce
                          WHERE ce.project_id = c.project_id
                            AND ce.relation = 'contradicts'
                            AND (
                                ce.source_claim_id = c.id
                                OR ce.target_claim_id = c.id
                            )
                      ) AS contradicted,
                      CASE
                          WHEN j.id IS NOT NULL
                           AND j.status = 'active'
                           AND j.confidence NOT IN ('superseded', 'retracted')
                           AND j.superseded_by IS NULL
                          THEN 1 ELSE 0
                      END AS source_current,
                      (
                          EXISTS (
                              SELECT 1 FROM tags AS t
                              WHERE t.project_id = c.project_id
                                AND t.entity_type = 'journal'
                                AND t.entity_id = c.source_entry_id
                                AND lower(t.tag) = 'manuscript'
                          )
                          OR EXISTS (
                              SELECT 1 FROM manuscripts AS source_manuscript
                              WHERE source_manuscript.project_id = c.project_id
                                AND source_manuscript.legacy_journal_id =
                                    c.source_entry_id
                          )
                      ) AS source_is_manuscript
               FROM manuscript_unit_evidence AS e
               JOIN claims AS c
                 ON c.id = e.evidence_claim_id
                AND c.project_id = e.project_id
               LEFT JOIN journal AS j
                 ON j.id = c.source_entry_id
                AND j.project_id = c.project_id
               WHERE e.manuscript_id = ? AND e.unit_id = ?
                 AND e.project_id = ?
               ORDER BY e.role, e.ordinal, e.evidence_claim_id""",
            [manuscript_id, unit_id, self.project_id],
        )
