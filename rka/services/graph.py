"""Graph service — entity relationship queries for the research map."""

from __future__ import annotations

import json
from typing import Any

from rka.infra.database import Database
from rka.infra.ids import generate_id


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

    async def get_graph_view(
        self,
        *,
        view: str = "full",
        include_types: list[str] | None = None,
        phase: str | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        """Return graph payload for different map modes.

        - full: existing entity graph
        - condensed/keynodes: precomputed keynode view (or auto-build if absent)
        """
        if view == "full":
            return await self.get_full_graph(include_types=include_types, phase=phase, limit=limit)

        if view not in {"condensed", "keynodes"}:
            raise ValueError("Unsupported graph view. Use one of: full, condensed, keynodes")

        cached = await self.db.fetchone(
            "SELECT nodes, edges, id, created_at FROM graph_views "
            "WHERE name = ? ORDER BY created_at DESC LIMIT 1",
            ["condensed"],
        )
        if not cached:
            await self.refresh_condensed_view()
            cached = await self.db.fetchone(
                "SELECT nodes, edges, id, created_at FROM graph_views "
                "WHERE name = ? ORDER BY created_at DESC LIMIT 1",
                ["condensed"],
            )

        if not cached:
            return {"nodes": [], "edges": [], "view": view}

        return {
            "view": "condensed",
            "view_id": cached["id"],
            "created_at": cached["created_at"],
            "nodes": json.loads(cached["nodes"] or "[]"),
            "edges": json.loads(cached["edges"] or "[]"),
        }

    async def refresh_condensed_view(
        self,
        *,
        top_per_kind: int = 8,
        min_importance: float = 0.45,
    ) -> dict[str, Any]:
        """Build a condensed keynode-centric graph view and persist it.

        Heuristic ranking is used so this works even without LLM dependencies.
        """
        candidates = await self._collect_keynode_candidates(top_per_kind=top_per_kind)
        selected = [c for c in candidates if c["importance"] >= min_importance]

        await self.db.execute("DELETE FROM keynodes WHERE blessed = 0")

        nodes: list[dict[str, Any]] = []
        ref_to_keynode: dict[tuple[str, str], str] = {}

        for item in selected:
            keynode_id = generate_id("keynode")
            node_refs = [{"entity_type": item["entity_type"], "entity_id": item["entity_id"]}]
            await self.db.execute(
                """INSERT INTO keynodes
                   (id, kind, title, summary, produced_by, importance, node_refs, blessed)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
                [
                    keynode_id,
                    item["kind"],
                    item["title"],
                    item.get("summary"),
                    "system",
                    item["importance"],
                    json.dumps(node_refs),
                ],
            )
            ref_to_keynode[(item["entity_type"], item["entity_id"])] = keynode_id
            nodes.append(
                {
                    "id": keynode_id,
                    "type": item["kind"],
                    "label": item["title"],
                    "importance": item["importance"],
                    "summary": item.get("summary"),
                    "source": {
                        "entity_type": item["entity_type"],
                        "entity_id": item["entity_id"],
                    },
                }
            )

        edges = await self._build_condensed_edges(ref_to_keynode)

        view_id = generate_id("graphview")
        params = {"top_per_kind": top_per_kind, "min_importance": min_importance}
        await self.db.execute(
            """INSERT INTO graph_views (id, name, params, nodes, edges)
               VALUES (?, ?, ?, ?, ?)""",
            [view_id, "condensed", json.dumps(params), json.dumps(nodes), json.dumps(edges)],
        )
        await self.db.commit()

        return {
            "view": "condensed",
            "view_id": view_id,
            "params": params,
            "nodes": nodes,
            "edges": edges,
        }

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

    async def _collect_keynode_candidates(self, *, top_per_kind: int) -> list[dict[str, Any]]:
        """Collect and score likely key nodes for condensed graph mode."""
        candidates: list[dict[str, Any]] = []

        journal_rows = await self.db.fetchall(
            """SELECT id, type, content, summary, confidence, created_at
               FROM journal
               WHERE type IN ('finding', 'insight', 'hypothesis', 'methodology', 'summary')
               ORDER BY created_at DESC
               LIMIT ?""",
            [top_per_kind * 6],
        )
        confidence_bonus = {"verified": 0.28, "tested": 0.18, "hypothesis": 0.10}
        for row in journal_rows:
            imp = 0.48 + confidence_bonus.get((row.get("confidence") or "").lower(), 0.05)
            candidates.append(
                {
                    "kind": "finding",
                    "entity_type": "journal",
                    "entity_id": row["id"],
                    "title": (row.get("summary") or row.get("content") or "Finding")[:90],
                    "summary": (row.get("summary") or row.get("content") or "")[:240],
                    "importance": min(1.0, imp),
                }
            )

        lit_rows = await self.db.fetchall(
            """SELECT id, title, abstract, status, relevance_score, created_at
               FROM literature
               ORDER BY created_at DESC
               LIMIT ?""",
            [top_per_kind * 8],
        )
        status_bonus = {"cited": 0.30, "read": 0.22, "reading": 0.12, "to_read": 0.05}
        for row in lit_rows:
            rel = float(row.get("relevance_score") or 0.0)
            base = 0.40 + status_bonus.get((row.get("status") or "").lower(), 0.04)
            imp = min(1.0, base + max(0.0, min(rel, 1.0)) * 0.25)
            candidates.append(
                {
                    "kind": "literature",
                    "entity_type": "literature",
                    "entity_id": row["id"],
                    "title": (row.get("title") or "Literature")[:90],
                    "summary": (row.get("abstract") or "")[:240],
                    "importance": imp,
                }
            )

        dec_rows = await self.db.fetchall(
            """SELECT id, question, rationale, status, created_at
               FROM decisions
               ORDER BY created_at DESC
               LIMIT ?""",
            [top_per_kind * 5],
        )
        dec_bonus = {"active": 0.30, "merged": 0.20, "revisit": 0.16, "superseded": 0.10, "abandoned": 0.08}
        for row in dec_rows:
            imp = 0.52 + dec_bonus.get((row.get("status") or "").lower(), 0.1)
            candidates.append(
                {
                    "kind": "decision",
                    "entity_type": "decision",
                    "entity_id": row["id"],
                    "title": (row.get("question") or "Decision")[:90],
                    "summary": (row.get("rationale") or "")[:240],
                    "importance": min(1.0, imp),
                }
            )

        mission_rows = await self.db.fetchall(
            """SELECT id, objective, report, status, completed_at, created_at
               FROM missions
               WHERE status IN ('complete', 'partial', 'blocked', 'active')
               ORDER BY COALESCE(completed_at, created_at) DESC
               LIMIT ?""",
            [top_per_kind * 6],
        )
        milestone_bonus = {"complete": 0.35, "partial": 0.26, "blocked": 0.22, "active": 0.16}
        for row in mission_rows:
            imp = 0.42 + milestone_bonus.get((row.get("status") or "").lower(), 0.1)
            candidates.append(
                {
                    "kind": "milestone",
                    "entity_type": "mission",
                    "entity_id": row["id"],
                    "title": (row.get("objective") or "Milestone")[:90],
                    "summary": (row.get("report") or "")[:240],
                    "importance": min(1.0, imp),
                }
            )

        per_kind: dict[str, list[dict[str, Any]]] = {"finding": [], "literature": [], "decision": [], "milestone": []}
        for candidate in candidates:
            per_kind[candidate["kind"]].append(candidate)

        selected: list[dict[str, Any]] = []
        for kind, items in per_kind.items():
            ranked = sorted(items, key=lambda candidate: candidate["importance"], reverse=True)
            selected.extend(ranked[:top_per_kind])
        return selected

    async def _build_condensed_edges(
        self,
        ref_to_keynode: dict[tuple[str, str], str],
    ) -> list[dict[str, Any]]:
        """Aggregate entity links into condensed keynode edges."""
        if not ref_to_keynode:
            return []

        rows = await self.db.fetchall(
            """SELECT source_type, source_id, target_type, target_id, link_type,
                      COALESCE(link_weight, 0.0) as link_weight,
                      link_reason
               FROM entity_links"""
        )

        aggregated: dict[tuple[str, str, str], dict[str, Any]] = {}
        for row in rows:
            source_key = (row["source_type"], row["source_id"])
            target_key = (row["target_type"], row["target_id"])
            src_keynode = ref_to_keynode.get(source_key)
            tgt_keynode = ref_to_keynode.get(target_key)
            if not src_keynode or not tgt_keynode or src_keynode == tgt_keynode:
                continue

            agg_key = (src_keynode, tgt_keynode, row["link_type"])
            current = aggregated.get(agg_key)
            weight = float(row.get("link_weight") or 0.0)
            if current is None:
                aggregated[agg_key] = {
                    "source": src_keynode,
                    "target": tgt_keynode,
                    "link_type": row["link_type"],
                    "weight": max(0.2, weight),
                    "reason": row.get("link_reason") or "Aggregated from linked supporting entities.",
                }
            else:
                current["weight"] = max(current["weight"], weight)

        return list(aggregated.values())

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
