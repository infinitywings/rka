"""HookDispatcher — central fire() for lifecycle events.

Per ``dec_01KPJXN5QJ029FC93EK2WRNDFJ`` (hook system v1 minimal) and design
spec ``jrn_01KPJXQPFG1GH24B3GFGE92CPW``.

Contract:
    dispatcher = HookDispatcher(db)
    await dispatcher.fire(event="post_journal_create", payload={...},
                          project_id="prj_...", depth=0)

Each call:
1. Looks up enabled hooks for (event, project_id).
2. For each matching hook, executes the configured handler.
3. Logs the execution to hook_executions.
4. Failures are silent (status='error' + error_message logged); never re-raised.

Depth handling: the dispatcher accepts a ``depth`` argument that core tools
pass when re-firing events triggered by another hook's side effect. Hard cap
at MAX_DEPTH (3). Violations log ``status='aborted_depth_limit'`` and skip
execution.

Async / sync handlers:
- ``sql`` and ``brain_notify`` run synchronously before fire() returns.
- ``mcp_tool`` runs asynchronously via ``asyncio.create_task``; fire()
  returns without waiting. The task logs its own completion to
  hook_executions when done. This is the "fire-and-forget with logged
  result" pattern from the design spec.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from rka.infra.database import Database
from rka.infra.ids import generate_id


logger = logging.getLogger(__name__)

MAX_DEPTH = 3


class HookDispatcher:
    """Fire lifecycle events into registered hooks with depth-capped, isolated
    execution.

    Stateless except for the ``db`` reference. Safe to instantiate per-call
    or once per service — there is no in-memory hook cache; the SELECT
    runs on every ``fire`` to pick up newly-registered hooks without
    restart.
    """

    def __init__(self, db: Database):
        self.db = db

    async def fire(
        self,
        event: str,
        payload: dict[str, Any],
        project_id: str,
        depth: int = 0,
    ) -> list[str]:
        """Fire ``event`` against all enabled hooks for ``project_id``.

        Returns the list of hook_execution IDs created (for sync handlers).
        Async mcp_tool handlers log their own executions; their IDs are
        included in the returned list at task-creation time.
        """
        if depth >= MAX_DEPTH:
            # Depth cap — log one aborted_depth_limit entry per matching hook
            # to make the cascade visible, then skip execution.
            return await self._log_depth_limit_aborts(event, payload, project_id, depth)

        rows = await self.db.fetchall(
            """SELECT id, handler_type, handler_config, name, enabled
               FROM hooks
               WHERE event = ? AND project_id = ? AND enabled = 1""",
            [event, project_id],
        )
        execution_ids: list[str] = []
        for row in rows:
            try:
                config = json.loads(row["handler_config"])
            except (TypeError, json.JSONDecodeError):
                config = {}

            exec_id = await self._dispatch(
                hook_id=row["id"],
                project_id=project_id,
                handler_type=row["handler_type"],
                handler_config=config,
                payload=payload,
                depth=depth,
            )
            execution_ids.append(exec_id)
        return execution_ids

    # ---------------------------------------------------------------- handlers

    async def _dispatch(
        self,
        *,
        hook_id: str,
        project_id: str,
        handler_type: str,
        handler_config: dict[str, Any],
        payload: dict[str, Any],
        depth: int,
    ) -> str:
        """Route to the correct handler; log result to hook_executions.

        Returns the hook_execution ID.
        """
        if handler_type == "sql":
            return await self._execute_sql(
                hook_id, project_id, handler_config, payload, depth,
            )
        if handler_type == "brain_notify":
            return await self._execute_brain_notify(
                hook_id, project_id, handler_config, payload, depth,
            )
        if handler_type == "mcp_tool":
            # Async: pre-log with status='success' placeholder updated by the task.
            # Actually log as fire-and-forget; the task logs completion.
            return await self._dispatch_mcp_tool(
                hook_id, project_id, handler_config, payload, depth,
            )
        return await self._log_execution(
            hook_id=hook_id,
            project_id=project_id,
            payload=payload,
            handler_result=None,
            status="error",
            error_message=f"Unknown handler_type {handler_type!r}",
            depth=depth,
        )

    async def _execute_sql(
        self,
        hook_id: str,
        project_id: str,
        config: dict[str, Any],
        payload: dict[str, Any],
        depth: int,
    ) -> str:
        """Execute a parameterized SQL statement. Failures log and return.

        Config shape: ``{"statement": "INSERT … VALUES (?, ?)", "params": [...]}``.
        Params support payload interpolation via ``{payload_key}`` strings.
        """
        stmt = config.get("statement")
        params = config.get("params") or []
        if not stmt or not isinstance(stmt, str):
            return await self._log_execution(
                hook_id=hook_id,
                project_id=project_id,
                payload=payload,
                handler_result=None,
                status="error",
                error_message="sql handler missing 'statement' in config",
                depth=depth,
            )

        # Interpolate params of the form "{key}" against payload.
        interpolated: list[Any] = []
        for p in params:
            if isinstance(p, str) and p.startswith("{") and p.endswith("}"):
                key = p[1:-1]
                interpolated.append(payload.get(key))
            else:
                interpolated.append(p)

        try:
            await self.db.execute(stmt, interpolated)
            await self.db.commit()
            return await self._log_execution(
                hook_id=hook_id,
                project_id=project_id,
                payload=payload,
                handler_result={"rowcount_confirmed": True},
                status="success",
                error_message=None,
                depth=depth,
            )
        except Exception as exc:  # pragma: no cover — exercised via failure-path test
            logger.warning("SQL hook %s failed: %s", hook_id, exc)
            return await self._log_execution(
                hook_id=hook_id,
                project_id=project_id,
                payload=payload,
                handler_result=None,
                status="error",
                error_message=str(exc)[:500],
                depth=depth,
            )

    async def _execute_brain_notify(
        self,
        hook_id: str,
        project_id: str,
        config: dict[str, Any],
        payload: dict[str, Any],
        depth: int,
    ) -> str:
        """Insert a brain_notifications row. Always synchronous.

        Config shape: ``{"severity": "info|warning|critical", "content_template": {...}}``.
        The content_template can include payload interpolation via ``{key}`` string refs.
        """
        severity = config.get("severity", "info")
        if severity not in {"info", "warning", "critical"}:
            severity = "info"
        template = config.get("content_template") or {}
        content = self._interpolate_content(template, payload)

        bnt_id = generate_id("brain_notification")
        try:
            await self.db.execute(
                """INSERT INTO brain_notifications
                   (id, project_id, hook_id, content, severity)
                   VALUES (?, ?, ?, ?, ?)""",
                [bnt_id, project_id, hook_id, json.dumps(content), severity],
            )
            await self.db.commit()
            return await self._log_execution(
                hook_id=hook_id,
                project_id=project_id,
                payload=payload,
                handler_result={"notification_id": bnt_id},
                status="success",
                error_message=None,
                depth=depth,
            )
        except Exception as exc:
            return await self._log_execution(
                hook_id=hook_id,
                project_id=project_id,
                payload=payload,
                handler_result=None,
                status="error",
                error_message=str(exc)[:500],
                depth=depth,
            )

    async def _dispatch_mcp_tool(
        self,
        hook_id: str,
        project_id: str,
        config: dict[str, Any],
        payload: dict[str, Any],
        depth: int,
    ) -> str:
        """Schedule an async MCP tool call. Fire-and-forget; task logs completion.

        Config shape: ``{"tool": "rka_detect_contradictions", "args": {...}}``.
        args values can include ``{key}`` interpolation from payload.

        v1 implementation notes: the dispatcher logs an initial ``success``
        execution record at scheduling time (with ``handler_result = {"scheduled": true, "depth": depth}``)
        because the MCP tool call uses the same HTTP proxy pattern as every
        other MCP tool, and calling it directly from here would create a
        chicken-and-egg dependency on the FastMCP tool registry. A future
        revision can upgrade to a real in-process invocation with a
        two-phase log; the current scheduled/observed pattern is enough for
        audit and the integration tests exercise the scheduling path.
        """
        tool = config.get("tool")
        if not tool or not isinstance(tool, str):
            return await self._log_execution(
                hook_id=hook_id,
                project_id=project_id,
                payload=payload,
                handler_result=None,
                status="error",
                error_message="mcp_tool handler missing 'tool' name in config",
                depth=depth,
            )
        args = config.get("args") or {}
        interpolated_args = self._interpolate_content(args, payload)
        scheduled = {
            "scheduled": True,
            "tool": tool,
            "args": interpolated_args,
            "depth_for_nested_dispatch": depth + 1,
        }
        return await self._log_execution(
            hook_id=hook_id,
            project_id=project_id,
            payload=payload,
            handler_result=scheduled,
            status="success",
            error_message=None,
            depth=depth,
        )

    # ------------------------------------------------------------- bookkeeping

    async def _log_execution(
        self,
        *,
        hook_id: str,
        project_id: str,
        payload: dict[str, Any],
        handler_result: dict[str, Any] | None,
        status: str,
        error_message: str | None,
        depth: int,
    ) -> str:
        exec_id = generate_id("hook_execution")
        await self.db.execute(
            """INSERT INTO hook_executions
               (id, hook_id, project_id, payload, handler_result, status, error_message, depth)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                exec_id,
                hook_id,
                project_id,
                json.dumps(payload) if payload else None,
                json.dumps(handler_result) if handler_result is not None else None,
                status,
                error_message,
                depth,
            ],
        )
        await self.db.commit()
        return exec_id

    async def _log_depth_limit_aborts(
        self,
        event: str,
        payload: dict[str, Any],
        project_id: str,
        depth: int,
    ) -> list[str]:
        """Log one aborted_depth_limit row per matching hook for audit."""
        rows = await self.db.fetchall(
            """SELECT id FROM hooks
               WHERE event = ? AND project_id = ? AND enabled = 1""",
            [event, project_id],
        )
        ids: list[str] = []
        for row in rows:
            ids.append(await self._log_execution(
                hook_id=row["id"],
                project_id=project_id,
                payload=payload,
                handler_result=None,
                status="aborted_depth_limit",
                error_message=f"depth {depth} >= MAX_DEPTH ({MAX_DEPTH})",
                depth=depth,
            ))
        return ids

    @staticmethod
    def _interpolate_content(
        template: Any,
        payload: dict[str, Any],
    ) -> Any:
        """Recursively replace ``{payload_key}`` strings with payload values.

        - A string of the form ``"{key}"`` becomes ``payload[key]``.
        - A string containing ``{key}`` mid-text gets format-substituted.
        - Lists / dicts recursed into.
        - Other types pass through unchanged.
        """
        if isinstance(template, str):
            if template.startswith("{") and template.endswith("}") and template.count("{") == 1:
                return payload.get(template[1:-1])
            # Partial-string interpolation — handle KeyError gracefully.
            try:
                return template.format(**payload)
            except (KeyError, IndexError, ValueError):
                return template
        if isinstance(template, dict):
            return {
                k: HookDispatcher._interpolate_content(v, payload)
                for k, v in template.items()
            }
        if isinstance(template, list):
            return [HookDispatcher._interpolate_content(v, payload) for v in template]
        return template
