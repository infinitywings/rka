"""Test for Affordance E (Mission B / mis_01KR209WY4M6WQFEXRH79KC2ZF):
check_integrity issues carry a severity field, and the import_pack
rollback gate reads that field rather than a hardcoded category set.

The orphan-class categories must report severity='critical' (rollback
on import); claim_count_mismatch must report severity='warning' (commit
+ recompute on import). Mission A's T5 behavior is preserved exactly —
this is a refactor that swaps the lookup from category→constant to
issue→severity, but the semantics are identical.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rka.services.knowledge_pack import KnowledgePackService


class TestSeverityMapping:
    """Pure mapping table — no DB needed."""

    def test_orphan_categories_critical(self):
        for cat in (
            "orphaned_entity_link_sources",
            "orphaned_entity_link_targets",
            "orphaned_claim_edge_sources",
            "orphaned_claim_edge_targets",
            "orphaned_claim_edge_clusters",
        ):
            assert KnowledgePackService._severity_for(cat) == "critical"

    def test_claim_count_mismatch_warning(self):
        assert KnowledgePackService._severity_for("claim_count_mismatch") == "warning"

    def test_unknown_category_defaults_to_warning(self):
        """New advisory checks added in the future default to warning so
        they don't accidentally start blocking imports."""
        assert KnowledgePackService._severity_for("a_new_unknown_category") == "warning"


