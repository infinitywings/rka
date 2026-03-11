"""Graph service — entity relationship queries for the research map."""

from __future__ import annotations

import json
from typing import Any

from rka.infra.database import Database


class GraphService:
    """Queries the entity_links table and related entities to produce
    graph structures for the research map UI and MCP tools."""

    def __init__(self, db: Database):
        self.db = db

    # ------------------------------------------------------------------
    # Full graph (all entity_links + nodes)
    # ------------------------------------------------------------------

    async def get_full_graph(
        self,
        *,
        include_types: list[str] | None = None,
        phase: str | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        """Return the full knowledge graph as {nodes, edges}.

        Each node: {id, type, label, status?, phase?, created_at}
        Each edge: {source, target, link_type, created_at}
        """
        nodes: dict[str, dict] = {}
        edges: list[dict] = []

        # Fetch all entity links
        link_rows = await self.db.fetchall(
            "SELECT source_type, source_id, link_type, target_type, target_id, created_at "
            "FROM entity_links ORDER BY created_at DESC LIMIT ?",
            [limit],
        )

        # Collect unique entity IDs we need to look up
        entity_ids: dict[str, set[str]] = {}
        for row in link_rows:
            for prefix in ("source", "target"):
                etype = row[f"{prefix}_type"]
                eid = row[f"{prefix}_id"]
                entity_ids.setdefault(etype, set()).add(eid)
            edges.append({
                "source": row["source_id"],
                "target": row["target_id"],
                "link_type": row["link_type"],
                "created_at": row["created_at"],
            })

        # Also include entities that have no links yet (orphans)
        for etype, table, label_col, status_col, has_phase in [
            ("decision", "decisions", "question", "status", True),
            ("mission", "missions", "objective", "status", True),
            ("journal", "journal", "content", "confidence", True),
            ("literature", "literature", "title", "status", False),
            ("checkpoint", "checkpoints", "description", "status", False),
        ]:
            if include_types and etype not in include_types:
                continue
            conditions = []
            params: list = []
            if phase and has_phase:
                conditions.append("phase = ?")
                params.append(phase)
            where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            phase_col = "COALESCE(phase, '') as phase" if has_phase else "'' as phase"
            rows = await self.db.fetchall(
                f"SELECT id, {label_col}, {status_col}, "
                f"{phase_col}, created_at "
                f"FROM {table} {where} ORDER BY created_at DESC LIMIT ?",
                params + [limit],
            )
            for r in rows:
                nid = r["id"]
                label_text = r[label_col] or ""
                nodes[nid] = {
                    "id": nid,
                    "type": etype,
                    "label": label_text[:120],
                    "status": r[status_col],
                    "phase": r.get("phase", ""),
                    "created_at": r["created_at"],
                }
                entity_ids.setdefault(etype, set()).add(nid)

        # Fill in any linked nodes that weren't fetched as orphans
        await self._fill_missing_nodes(nodes, entity_ids)

        # Filter by type if requested
        if include_types:
            nodes = {k: v for k, v in nodes.items() if v["type"] in include_types}
            valid_ids = set(nodes.keys())
            edges = [e for e in edges if e["source"] in valid_ids and e["target"] in valid_ids]

        return {"nodes": list(nodes.values()), "edges": edges}

    # ------------------------------------------------------------------
    # Ego graph (neighborhood of a single entity)
    # ------------------------------------------------------------------

    async def get_ego_graph(self, entity_id: str, depth: int = 1) -> dict[str, Any]:
        """Return the subgraph centered on entity_id up to `depth` hops."""
        visited: set[str] = set()
        frontier: set[str] = {entity_id}
        all_edges: list[dict] = []

        for _ in range(depth):
            if not frontier:
                break
            placeholders = ",".join("?" for _ in frontier)
            rows = await self.db.fetchall(
                f"SELECT source_type, source_id, link_type, target_type, target_id, created_at "
                f"FROM entity_links "
                f"WHERE source_id IN ({placeholders}) OR target_id IN ({placeholders})",
                list(frontier) + list(frontier),
            )
            visited |= frontier
            next_frontier: set[str] = set()
            for row in rows:
                all_edges.append({
                    "source": row["source_id"],
                    "target": row["target_id"],
                    "link_type": row["link_type"],
                    "created_at": row["created_at"],
                })
                for eid in (row["source_id"], row["target_id"]):
                    if eid not in visited:
                        next_frontier.add(eid)
            frontier = next_frontier

        # Deduplicate edges
        seen = set()
        unique_edges = []
        for e in all_edges:
            key = (e["source"], e["target"], e["link_type"])
            if key not in seen:
                seen.add(key)
                unique_edges.append(e)

        # Collect all node IDs
        node_ids: set[str] = {entity_id}
        for e in unique_edges:
            node_ids.add(e["source"])
            node_ids.add(e["target"])

        entity_ids: dict[str, set[str]] = {}
        for nid in node_ids:
            etype = self._guess_type_from_id(nid)
            entity_ids.setdefault(etype, set()).add(nid)

        nodes: dict[str, dict] = {}
        await self._fill_missing_nodes(nodes, entity_ids)

        return {"nodes": list(nodes.values()), "edges": unique_edges}

    # ------------------------------------------------------------------
    # Decision tree (hierarchical)
    # ------------------------------------------------------------------

    async def get_decision_tree(self, root_id: str | None = None) -> list[dict]:
        """Return decisions as a tree structure.

        If root_id is given, return only that subtree.
        Each node: {id, question, chosen, status, phase, children: [...], linked_entities: [...]}
        """
        rows = await self.db.fetchall(
            "SELECT id, parent_id, question, chosen, status, phase, rationale, "
            "related_missions, related_literature, created_at "
            "FROM decisions ORDER BY created_at"
        )

        # Build lookup
        by_id: dict[str, dict] = {}
        for r in rows:
            by_id[r["id"]] = {
                "id": r["id"],
                "parent_id": r["parent_id"],
                "question": r["question"],
                "chosen": r["chosen"],
                "status": r["status"],
                "phase": r["phase"],
                "rationale": r["rationale"],
                "created_at": r["created_at"],
                "children": [],
                "linked_entities": [],
            }

        # Fetch entity_links for decisions
        dec_ids = list(by_id.keys())
        if dec_ids:
            placeholders = ",".join("?" for _ in dec_ids)
            links = await self.db.fetchall(
                f"SELECT source_type, source_id, link_type, target_type, target_id "
                f"FROM entity_links "
                f"WHERE source_id IN ({placeholders}) OR target_id IN ({placeholders})",
                dec_ids + dec_ids,
            )
            for link in links:
                for dec_id in dec_ids:
                    if link["source_id"] == dec_id or link["target_id"] == dec_id:
                        other_id = link["target_id"] if link["source_id"] == dec_id else link["source_id"]
                        other_type = link["target_type"] if link["source_id"] == dec_id else link["source_type"]
                        if dec_id in by_id:
                            by_id[dec_id]["linked_entities"].append({
                                "id": other_id,
                                "type": other_type,
                                "link_type": link["link_type"],
                            })

        # Build tree
        roots: list[dict] = []
        for node in by_id.values():
            pid = node["parent_id"]
            if pid and pid in by_id:
                by_id[pid]["children"].append(node)
            else:
                roots.append(node)

        if root_id and root_id in by_id:
            return [by_id[root_id]]
        return roots

    # ------------------------------------------------------------------
    # Timeline (events + entity_links combined)
    # ------------------------------------------------------------------

    async def get_timeline(
        self,
        phase: str | None = None,
        since: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Return a chronological timeline of events with linked context."""
        conditions = []
        params: list = []
        if phase:
            conditions.append("phase = ?")
            params.append(phase)
        if since:
            conditions.append("timestamp >= ?")
            params.append(since)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)

        rows = await self.db.fetchall(
            f"SELECT id, timestamp, event_type, entity_type, entity_id, actor, "
            f"summary, caused_by_event, phase "
            f"FROM events {where} ORDER BY timestamp DESC LIMIT ?",
            params,
        )
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    async def get_stats(self) -> dict[str, Any]:
        """Return graph statistics: node/edge counts by type."""
        node_counts = {}
        for etype, table in [
            ("decision", "decisions"),
            ("mission", "missions"),
            ("journal", "journal"),
            ("literature", "literature"),
            ("checkpoint", "checkpoints"),
        ]:
            row = await self.db.fetchone(f"SELECT COUNT(*) as cnt FROM {table}")
            node_counts[etype] = row["cnt"] if row else 0

        edge_row = await self.db.fetchone("SELECT COUNT(*) as cnt FROM entity_links")
        total_edges = edge_row["cnt"] if edge_row else 0

        edge_type_rows = await self.db.fetchall(
            "SELECT link_type, COUNT(*) as cnt FROM entity_links GROUP BY link_type"
        )
        edge_counts = {r["link_type"]: r["cnt"] for r in edge_type_rows}

        return {
            "node_counts": node_counts,
            "total_nodes": sum(node_counts.values()),
            "total_edges": total_edges,
            "edge_counts_by_type": edge_counts,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _fill_missing_nodes(
        self, nodes: dict[str, dict], entity_ids: dict[str, set[str]]
    ) -> None:
        """Look up entity metadata for IDs not already in the nodes dict."""
        table_map: dict[str, tuple[str, str, str, bool]] = {
            "decision": ("decisions", "question", "status", True),
            "mission": ("missions", "objective", "status", True),
            "journal": ("journal", "content", "confidence", True),
            "literature": ("literature", "title", "status", False),
            "checkpoint": ("checkpoints", "description", "status", False),
        }
        for etype, ids in entity_ids.items():
            missing = [eid for eid in ids if eid not in nodes]
            if not missing:
                continue
            info = table_map.get(etype)
            if not info:
                for eid in missing:
                    nodes[eid] = {"id": eid, "type": etype, "label": eid, "status": None, "phase": "", "created_at": ""}
                continue
            table, label_col, status_col, has_phase = info
            placeholders = ",".join("?" for _ in missing)
            phase_col = "COALESCE(phase, '') as phase" if has_phase else "'' as phase"
            rows = await self.db.fetchall(
                f"SELECT id, {label_col}, {status_col}, "
                f"{phase_col}, created_at "
                f"FROM {table} WHERE id IN ({placeholders})",
                missing,
            )
            for r in rows:
                label_text = r[label_col] or ""
                nodes[r["id"]] = {
                    "id": r["id"],
                    "type": etype,
                    "label": label_text[:120],
                    "status": r[status_col],
                    "phase": r.get("phase", ""),
                    "created_at": r["created_at"],
                }
            # Any still missing get placeholder nodes
            fetched = {r["id"] for r in rows}
            for eid in missing:
                if eid not in fetched:
                    nodes[eid] = {"id": eid, "type": etype, "label": eid, "status": None, "phase": "", "created_at": ""}

    @staticmethod
    def _guess_type_from_id(entity_id: str) -> str:
        """Guess entity type from ID prefix."""
        prefix_map = {
            "dec": "decision",
            "lit": "literature",
            "jrn": "journal",
            "mis": "mission",
            "chk": "checkpoint",
            "evt": "event",
            "art": "artifact",
            "fig": "figure",
            "sum": "summary",
            "qas": "qa_session",
            "qal": "qa_log",
            "lnk": "link",
        }
        prefix = entity_id.split("_")[0] if "_" in entity_id else ""
        return prefix_map.get(prefix, "unknown")
