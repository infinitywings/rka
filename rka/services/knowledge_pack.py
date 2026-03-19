"""Project knowledge-pack export/import service."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any, BinaryIO

from rka import __version__ as _rka_version
from rka.infra.ids import generate_id
from rka.models.knowledge_pack import KnowledgePackImportResult
from rka.services.base import BaseService, _now

PACK_SCHEMA_VERSION = 1
PACK_FILE_SUFFIX = ".rka-pack.zip"
_PROJECT_TABLES = (
    "literature",
    "missions",
    "decisions",
    "journal",
    "checkpoints",
    "artifacts",
    "figures",
    "exploration_summaries",
    "qa_sessions",
    "qa_logs",
    "events",
    "audit_log",
    "tags",
    "bootstrap_log",
    "entity_links",
    "keynodes",
    "graph_views",
)
_INSERT_ORDER = (
    "literature",
    "decisions",
    "missions",
    "journal",
    "checkpoints",
    "artifacts",
    "figures",
    "qa_sessions",
    "qa_logs",
    "events",
    "audit_log",
    "tags",
    "bootstrap_log",
    "entity_links",
    "exploration_summaries",
    "keynodes",
    "graph_views",
)
_SELF_REFERENTIAL_TABLES: dict[str, str | list[str]] = {
    "missions": ["depends_on", "parent_mission_id"],
    "decisions": ["parent_id", "superseded_by"],
    "journal": "supersedes",
    "events": "caused_by_event",
}
_ID_ENTITY_TYPES = {
    "literature": "literature",
    "missions": "mission",
    "decisions": "decision",
    "journal": "journal",
    "checkpoints": "checkpoint",
    "artifacts": "artifact",
    "figures": "figure",
    "exploration_summaries": "summary",
    "qa_sessions": "qa_session",
    "qa_logs": "qa_log",
    "events": "event",
    "entity_links": "link",
    "keynodes": "keynode",
    "graph_views": "graphview",
}
_DIRECT_ID_COLUMNS = {
    "literature": ("id",),
    "missions": ("id", "depends_on", "parent_mission_id", "motivated_by_decision"),
    "decisions": ("id", "parent_id", "superseded_by"),
    "journal": ("id", "related_mission", "supersedes", "superseded_by"),
    "checkpoints": ("id", "mission_id", "linked_decision_id"),
    "artifacts": ("id",),
    "figures": ("id", "artifact_id"),
    "exploration_summaries": ("id", "scope_id"),
    "qa_sessions": ("id",),
    "qa_logs": ("id", "session_id"),
    "events": ("id", "entity_id", "caused_by_event", "caused_by_entity"),
    "audit_log": ("entity_id",),
    "tags": ("entity_id",),
    "bootstrap_log": ("entity_id",),
    "entity_links": ("id", "source_id", "target_id"),
    "keynodes": ("id",),
    "graph_views": ("id",),
}
_JSON_ID_COLUMNS = {
    "literature": ("related_decisions",),
    "decisions": ("related_missions", "related_literature", "related_journal"),
    "journal": ("related_decisions", "related_literature"),
    "exploration_summaries": ("source_refs",),
    "qa_logs": ("answer_structured", "sources"),
    "events": ("details",),
    "audit_log": ("details",),
    "keynodes": ("node_refs",),
    "graph_views": ("nodes", "edges"),
}


class KnowledgePackService(BaseService):
    """Export and import a full project-scoped knowledge pack."""

    async def export_pack(self, project_id: str | None = None) -> tuple[str, str]:
        resolved_project_id = self._resolve_project_id(project_id)
        project = await self.db.fetchone(
            "SELECT * FROM projects WHERE id = ?",
            [resolved_project_id],
        )
        if project is None:
            raise ValueError(f"Project '{resolved_project_id}' not found")

        project_state = await self.db.fetchone(
            "SELECT * FROM project_states WHERE project_id = ?",
            [resolved_project_id],
        )

        manifest: dict[str, Any] = {
            "schema_version": PACK_SCHEMA_VERSION,
            "exported_at": _now(),
            "rka_version": _rka_version,
            "project": dict(project),
            "project_state": dict(project_state) if project_state else None,
            "tables": {},
        }

        temp_file = tempfile.NamedTemporaryFile(
            prefix=f"{self._slugify(project['name'] or resolved_project_id)}-",
            suffix=PACK_FILE_SUFFIX,
            delete=False,
        )
        temp_path = Path(temp_file.name)
        temp_file.close()

        with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for table in _PROJECT_TABLES:
                rows = await self._export_rows_for_table(table, resolved_project_id)
                if table == "artifacts":
                    rows = self._attach_artifact_files(rows, archive)
                manifest["tables"][table] = rows
            archive.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))

        filename = f"{self._slugify(project['name'] or resolved_project_id)}{PACK_FILE_SUFFIX}"
        return str(temp_path), filename

    async def import_pack(
        self,
        fileobj: BinaryIO,
        project_id: str | None = None,
        project_name: str | None = None,
    ) -> KnowledgePackImportResult:
        with zipfile.ZipFile(fileobj) as archive:
            manifest = self._load_manifest(archive)
            source_project = manifest["project"]
            source_state = manifest.get("project_state")
            source_tables: dict[str, list[dict[str, Any]]] = manifest.get("tables", {})

            target_project_id = (project_id or source_project["id"]).strip()
            target_project_name = (project_name or source_project["name"]).strip()
            target_description = source_project.get("description")
            if not target_project_id:
                raise ValueError("Imported project ID cannot be empty")
            if not target_project_name:
                raise ValueError("Imported project name cannot be empty")

            await self._assert_target_project_available(target_project_id, target_project_name)
            self._assert_no_duplicate_pack_dois(source_tables)
            tables = self._remap_tables(
                source_tables,
                source_project_id=source_project["id"],
                target_project_id=target_project_id,
            )

            artifact_root = self._artifact_import_root(target_project_id)
            created_root = False

            await self.db.execute("BEGIN")
            try:
                await self._insert_row(
                    "projects",
                    {
                        "id": target_project_id,
                        "name": target_project_name,
                        "description": target_description,
                        "created_by": source_project.get("created_by"),
                        "created_at": source_project.get("created_at") or _now(),
                        "updated_at": source_project.get("updated_at") or _now(),
                    },
                )

                state_row = self._build_project_state_row(
                    source_state=source_state,
                    source_project=source_project,
                    target_project_id=target_project_id,
                    target_project_name=target_project_name,
                    target_description=target_description,
                )
                await self._insert_row("project_states", state_row)

                imported_counts: dict[str, int] = {}
                artifact_files_restored = 0

                for table in _INSERT_ORDER:
                    rows = [dict(row) for row in tables.get(table, [])]
                    rows = self._prepare_rows_for_insert(table, rows, target_project_id)

                    if table == "artifacts":
                        created_root = created_root or bool(rows)
                        rows, restored = self._restore_artifact_files(rows, archive, artifact_root)
                        artifact_files_restored += restored

                    for row in rows:
                        await self._insert_row(table, row)

                    imported_counts[table] = len(rows)

                await self.db.commit()
            except Exception:
                await self.db.execute("ROLLBACK")
                if created_root and artifact_root.exists():
                    shutil.rmtree(artifact_root.parent, ignore_errors=True)
                raise

        await self._sync_imported_indexes(tables)

        return KnowledgePackImportResult(
            project_id=target_project_id,
            project_name=target_project_name,
            source_project_id=source_project["id"],
            imported_counts=imported_counts,
            artifact_files_restored=artifact_files_restored,
        )

    async def _export_rows_for_table(self, table: str, project_id: str) -> list[dict[str, Any]]:
        if table == "qa_logs":
            return await self.db.fetchall(
                """SELECT qa_logs.*
                   FROM qa_logs
                   INNER JOIN qa_sessions ON qa_sessions.id = qa_logs.session_id
                   WHERE qa_sessions.project_id = ?
                   ORDER BY qa_logs.created_at, qa_logs.id""",
                [project_id],
            )
        return await self.db.fetchall(
            f"SELECT * FROM {table} WHERE project_id = ? ORDER BY rowid",
            [project_id],
        )

    def _attach_artifact_files(
        self,
        rows: list[dict[str, Any]],
        archive: zipfile.ZipFile,
    ) -> list[dict[str, Any]]:
        enriched: list[dict[str, Any]] = []
        for row in rows:
            artifact = dict(row)
            filepath = artifact.get("filepath")
            pack_file = None
            if filepath:
                path = Path(filepath)
                if path.exists() and path.is_file():
                    safe_name = self._safe_filename(path.name)
                    pack_file = f"artifacts/{artifact['id']}/{safe_name}"
                    archive.write(path, pack_file)
            artifact["pack_file"] = pack_file
            enriched.append(artifact)
        return enriched

    def _load_manifest(self, archive: zipfile.ZipFile) -> dict[str, Any]:
        try:
            raw_manifest = archive.read("manifest.json")
        except KeyError as exc:
            raise ValueError("Knowledge pack is missing manifest.json") from exc
        try:
            manifest = json.loads(raw_manifest.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("Knowledge pack manifest is not valid JSON") from exc

        if manifest.get("schema_version") != PACK_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported knowledge pack schema version: {manifest.get('schema_version')}"
            )
        if not manifest.get("project"):
            raise ValueError("Knowledge pack manifest is missing project metadata")
        return manifest

    async def _assert_target_project_available(self, project_id: str, project_name: str) -> None:
        existing_id = await self.db.fetchone("SELECT id FROM projects WHERE id = ?", [project_id])
        if existing_id:
            raise ValueError(f"Project '{project_id}' already exists")

        existing_name = await self.db.fetchone("SELECT id FROM projects WHERE name = ?", [project_name])
        if existing_name:
            raise ValueError(
                f"Project name '{project_name}' already exists. Choose a different import name."
            )

    def _assert_no_duplicate_pack_dois(self, tables: dict[str, list[dict[str, Any]]]) -> None:
        dois = [str(row["doi"]).strip() for row in tables.get("literature", []) if row.get("doi")]
        duplicate_dois = sorted(doi for doi, count in Counter(dois).items() if count > 1)
        if duplicate_dois:
            sample = ", ".join(duplicate_dois[:5])
            raise ValueError(
                f"Knowledge pack contains duplicate literature DOI(s): {sample}"
            )

    def _remap_tables(
        self,
        tables: dict[str, list[dict[str, Any]]],
        *,
        source_project_id: str,
        target_project_id: str,
    ) -> dict[str, list[dict[str, Any]]]:
        id_map = self._build_id_map(tables)
        remapped: dict[str, list[dict[str, Any]]] = {}
        for table in _PROJECT_TABLES:
            remapped[table] = [
                self._remap_row(
                    table,
                    row,
                    id_map=id_map,
                    source_project_id=source_project_id,
                    target_project_id=target_project_id,
                )
                for row in tables.get(table, [])
            ]
        return remapped

    def _build_id_map(self, tables: dict[str, list[dict[str, Any]]]) -> dict[str, str]:
        id_map: dict[str, str] = {}
        for table, entity_type in _ID_ENTITY_TYPES.items():
            for row in tables.get(table, []):
                row_id = row.get("id")
                if row_id:
                    id_map[str(row_id)] = generate_id(entity_type)
        return id_map

    def _remap_row(
        self,
        table: str,
        row: dict[str, Any],
        *,
        id_map: dict[str, str],
        source_project_id: str,
        target_project_id: str,
    ) -> dict[str, Any]:
        remapped = dict(row)
        if "project_id" in remapped:
            remapped["project_id"] = target_project_id
        if table == "qa_logs":
            remapped.pop("project_id", None)

        for column in _DIRECT_ID_COLUMNS.get(table, ()):
            if remapped.get(column):
                remapped[column] = self._rewrite_direct_ref(
                    table=table,
                    column=column,
                    value=remapped[column],
                    id_map=id_map,
                    source_project_id=source_project_id,
                    target_project_id=target_project_id,
                    scope_type=remapped.get("scope_type"),
                    entity_type=remapped.get("entity_type"),
                )

        for column in _JSON_ID_COLUMNS.get(table, ()):
            if remapped.get(column):
                remapped[column] = self._rewrite_json_refs(
                    remapped[column],
                    id_map=id_map,
                    source_project_id=source_project_id,
                    target_project_id=target_project_id,
                )

        return remapped

    def _rewrite_direct_ref(
        self,
        *,
        table: str,
        column: str,
        value: Any,
        id_map: dict[str, str],
        source_project_id: str,
        target_project_id: str,
        scope_type: str | None = None,
        entity_type: str | None = None,
    ) -> Any:
        if not isinstance(value, str):
            return value

        if table == "exploration_summaries" and column == "scope_id":
            if scope_type == "project" and value == source_project_id:
                return target_project_id
            if scope_type in {"mission", "decision", "journal", "literature", "checkpoint", "summary"}:
                return id_map.get(value, value)
            return value

        if table in {"events", "audit_log"} and column == "entity_id":
            if entity_type == "project" and value == source_project_id:
                return target_project_id

        if value == source_project_id:
            return target_project_id
        return id_map.get(value, value)

    def _rewrite_json_refs(
        self,
        value: Any,
        *,
        id_map: dict[str, str],
        source_project_id: str,
        target_project_id: str,
    ) -> Any:
        if not isinstance(value, str):
            return value
        try:
            payload = json.loads(value)
        except json.JSONDecodeError:
            return value
        rewritten = self._rewrite_nested_refs(payload, id_map, source_project_id, target_project_id)
        return json.dumps(rewritten)

    def _rewrite_nested_refs(
        self,
        value: Any,
        id_map: dict[str, str],
        source_project_id: str,
        target_project_id: str,
    ) -> Any:
        if isinstance(value, str):
            if value == source_project_id:
                return target_project_id
            return id_map.get(value, value)
        if isinstance(value, list):
            return [
                self._rewrite_nested_refs(item, id_map, source_project_id, target_project_id)
                for item in value
            ]
        if isinstance(value, dict):
            return {
                key: self._rewrite_nested_refs(item, id_map, source_project_id, target_project_id)
                for key, item in value.items()
            }
        return value

    def _build_project_state_row(
        self,
        source_state: dict[str, Any] | None,
        source_project: dict[str, Any],
        target_project_id: str,
        target_project_name: str,
        target_description: str | None,
    ) -> dict[str, Any]:
        phases = None
        if source_state:
            phases = source_state.get("phases_config")
        if not phases:
            phases = json.dumps([
                "literature",
                "planning",
                "data_collection",
                "implementation",
                "evaluation",
                "paper_writing",
            ])
        return {
            "project_id": target_project_id,
            "project_name": target_project_name,
            "project_description": target_description,
            "current_phase": (source_state or {}).get("current_phase"),
            "phases_config": phases,
            "summary": (source_state or {}).get("summary"),
            "blockers": (source_state or {}).get("blockers"),
            "metrics": (source_state or {}).get("metrics"),
            "created_at": (source_state or {}).get("created_at") or source_project.get("created_at") or _now(),
            "updated_at": (source_state or {}).get("updated_at") or source_project.get("updated_at") or _now(),
        }

    def _prepare_rows_for_insert(
        self,
        table: str,
        rows: list[dict[str, Any]],
        target_project_id: str,
    ) -> list[dict[str, Any]]:
        prepared = [self._rewrite_project_scope(table, row, target_project_id) for row in rows]

        dependency_keys = _SELF_REFERENTIAL_TABLES.get(table)
        if dependency_keys:
            keys = [dependency_keys] if isinstance(dependency_keys, str) else list(dependency_keys)
            for key in keys:
                prepared = self._sort_rows_by_dependency(prepared, key)

        if table == "audit_log" or table == "bootstrap_log":
            for row in prepared:
                row.pop("id", None)
        return prepared

    def _rewrite_project_scope(
        self,
        table: str,
        row: dict[str, Any],
        target_project_id: str,
    ) -> dict[str, Any]:
        rewritten = dict(row)
        if "project_id" in rewritten:
            rewritten["project_id"] = target_project_id
        if table == "qa_logs":
            rewritten.pop("project_id", None)
        return rewritten

    def _sort_rows_by_dependency(
        self,
        rows: list[dict[str, Any]],
        dependency_key: str,
    ) -> list[dict[str, Any]]:
        remaining = {str(row["id"]): dict(row) for row in rows if row.get("id")}
        ordered: list[dict[str, Any]] = []
        placed: set[str] = set()

        while remaining:
            progressed = False
            for row_id, row in list(remaining.items()):
                dependency = row.get(dependency_key)
                if not dependency or dependency in placed or dependency not in remaining:
                    ordered.append(row)
                    placed.add(row_id)
                    del remaining[row_id]
                    progressed = True
            if not progressed:
                raise ValueError(
                    f"Cannot import pack because {dependency_key} contains a cycle or unresolved reference"
                )

        return ordered

    def _restore_artifact_files(
        self,
        rows: list[dict[str, Any]],
        archive: zipfile.ZipFile,
        artifact_root: Path,
    ) -> tuple[list[dict[str, Any]], int]:
        restored = 0
        if rows:
            artifact_root.mkdir(parents=True, exist_ok=True)

        prepared: list[dict[str, Any]] = []
        for row in rows:
            artifact = dict(row)
            pack_file = artifact.get("pack_file")
            if pack_file:
                destination = artifact_root / artifact["id"] / self._safe_filename(artifact.get("filename") or "artifact.bin")
                destination.parent.mkdir(parents=True, exist_ok=True)
                try:
                    with archive.open(pack_file) as src, destination.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
                    artifact["filepath"] = str(destination.resolve())
                    restored += 1
                except KeyError as exc:
                    raise ValueError(f"Knowledge pack is missing bundled artifact file '{pack_file}'") from exc
            artifact.pop("pack_file", None)
            prepared.append(artifact)
        return prepared, restored

    async def _insert_row(self, table: str, row: dict[str, Any]) -> None:
        columns = list(row.keys())
        placeholders = ", ".join("?" for _ in columns)
        column_sql = ", ".join(columns)
        await self.db.execute(
            f"INSERT INTO {table} ({column_sql}) VALUES ({placeholders})",
            [row[column] for column in columns],
        )

    async def _sync_imported_indexes(self, tables: dict[str, list[dict[str, Any]]]) -> None:
        for row in tables.get("journal", []):
            await self._sync_indexes("journal", row["id"], row)
        for row in tables.get("decisions", []):
            await self._sync_indexes("decision", row["id"], row)
        for row in tables.get("literature", []):
            await self._sync_indexes("literature", row["id"], row)
        for row in tables.get("missions", []):
            await self._sync_indexes("mission", row["id"], row)

    def _artifact_import_root(self, project_id: str) -> Path:
        db_dir = Path(self.db.db_path).resolve().parent
        return db_dir / "knowledge-packs" / project_id / "artifacts"

    @staticmethod
    def _slugify(value: str) -> str:
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.")
        return slug or "knowledge-pack"

    @staticmethod
    def _safe_filename(value: str) -> str:
        return Path(value).name or "artifact.bin"