class TestCheckIntegrityCarriesSeverity:
    """check_integrity must include severity on every emitted issue."""

    async def test_orphan_target_issue_carries_critical_severity(self, db):
        # Insert an entity_link with an orphan target.
        await db.execute(
            "INSERT INTO projects (id, name) VALUES (?, ?)",
            ["proj_severity_orphan", "Sev Test"],
        )
        await db.execute(
            """INSERT INTO entity_links
               (id, source_type, source_id, link_type, target_type, target_id, project_id)
               VALUES ('lnk_sev_1', 'journal', 'jrn_x', 'references', 'decision',
                       'dec_does_not_exist_for_sure', 'proj_severity_orphan')""",
        )
        await db.commit()
        svc = KnowledgePackService(db, project_id="proj_severity_orphan")
        issues = await svc.check_integrity("proj_severity_orphan")
        assert any(
            i["category"] == "orphaned_entity_link_targets"
            and i["severity"] == "critical"
            for i in issues
        ), f"expected orphaned_entity_link_targets/critical; got {issues}"

    async def test_claim_count_mismatch_issue_carries_warning_severity(self, db):
        # Build a cluster + a member_of edge but set claim_count to 99 to force a mismatch.
        await db.execute(
            "INSERT INTO projects (id, name) VALUES (?, ?)",
            ["proj_severity_count", "Sev Count Test"],
        )
        await db.execute(
            "INSERT INTO journal (id, type, content, source, project_id) VALUES (?, ?, ?, ?, ?)",
            ["jrn_sev_count", "note", "seed", "executor", "proj_severity_count"],
        )
        await db.execute(
            """INSERT INTO claims (id, source_entry_id, claim_type, content, confidence, project_id)
               VALUES ('clm_sev_count', 'jrn_sev_count', 'observation', 'c', 0.5, 'proj_severity_count')""",
        )
        await db.execute(
            """INSERT INTO evidence_clusters (id, label, claim_count, project_id)
               VALUES ('ecl_sev_count', 'lbl', 99, 'proj_severity_count')""",
        )
        await db.execute(
            """INSERT INTO claim_edges (id, source_claim_id, cluster_id, relation, confidence, project_id)
               VALUES ('clmedge_sev_count', 'clm_sev_count', 'ecl_sev_count', 'member_of', 0.9, 'proj_severity_count')""",
        )
        await db.commit()

        svc = KnowledgePackService(db, project_id="proj_severity_count")
        issues = await svc.check_integrity("proj_severity_count")
        assert any(
            i["category"] == "claim_count_mismatch" and i["severity"] == "warning"
            for i in issues
        ), f"expected claim_count_mismatch/warning; got {issues}"

    async def test_clean_db_returns_empty_issue_list(self, db):
        await db.execute(
            "INSERT INTO projects (id, name) VALUES (?, ?)",
            ["proj_severity_clean", "Sev Clean Test"],
        )
        await db.commit()
        svc = KnowledgePackService(db, project_id="proj_severity_clean")
        issues = await svc.check_integrity("proj_severity_clean")
        assert issues == []

    async def test_entity_link_endpoint_must_match_declared_type(self, db):
        await db.execute(
            "INSERT INTO projects (id, name) VALUES (?, ?)",
            ["proj_typed_edge", "Typed Edge Test"],
        )
        await db.execute(
            """INSERT INTO journal
               (id, type, content, source, project_id)
               VALUES ('jrn_typed_edge', 'note', 'seed', 'executor',
                       'proj_typed_edge')"""
        )
        await db.execute(
            """INSERT INTO entity_links
               (id, source_type, source_id, link_type, target_type, target_id,
                project_id)
               VALUES ('lnk_wrong_declared_type', 'journal', 'jrn_typed_edge',
                       'references', 'decision', 'jrn_typed_edge',
                       'proj_typed_edge')"""
        )
        await db.commit()

        issues = await KnowledgePackService(
            db, project_id="proj_typed_edge"
        ).check_integrity("proj_typed_edge")
        assert any(
            issue["category"] == "orphaned_entity_link_targets"
            and "lnk_wrong_declared_type" in issue["ids"]
            for issue in issues
        )

    async def test_entity_link_endpoint_must_belong_to_edge_project(self, db):
        await db.execute(
            "INSERT INTO projects (id, name) VALUES (?, ?)",
            ["proj_edge_owner", "Edge Owner"],
        )
        await db.execute(
            "INSERT INTO projects (id, name) VALUES (?, ?)",
            ["proj_edge_foreign", "Edge Foreign"],
        )
        await db.execute(
            """INSERT INTO journal
               (id, type, content, source, project_id)
               VALUES ('jrn_edge_owner', 'note', 'seed', 'executor',
                       'proj_edge_owner')"""
        )
        await db.execute(
            """INSERT INTO decisions
               (id, phase, question, decided_by, project_id)
               VALUES ('dec_edge_foreign', 'planning', 'Foreign decision?',
                       'pi', 'proj_edge_foreign')"""
        )
        await db.execute(
            """INSERT INTO entity_links
               (id, source_type, source_id, link_type, target_type, target_id,
                project_id)
               VALUES ('lnk_cross_project_target', 'journal', 'jrn_edge_owner',
                       'references', 'decision', 'dec_edge_foreign',
                       'proj_edge_owner')"""
        )
        await db.commit()

        issues = await KnowledgePackService(
            db, project_id="proj_edge_owner"
        ).check_integrity("proj_edge_owner")
        assert any(
            issue["category"] == "orphaned_entity_link_targets"
            and "lnk_cross_project_target" in issue["ids"]
            for issue in issues
        )

    async def test_claim_edge_endpoints_must_belong_to_edge_project(self, db):
        for project_id, name in (
            ("proj_claim_edge_owner", "Claim Edge Owner"),
            ("proj_claim_edge_foreign", "Claim Edge Foreign"),
        ):
            await db.execute(
                "INSERT INTO projects (id, name) VALUES (?, ?)",
                [project_id, name],
            )
            await db.execute(
                """INSERT INTO journal
                   (id, type, content, source, project_id)
                   VALUES (?, 'note', 'seed', 'executor', ?)""",
                [f"jrn_{project_id}", project_id],
            )
            await db.execute(
                """INSERT INTO claims
                   (id, source_entry_id, claim_type, content, confidence,
                    project_id)
                   VALUES (?, ?, 'observation', 'claim', 0.5, ?)""",
                [
                    f"clm_{project_id}",
                    f"jrn_{project_id}",
                    project_id,
                ],
            )
        await db.execute(
            """INSERT INTO claim_edges
               (id, source_claim_id, target_claim_id, relation, confidence,
                project_id)
               VALUES ('clmedge_cross_project_source',
                       'clm_proj_claim_edge_foreign',
                       'clm_proj_claim_edge_owner', 'supports', 0.8,
                       'proj_claim_edge_owner')"""
        )
        await db.execute(
            """INSERT INTO claim_edges
               (id, source_claim_id, target_claim_id, relation, confidence,
                project_id)
               VALUES ('clmedge_cross_project_target',
                       'clm_proj_claim_edge_owner',
                       'clm_proj_claim_edge_foreign', 'supports', 0.8,
                       'proj_claim_edge_owner')"""
        )
        await db.commit()

        issues = await KnowledgePackService(
            db, project_id="proj_claim_edge_owner"
        ).check_integrity("proj_claim_edge_owner")
        assert any(
            issue["category"] == "orphaned_claim_edge_sources"
            and "clmedge_cross_project_source" in issue["ids"]
            for issue in issues
        )
        assert any(
            issue["category"] == "orphaned_claim_edge_targets"
            and "clmedge_cross_project_target" in issue["ids"]
            for issue in issues
        )

    async def test_member_edge_cluster_must_belong_to_edge_project(self, db):
        for project_id, name in (
            ("proj_member_owner", "Member Owner"),
            ("proj_member_foreign", "Member Foreign"),
        ):
            await db.execute(
                "INSERT INTO projects (id, name) VALUES (?, ?)",
                [project_id, name],
            )
        await db.execute(
            """INSERT INTO journal
               (id, type, content, source, project_id)
               VALUES ('jrn_member_owner', 'note', 'seed', 'executor',
                       'proj_member_owner')"""
        )
        await db.execute(
            """INSERT INTO claims
               (id, source_entry_id, claim_type, content, confidence,
                project_id)
               VALUES ('clm_member_owner', 'jrn_member_owner', 'observation',
                       'claim', 0.5, 'proj_member_owner')"""
        )
        await db.execute(
            """INSERT INTO evidence_clusters
               (id, label, project_id)
               VALUES ('ecl_member_foreign', 'foreign',
                       'proj_member_foreign')"""
        )
        await db.execute(
            """INSERT INTO claim_edges
               (id, source_claim_id, cluster_id, relation, confidence,
                project_id)
               VALUES ('clmedge_cross_project_cluster', 'clm_member_owner',
                       'ecl_member_foreign', 'member_of', 0.8,
                       'proj_member_owner')"""
        )
        await db.commit()

        issues = await KnowledgePackService(
            db, project_id="proj_member_owner"
        ).check_integrity("proj_member_owner")
        assert any(
            issue["category"] == "orphaned_claim_edge_clusters"
            and "clmedge_cross_project_cluster" in issue["ids"]
            for issue in issues
        )


