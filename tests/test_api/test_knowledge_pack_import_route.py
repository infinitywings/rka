"""Test for Affordance G (Mission B / mis_01KR209WY4M6WQFEXRH79KC2ZF):
KnowledgePackIntegrityError surfaces as HTTP 422 with structured issues
body via POST /api/projects/import.

Verified shape:
  {
    "error": "knowledge_pack_integrity_failed",
    "detail": "<exception message>",
    "issues": [
      {"category": "...", "severity": "critical", "count": …, "ids": [...], ...},
      ...
    ],
    "hint": "..."
  }

Pre-Affordance-G behavior was a generic 500 with no structured body.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from rka.api.app import create_app
from rka.config import RKAConfig
from rka.services.knowledge_pack import PACK_SCHEMA_VERSION


PROJECT_ID = "proj_default"
HEADERS = {"X-RKA-Project": PROJECT_ID}


@pytest_asyncio.fixture
async def api_client(tmp_path: Path):
    config = RKAConfig(
        project_dir=tmp_path,
        db_path=Path("kp_import_route.db"),
        llm_enabled=False,
        embeddings_enabled=False,
    )
    app = create_app(config)
    lifespan = app.router.lifespan_context(app)
    await lifespan.__aenter__()
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client
    finally:
        await lifespan.__aexit__(None, None, None)


def _build_pack(tables: dict, source_id: str = "proj_kpg_src",
                source_name: str = "Affordance G Source") -> bytes:
    manifest = {
        "pack_format_version": PACK_SCHEMA_VERSION,
        "schema_version": 21,
        "project": {
            "id": source_id, "name": source_name,
            "description": "synthetic test pack",
            "created_by": "system",
        },
        "project_state": None,
        "tables": tables,
        "table_counts": {k: len(v) for k, v in tables.items()},
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as ar:
        ar.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))
    buf.seek(0)
    return buf.read()


class TestKnowledgePackIntegrityIs422:
    @pytest.mark.asyncio
    async def test_orphan_entity_link_returns_422(self, api_client: httpx.AsyncClient):
        """Synthetic pack with an orphan entity_link target → 422 with
        structured issues body. The issues list carries severity=critical
        and the orphaned_entity_link_targets category."""
        pack_bytes = _build_pack(tables={
            "journal": [{
                "id": "jrn_kpg_orphan", "type": "note",
                "content": "rollback me.", "source": "pi",
                "confidence": "tested", "status": "active",
                "project_id": "proj_kpg_src",
            }],
            "entity_links": [{
                "id": "lnk_kpg_orphan",
                "source_type": "journal", "source_id": "jrn_kpg_orphan",
                "link_type": "references",
                "target_type": "decision", "target_id": "dec_does_not_exist_xyz",
                "project_id": "proj_kpg_src",
            }],
        })
        files = {"file": ("test.rka-pack.zip", pack_bytes, "application/zip")}
        data = {"project_id": "proj_kpg_dst_orphan", "project_name": "KPG Dst Orphan"}
        r = await api_client.post(
            "/api/projects/import", files=files, data=data, headers=HEADERS,
        )
        assert r.status_code == 422, r.text
        body = r.json()
        assert body["error"] == "knowledge_pack_integrity_failed"
        assert "detail" in body
        assert "issues" in body
        issues = body["issues"]
        assert len(issues) >= 1
        for issue in issues:
            assert "category" in issue
            assert "severity" in issue
            assert issue["severity"] == "critical"
        cats = {issue["category"] for issue in issues}
        assert "orphaned_entity_link_targets" in cats
        assert "hint" in body

    @pytest.mark.asyncio
    async def test_unknown_entity_type_returns_400_not_422(self, api_client: httpx.AsyncClient):
        """Sanity: only KnowledgePackIntegrityError is mapped to 422.
        Other malformed-pack errors (ValueError) keep their existing 400."""
        # Pack manifest missing the required 'project' field.
        manifest = {
            "pack_format_version": PACK_SCHEMA_VERSION,
            "schema_version": 21,
            "tables": {},
        }
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as ar:
            ar.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))
        buf.seek(0)
        files = {"file": ("bad.rka-pack.zip", buf.read(), "application/zip")}
        data = {"project_id": "proj_kpg_dst_bad", "project_name": "KPG Dst Bad"}
        r = await api_client.post(
            "/api/projects/import", files=files, data=data, headers=HEADERS,
        )
        # ValueError → existing 400/409 handler, NOT the new 422.
        assert r.status_code != 422
        assert r.status_code in (400, 409)
