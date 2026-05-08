"""Test for Affordance E (Mission B / mis_01KR209WY4M6WQFEXRH79KC2ZF):
check_integrity issues carry a severity field, and the import_pack
rollback gate reads that field rather than a hardcoded category set.

The 4 orphan-class categories must report severity='critical' (rollback
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