class TestImportRollbackUsesSeverityField:
    """The rollback gate in import_pack must read severity, not a
    hardcoded category set. Behavior is the orphan = rollback, mismatch
    = commit pattern Mission A T5 established — exact behavior preserved.
    """

    async def test_orphan_rollback_uses_severity(self, db, tmp_path: Path):
        """Synthetic pack with orphan entity_link → KnowledgePackIntegrityError
        raised; no rows for the target project survive (Mission A T5
        regression check, now flowing through the severity-field gate).
        """
        import json
        import zipfile
        from rka.services.knowledge_pack import (
            KnowledgePackIntegrityError, PACK_SCHEMA_VERSION,
        )

        pack_path = tmp_path / "synthetic-orphan.rka-pack.zip"
        manifest = {
            "pack_format_version": PACK_SCHEMA_VERSION,
            "schema_version": 21,
            "project": {
                "id": "proj_orphan_sev_src", "name": "Orphan Sev Source",
                "description": "synthetic", "created_by": "system",
            },
            "project_state": None,
            "tables": {
                "journal": [{
                    "id": "jrn_sev_orphan", "type": "note",
                    "content": "rollback me.", "source": "pi",
                    "confidence": "tested", "status": "active",
                    "project_id": "proj_orphan_sev_src",
                }],
                "entity_links": [{
                    "id": "lnk_sev_orphan",
                    "source_type": "journal", "source_id": "jrn_sev_orphan",
                    "link_type": "references",
                    "target_type": "decision", "target_id": "dec_does_not_exist",
                    "project_id": "proj_orphan_sev_src",
                }],
            },
            "table_counts": {"journal": 1, "entity_links": 1},
        }
        with zipfile.ZipFile(pack_path, "w", compression=zipfile.ZIP_DEFLATED) as ar:
            ar.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))

        with open(pack_path, "rb") as pf:
            with pytest.raises(KnowledgePackIntegrityError) as excinfo:
                await KnowledgePackService(db).import_pack(
                    pf,
                    project_id="proj_orphan_sev_dst",
                    project_name="Orphan Sev Dest",
                )

        # Issues attached to the exception all have severity=critical.
        for issue in excinfo.value.issues:
            assert issue["severity"] == "critical", (
                f"issue {issue!r} reached the rollback gate without severity=critical"
            )

        # No rows for the target project survived.
        rows = await db.fetchall(
            "SELECT id FROM projects WHERE id = ?", ["proj_orphan_sev_dst"],
        )
        assert rows == []

    async def test_foreign_project_endpoint_cannot_satisfy_import(
        self, db, tmp_path: Path
    ):
        """A globally existing id cannot validate an imported local edge."""
        import json
        import zipfile
        from rka.services.knowledge_pack import (
            KnowledgePackIntegrityError,
            PACK_SCHEMA_VERSION,
        )

        await db.execute(
            """INSERT INTO projects (id, name)
               VALUES ('proj_foreign_edge_existing', 'Foreign Existing')"""
        )
        await db.execute(
            """INSERT INTO decisions
               (id, phase, question, decided_by, project_id)
               VALUES ('dec_foreign_edge_existing', 'planning',
                       'Foreign endpoint?', 'pi',
                       'proj_foreign_edge_existing')"""
        )
        await db.commit()

        pack_path = tmp_path / "foreign-endpoint.rka-pack.zip"
        manifest = {
            "pack_format_version": PACK_SCHEMA_VERSION,
            "schema_version": 36,
            "project": {
                "id": "proj_foreign_edge_src",
                "name": "Foreign Edge Source",
                "description": "synthetic",
                "created_by": "system",
            },
            "project_state": None,
            "tables": {
                "journal": [{
                    "id": "jrn_foreign_edge_src",
                    "type": "note",
                    "content": "source",
                    "source": "pi",
                    "confidence": "tested",
                    "status": "active",
                    "project_id": "proj_foreign_edge_src",
                }],
                "entity_links": [{
                    "id": "lnk_foreign_edge",
                    "source_type": "journal",
                    "source_id": "jrn_foreign_edge_src",
                    "link_type": "references",
                    "target_type": "decision",
                    "target_id": "dec_foreign_edge_existing",
                    "project_id": "proj_foreign_edge_src",
                }],
            },
            "table_counts": {"journal": 1, "entity_links": 1},
        }
        with zipfile.ZipFile(
            pack_path, "w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            archive.writestr(
                "manifest.json", json.dumps(manifest, indent=2, sort_keys=True)
            )

        with open(pack_path, "rb") as pack_file:
            with pytest.raises(KnowledgePackIntegrityError) as exc_info:
                await KnowledgePackService(db).import_pack(
                    pack_file,
                    project_id="proj_foreign_edge_dst",
                    project_name="Foreign Edge Destination",
                )

        assert any(
            issue["category"] == "orphaned_entity_link_targets"
            for issue in exc_info.value.issues
        )
        assert await db.fetchone(
            """SELECT id FROM decisions
               WHERE id = 'dec_foreign_edge_existing'
                 AND project_id = 'proj_foreign_edge_existing'"""
        ) == {"id": "dec_foreign_edge_existing"}
        assert await db.fetchone(
            "SELECT 1 FROM projects WHERE id = 'proj_foreign_edge_dst'"
        ) is None
