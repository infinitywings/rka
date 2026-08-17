"""Progressive outline projections and proposal-first structural edits."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from rka.models.outline import OutlineProposalRequest
from rka.models.semantic_patch import (
    ArgumentSpineReplaceOperation,
    SemanticPatchProposalCreate,
)
from rka.services.base import BaseService
from rka.services.manuscript_native import NativeManuscriptService
from rka.services.semantic_patch import SemanticPatchService


class ManuscriptOutlineService(BaseService):
    """Join outline rationale to native units and prepare safe transformations."""

    async def get_outline(self, manuscript_id: str) -> dict[str, Any]:
        native = NativeManuscriptService(self.db, project_id=self.project_id)
        context = await native.get_context(manuscript_id)
        claims_by_unit: dict[str, list[dict[str, Any]]] = {}
        for claim in context["claims"]:
            for link in claim["unit_links"]:
                claims_by_unit.setdefault(str(link["unit_id"]), []).append(
                    {
                        "claim_id": claim["id"],
                        "claim_key": claim["local_key"],
                        "claim_version": claim.get("version"),
                        "exact_wording": claim.get("exact_wording"),
                        "relationship": link["relationship"],
                    }
                )

        active_units = [unit for unit in context["units"] if unit["status"] != "removed"]
        children: dict[str, list[str]] = {}
        for unit in active_units:
            if unit.get("parent_unit_key"):
                children.setdefault(str(unit["parent_unit_key"]), []).append(unit["local_key"])

        projected = []
        blocker_count = 0
        for unit in active_units:
            unit_claims = sorted(
                claims_by_unit.get(unit["id"], []),
                key=lambda item: (item["claim_key"], item["relationship"]),
            )
            missing = []
            if not unit.get("communicative_job"):
                missing.append("communicative_job")
            if not unit.get("intended_takeaway"):
                missing.append("intended_takeaway")
            if not unit_claims:
                missing.append("intended_claim")
            if not unit.get("evidence_plan"):
                missing.append("evidence_plan")
            if unit.get("blocker"):
                missing.append("declared_blocker")
            blocker_count += bool(missing)
            projected.append(
                {
                    **unit,
                    "claims": unit_claims,
                    "child_unit_keys": sorted(
                        children.get(unit["local_key"], []),
                        key=lambda key: next(
                            item["sequence"] for item in active_units if item["local_key"] == key
                        ),
                    ),
                    "completeness": "complete" if not missing else "needs_review",
                    "missing": missing,
                }
            )

        checkpoints = [
            checkpoint for checkpoint in context["checkpoints"] if checkpoint["kind"] == "outline"
        ]
        latest_checkpoint = checkpoints[-1] if checkpoints else None
        rationale_complete = bool(projected) and blocker_count == 0
        return {
            "schema_version": "rka.manuscript-outline/v1",
            "project_id": self.project_id,
            "manuscript_id": context["manuscript"]["id"],
            "manuscript_revision": context["manuscript"]["revision"],
            "units": projected,
            "outline_checkpoint": latest_checkpoint,
            "summary": {
                "active_units": len(projected),
                "complete_units": len(projected) - blocker_count,
                "units_needing_review": blocker_count,
                "levels": sorted({unit["outline_level"] for unit in projected}),
                "rationale_complete": rationale_complete,
                # Compatibility alias. This field never represented checkpoint
                # state; clients should migrate to rationale_complete.
                "checkpoint_ready": rationale_complete,
            },
            "policy": {
                "canonical_unit_identity": "mun_",
                "mutation": "semantic_patch_then_explicit_apply",
                "checkpoint_resolution": "explicit_pi_decision",
                "deprecated_fields": {"summary.checkpoint_ready": "summary.rationale_complete"},
                "file_writes": False,
            },
        }

    async def prepare_proposal(
        self,
        manuscript_id: str,
        data: OutlineProposalRequest,
        *,
        actor: str,
    ) -> dict[str, Any]:
        native = NativeManuscriptService(self.db, project_id=self.project_id)
        spine = await native.export_spine_projection(manuscript_id)
        if int(spine["manuscript_revision"]) != data.expected_revision:
            await native._raise_revision_conflict(manuscript_id, data.expected_revision)
        before = deepcopy(spine)
        claims = deepcopy(spine["claims"])
        units = deepcopy(spine["units"])

        if data.action == "edit":
            impact = self._edit(units, data)
        elif data.action == "expand":
            impact = self._expand(claims, units, data)
        elif data.action == "condense":
            impact = self._condense(claims, units, data)
        else:
            impact = self._reorder(units, data)

        if data.action != "edit":
            self._resequence(units)
        # Reuse the native closed-schema validator before persisting a proposal.
        native._normalize_claim_specs(claims)
        native._normalize_unit_specs(units)
        if actor not in {"pi", "brain", "executor", "web_ui"}:
            raise ValueError(f"invalid outline proposal actor {actor!r}")
        if actor in {"brain", "executor"} and data.origin == "human":
            raise ValueError(
                "AI-authored outline proposals must declare their provider origin "
                "and matching context manifest"
            )
        created_by = actor
        proposal = await SemanticPatchService(self.db, project_id=self.project_id).create_proposal(
            SemanticPatchProposalCreate(
                origin=data.origin,
                intent=f"{data.action.capitalize()} the progressive manuscript outline.",
                reason=data.reason,
                created_by=created_by,
                provider=data.provider,
                model=data.model,
                boundary=data.boundary,
                context_manifest_id=data.context_manifest_id,
                operations=[
                    ArgumentSpineReplaceOperation(
                        manuscript_id=str(spine["manuscript_id"]),
                        expected_revision=data.expected_revision,
                        spine={"claims": claims, "units": units},
                    )
                ],
            )
        )
        return {
            "schema_version": "rka.outline-proposal/v1",
            "proposal": proposal,
            "impact": {
                **impact,
                "before_revision": before["manuscript_revision"],
                "canonical_mutation": False,
                "apply_operation": "semantic_patch_apply",
            },
        }

    @staticmethod
    def _unit_map(units: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        return {str(unit["unit_id"]): unit for unit in units}

    def _active_unit(self, units: list[dict[str, Any]], key: str | None) -> dict[str, Any]:
        unit = self._unit_map(units).get(str(key))
        if unit is None or unit.get("status") == "removed":
            raise ValueError(f"active outline unit {key!r} not found")
        return unit

    def _edit(self, units: list[dict[str, Any]], data: OutlineProposalRequest) -> dict[str, Any]:
        unit = self._active_unit(units, data.unit_key)
        assert data.patch is not None
        changes = data.patch.model_dump(exclude_unset=True)
        unit.update(changes)
        return {
            "action": "edit",
            "affected_unit_keys": [unit["unit_id"]],
            "preserved": ["claim_links", "typed_evidence_bindings", "stable_unit_identity"],
        }

    def _expand(
        self,
        claims: list[dict[str, Any]],
        units: list[dict[str, Any]],
        data: OutlineProposalRequest,
    ) -> dict[str, Any]:
        parent = self._active_unit(units, data.unit_key)
        parent_level = int(parent.get("outline_level", 4))
        if parent_level >= 5:
            raise ValueError("L5 units cannot be expanded within the PR 9 outline contract")
        by_key = self._unit_map(units)
        child_keys = [child.local_key for child in data.children]
        if len(child_keys) != len(set(child_keys)) or any(key in by_key for key in child_keys):
            raise ValueError("expanded child local_key values must be new and unique")

        parent_claims: dict[str, list[dict[str, Any]]] = {}
        for claim in claims:
            links = [
                link
                for link in claim.get("unit_links", [])
                if (link.get("unit_key") or link.get("unit_id")) == parent["unit_id"]
            ]
            if links:
                parent_claims[str(claim["claim_id"])] = links
        parent_evidence = {
            "support_ids": set(parent.get("evidence_ids") or []),
            "qualifier_ids": set(parent.get("qualifier_ids") or []),
            "counterevidence_ids": set(parent.get("counterevidence_ids") or []),
        }

        inserted: list[dict[str, Any]] = []
        for child in data.children:
            selected_claims = set(child.claim_keys or parent_claims)
            if not selected_claims <= set(parent_claims):
                raise ValueError(
                    "expanded child claim_keys must be a subset of the parent bindings"
                )
            selected_evidence: dict[str, list[str]] = {}
            for field in ("support_ids", "qualifier_ids", "counterevidence_ids"):
                requested = getattr(child, field)
                chosen = set(requested) if requested is not None else parent_evidence[field]
                if not chosen <= parent_evidence[field]:
                    raise ValueError(
                        f"expanded child {field} must be a subset of the parent bindings"
                    )
                selected_evidence[field] = sorted(chosen)
            new_unit = {
                **{
                    key: value
                    for key, value in parent.items()
                    if key
                    not in {
                        "rka_manuscript_unit_id",
                        "evidence",
                        "evidence_ids",
                        "qualifier_ids",
                        "counterevidence_ids",
                    }
                },
                "unit_id": child.local_key,
                "title": child.title,
                "location": child.location,
                "sequence": int(parent["sequence"]) + len(inserted) + 1,
                "status": "planned",
                "outline_level": parent_level + 1,
                "parent_unit_key": parent["unit_id"],
                "communicative_job": child.communicative_job,
                "intended_takeaway": child.intended_takeaway,
                "transition_from_previous": child.transition_from_previous,
                "quick_reader_role": child.quick_reader_role,
                "evidence_plan": child.evidence_plan,
                "figure_intentions": child.figure_intentions,
                "table_intentions": child.table_intentions,
                "citation_intentions": child.citation_intentions,
                "blocker": child.blocker,
                "evidence": {
                    "support": selected_evidence["support_ids"],
                    "qualifier": selected_evidence["qualifier_ids"],
                    "counterevidence": selected_evidence["counterevidence_ids"],
                },
            }
            new_unit.pop("claim_ids", None)
            inserted.append(new_unit)
            for claim in claims:
                claim_key = str(claim["claim_id"])
                if claim_key not in selected_claims:
                    continue
                links = claim.setdefault("unit_links", [])
                for source_link in parent_claims[claim_key]:
                    links.append(
                        {
                            "unit_key": child.local_key,
                            "relationship": source_link.get("relationship", "advances"),
                        }
                    )

        parent_index = units.index(parent)
        units[parent_index + 1 : parent_index + 1] = inserted
        return {
            "action": "expand",
            "affected_unit_keys": [parent["unit_id"], *child_keys],
            "created_child_keys": child_keys,
            "inherited": ["claim_links", "support", "qualifier", "counterevidence"],
            "parent_retained": True,
        }

    def _condense(
        self,
        claims: list[dict[str, Any]],
        units: list[dict[str, Any]],
        data: OutlineProposalRequest,
    ) -> dict[str, Any]:
        parent = self._active_unit(units, data.unit_key)
        by_key = self._unit_map(units)
        selected = {key: self._active_unit(units, key) for key in data.descendant_keys}

        def is_descendant(unit: dict[str, Any]) -> bool:
            cursor = unit
            seen: set[str] = set()
            while cursor.get("parent_unit_key"):
                key = str(cursor["parent_unit_key"])
                if key == parent["unit_id"]:
                    return True
                if key in seen or key not in by_key:
                    return False
                seen.add(key)
                cursor = by_key[key]
            return False

        if any(not is_descendant(unit) for unit in selected.values()):
            raise ValueError("condense may remove only descendants of the selected parent")
        for unit in units:
            if unit.get("status") == "removed" or not unit.get("parent_unit_key"):
                continue
            if unit["parent_unit_key"] in selected and unit["unit_id"] not in selected:
                raise ValueError("condense must include active descendants of every removed unit")

        for evidence_field in ("evidence_ids", "qualifier_ids", "counterevidence_ids"):
            parent[evidence_field] = sorted(
                {
                    *(parent.get(evidence_field) or []),
                    *(
                        value
                        for unit in selected.values()
                        for value in unit.get(evidence_field) or []
                    ),
                }
            )
        for plan_field in (
            "evidence_plan",
            "figure_intentions",
            "table_intentions",
            "citation_intentions",
        ):
            parent[plan_field] = list(
                dict.fromkeys(
                    [
                        *(parent.get(plan_field) or []),
                        *(
                            value
                            for unit in selected.values()
                            for value in unit.get(plan_field) or []
                        ),
                    ]
                )
            )
        selected_keys = set(selected)
        for claim in claims:
            links = claim.setdefault("unit_links", [])
            inherited = [
                link
                for link in links
                if (link.get("unit_key") or link.get("unit_id")) in selected_keys
            ]
            parent_relationships = {
                link.get("relationship", "advances")
                for link in links
                if (link.get("unit_key") or link.get("unit_id")) == parent["unit_id"]
            }
            for relationship in sorted(
                {link.get("relationship", "advances") for link in inherited} - parent_relationships
            ):
                links.append({"unit_key": parent["unit_id"], "relationship": relationship})
            claim["unit_links"] = [
                link
                for link in links
                if (link.get("unit_key") or link.get("unit_id")) not in selected_keys
            ]
        for unit in selected.values():
            unit["status"] = "removed"
        return {
            "action": "condense",
            "affected_unit_keys": [parent["unit_id"], *sorted(selected)],
            "removed_descendant_keys": sorted(selected),
            "bindings_unioned_to_parent": True,
            "parent_retained": True,
        }

    def _reorder(self, units: list[dict[str, Any]], data: OutlineProposalRequest) -> dict[str, Any]:
        active = [unit for unit in units if unit.get("status") != "removed"]
        active_keys = [str(unit["unit_id"]) for unit in active]
        if len(data.ordered_unit_keys) != len(set(data.ordered_unit_keys)):
            raise ValueError("reorder keys must be unique")
        if set(data.ordered_unit_keys) != set(active_keys):
            missing = sorted(set(active_keys) - set(data.ordered_unit_keys))
            unknown = sorted(set(data.ordered_unit_keys) - set(active_keys))
            raise ValueError(
                f"reorder requires the exact active unit set; missing={missing}, unknown={unknown}"
            )
        old_predecessor = {
            key: active_keys[index - 1] if index else None for index, key in enumerate(active_keys)
        }
        by_key = self._unit_map(units)
        reordered = [by_key[key] for key in data.ordered_unit_keys]
        self._validate_active_order(reordered)
        removed = [unit for unit in units if unit.get("status") == "removed"]
        units[:] = [*reordered, *removed]
        changed = [
            key
            for index, key in enumerate(data.ordered_unit_keys)
            if old_predecessor[key] != (data.ordered_unit_keys[index - 1] if index else None)
        ]
        return {
            "action": "reorder",
            "affected_unit_keys": changed,
            "changed_predecessors": changed,
            "transition_review_required": changed,
            "preserved": ["claim_links", "typed_evidence_bindings", "unit_content"],
        }

    @staticmethod
    def _validate_active_order(units: list[dict[str, Any]]) -> None:
        """Require a depth-first flat order with every parent before its subtree."""
        positions = {str(unit["unit_id"]): index for index, unit in enumerate(units)}
        parents = {
            str(unit["unit_id"]): (
                str(unit["parent_unit_key"]) if unit.get("parent_unit_key") else None
            )
            for unit in units
        }

        def descendants(root: str) -> set[str]:
            found: set[str] = set()
            frontier = [root]
            while frontier:
                current = frontier.pop()
                children = [key for key, parent in parents.items() if parent == current]
                for child in children:
                    if child not in found:
                        found.add(child)
                        frontier.append(child)
            return found

        for key, parent in parents.items():
            if parent is not None and positions[parent] >= positions[key]:
                raise ValueError(f"outline order must place parent {parent!r} before child {key!r}")
        for key in positions:
            nested = descendants(key)
            if not nested:
                continue
            occupied = {positions[key], *(positions[item] for item in nested)}
            if max(occupied) - min(occupied) + 1 != len(occupied):
                raise ValueError(f"outline order must keep subtree {key!r} contiguous")

    @staticmethod
    def _resequence(units: list[dict[str, Any]]) -> None:
        active = [unit for unit in units if unit.get("status") != "removed"]
        removed = [unit for unit in units if unit.get("status") == "removed"]
        for index, unit in enumerate(active):
            unit["sequence"] = index * 10
        for index, unit in enumerate(removed, start=len(active)):
            unit["sequence"] = index * 10
