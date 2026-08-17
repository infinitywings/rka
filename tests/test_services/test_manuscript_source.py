"""Conflict, recovery, anchor, and path-safety tests for source synchronization."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import stat
import zipfile
from pathlib import Path

import pytest

from rka.config import RKAConfig
from rka.infra.ids import generate_id
from rka.models.manuscript_native import ManuscriptCreate
from rka.models.manuscript_native import ManuscriptUpdate
from rka.models.manuscript_source import (
    ManuscriptSourceProposalCreate,
    ManuscriptSourceProposalTransition,
)
from rka.models.semantic_patch import ContextManifestCreate
from rka.services.manuscript_native import NativeManuscriptService
from rka.services.manuscript_source import (
    ManuscriptSourceConflictError,
    ManuscriptSourceSecurityError,
    ManuscriptSourceService,
)
from rka.services.semantic_patch import SemanticPatchService
from rka.services.knowledge_pack import KnowledgePackService


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


async def _source_fixture(db, tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config = RKAConfig(
        project_dir=tmp_path,
        db_path=tmp_path / "source.db",
        data_dir=tmp_path / "data",
        llm_enabled=False,
        embeddings_enabled=False,
        manuscript_workspace_roots=str(tmp_path),
    )
    native = NativeManuscriptService(db, project_id="proj_default")
    manuscript = await native.create(
        ManuscriptCreate(title="Source paper", workspace_ref=str(workspace))
    )
    context = await native.upsert_argument_spine(
        manuscript.id,
        expected_revision=1,
        spine={
            "claims": [],
            "units": [
                {
                    "unit_id": "U1",
                    "kind": "introduction",
                    "location": "main.md#u1",
                    "status": "planned",
                    "outline_level": 3,
                    "unit_role": "argument_block",
                    "rhetorical_move": "frame_problem",
                    "communicative_job": "Frame the bounded problem.",
                    "intended_takeaway": "The problem matters in the evaluated setting.",
                    "evidence_plan": ["Link one bounded source."],
                    "quick_reader_role": "Problem in one sentence.",
                }
            ],
        },
        actor="web_ui",
    )
    unit_id = context["units"][0]["id"]
    service = ManuscriptSourceService(db, config=config, project_id="proj_default")
    return service, config, manuscript.id, workspace, unit_id


def _markdown(unit_id: str, sentence: str) -> str:
    return (
        "# Paper\n\n"
        f"<!-- rka:unit {unit_id} begin -->\n"
        f"{sentence}\n"
        f"<!-- rka:unit {unit_id} end -->\n"
    )


async def _evidence_claim(db, content: str) -> str:
    journal_id = generate_id("journal")
    claim_id = generate_id("claim")
    await db.execute(
        """INSERT INTO journal
           (id, type, content, source, confidence, importance, status, project_id)
           VALUES (?, 'log', ?, 'executor', 'tested', 'high', 'active', 'proj_default')""",
        [journal_id, content],
    )
    await db.execute(
        """INSERT INTO claims
           (id, source_entry_id, claim_type, content, confidence, verified,
            evidence_status, stale, project_id)
           VALUES (?, ?, 'result', ?, 0.9, 1, 'supported', 0, 'proj_default')""",
        [claim_id, journal_id, content],
    )
    await db.commit()
    return claim_id


@pytest.mark.asyncio
async def test_prepare_then_apply_is_atomic_mode_preserving_and_recoverable(
    db_with_project,
    tmp_path: Path,
) -> None:
    service, _, manuscript_id, workspace, unit_id = await _source_fixture(
        db_with_project, tmp_path
    )
    before = _markdown(unit_id, "Old bounded prose.")
    after = _markdown(unit_id, "New bounded prose.")
    source = workspace / "main.md"
    source.write_text(before)
    source.chmod(0o640)

    proposal = await service.create_proposal(
        manuscript_id,
        ManuscriptSourceProposalCreate(
            origin="human",
            relative_path="main.md",
            expected_content_hash=_hash(before),
            content=after,
            created_by="web_ui",
            reason="Review and apply the revised introduction.",
        ),
    )
    assert proposal["status"] == "proposed"
    assert source.read_text() == before

    applied = await service.apply_proposal(
        proposal["id"],
        ManuscriptSourceProposalTransition(
            expected_revision=1,
            actor="web_ui",
            reason="PI accepted the source diff.",
        ),
    )
    assert applied["status"] == "applied"
    assert source.read_text() == after
    assert source.stat().st_mode & 0o777 == 0o640
    recovery = Path(db_with_project.db_path).resolve().parent / applied[
        "recovery_manifest_path"
    ]
    payload = json.loads(recovery.read_text())
    assert payload["before_content_hash"] == _hash(before)
    assert payload["after_content_hash"] == _hash(after)
    assert (recovery.parent / "before.bin").read_text() == before
    assert applied["events"][-1]["details"]["git_operation"] is False
    displaced_relative = applied["events"][-1]["details"]["displaced_source_path"]
    assert displaced_relative == service._source_swap_name(proposal["id"])
    assert (workspace / displaced_relative).read_text() == before


@pytest.mark.asyncio
async def test_preopened_external_descriptor_remains_linked_after_apply(
    db_with_project,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _, manuscript_id, workspace, unit_id = await _source_fixture(
        db_with_project, tmp_path
    )
    before = _markdown(unit_id, "Base inode opened by an external editor.")
    after = _markdown(unit_id, "Reviewed proposal installed at the public target.")
    external = _markdown(unit_id, "External bytes written through the pre-opened inode.")
    source = workspace / "main.md"
    source.write_text(before)
    proposal = await service.create_proposal(
        manuscript_id,
        ManuscriptSourceProposalCreate(
            origin="human",
            relative_path="main.md",
            expected_content_hash=_hash(before),
            content=after,
            created_by="web_ui",
            reason="Retain the exact displaced inode across late descriptor writes.",
        ),
    )
    swap_name = service._source_swap_name(proposal["id"])
    editor_fd = os.open(source, os.O_RDWR)
    original_read = service._read_source_entry_at
    injected = False

    def write_after_displaced_read(*args, **kwargs):
        nonlocal injected
        result = original_read(*args, **kwargs)
        if args[1] == swap_name and result[0] is not None and not injected:
            injected = True
            os.lseek(editor_fd, 0, os.SEEK_SET)
            view = memoryview(external.encode())
            while view:
                written = os.write(editor_fd, view)
                view = view[written:]
            os.ftruncate(editor_fd, len(external.encode()))
            os.fsync(editor_fd)
        return result

    monkeypatch.setattr(service, "_read_source_entry_at", write_after_displaced_read)
    try:
        applied = await service.apply_proposal(
            proposal["id"],
            ManuscriptSourceProposalTransition(
                expected_revision=1,
                actor="web_ui",
                reason="Apply while preserving a late write to the displaced inode.",
            ),
        )
        retained = workspace / swap_name
        assert applied["status"] == "applied"
        assert source.read_text() == after
        assert os.fstat(editor_fd).st_ino == retained.stat().st_ino
        assert os.fstat(editor_fd).st_nlink >= 1
        assert retained.read_text() == external
        recovery = Path(db_with_project.db_path).resolve().parent / applied[
            "recovery_manifest_path"
        ]
        assert (recovery.parent / "before.bin").read_text() == before
        assert json.loads(recovery.read_text())["displaced_source_path"] == swap_name
    finally:
        os.close(editor_fd)
    assert (workspace / swap_name).read_text() == external


@pytest.mark.asyncio
async def test_apply_creates_a_missing_source_with_no_clobber_link(
    db_with_project,
    tmp_path: Path,
) -> None:
    service, _, manuscript_id, workspace, unit_id = await _source_fixture(
        db_with_project, tmp_path
    )
    after = _markdown(unit_id, "Create a previously missing source.")
    source = workspace / "main.md"
    proposal = await service.create_proposal(
        manuscript_id,
        ManuscriptSourceProposalCreate(
            origin="human",
            relative_path="main.md",
            expected_content_hash=None,
            content=after,
            created_by="web_ui",
            reason="Exercise atomic missing-file creation.",
        ),
    )

    applied = await service.apply_proposal(
        proposal["id"],
        ManuscriptSourceProposalTransition(
            expected_revision=1,
            actor="web_ui",
            reason="Create the reviewed source without clobbering.",
        ),
    )
    assert applied["status"] == "applied"
    assert source.read_text() == after
    recovery = Path(db_with_project.db_path).resolve().parent / applied[
        "recovery_manifest_path"
    ]
    assert json.loads(recovery.read_text())["before_existed"] is False
    assert not (recovery.parent / "before.bin").exists()


@pytest.mark.asyncio
async def test_external_file_appearing_at_missing_source_commit_is_preserved(
    db_with_project,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _, manuscript_id, workspace, unit_id = await _source_fixture(
        db_with_project, tmp_path
    )
    proposed = _markdown(unit_id, "Proposed missing source.")
    external = _markdown(unit_id, "External source won the creation race.")
    source = workspace / "main.md"
    proposal = await service.create_proposal(
        manuscript_id,
        ManuscriptSourceProposalCreate(
            origin="human",
            relative_path="main.md",
            expected_content_hash=None,
            content=proposed,
            created_by="web_ui",
            reason="Exercise a missing-file creation race.",
        ),
    )
    original_link = os.link
    injected = False

    def inject_before_link(*args, **kwargs):
        nonlocal injected
        if not injected:
            injected = True
            source.write_text(external)
        return original_link(*args, **kwargs)

    monkeypatch.setattr(os, "link", inject_before_link)
    with pytest.raises(ManuscriptSourceConflictError, match="appeared immediately"):
        await service.apply_proposal(
            proposal["id"],
            ManuscriptSourceProposalTransition(
                expected_revision=1,
                actor="web_ui",
                reason="Preserve the external creation winner.",
            ),
        )
    assert source.read_text() == external
    assert (await service.get_proposal(proposal["id"]))["status"] == "conflicted"
    assert not (workspace / service._source_swap_name(proposal["id"])).exists()


@pytest.mark.asyncio
async def test_external_edit_creates_durable_conflict_without_overwrite(
    db_with_project,
    tmp_path: Path,
) -> None:
    service, _, manuscript_id, workspace, unit_id = await _source_fixture(
        db_with_project, tmp_path
    )
    before = _markdown(unit_id, "Initial prose.")
    proposed = _markdown(unit_id, "Proposed prose.")
    external = _markdown(unit_id, "Externally edited prose.")
    source = workspace / "main.md"
    source.write_text(before)
    proposal = await service.create_proposal(
        manuscript_id,
        ManuscriptSourceProposalCreate(
            origin="human",
            relative_path="main.md",
            expected_content_hash=_hash(before),
            content=proposed,
            created_by="web_ui",
            reason="Prepare a bounded revision.",
        ),
    )
    source.write_text(external)

    with pytest.raises(ManuscriptSourceConflictError, match="source changed"):
        await service.apply_proposal(
            proposal["id"],
            ManuscriptSourceProposalTransition(
                expected_revision=1,
                actor="web_ui",
                reason="Attempt apply after an external edit.",
            ),
        )
    assert source.read_text() == external
    conflicted = await service.get_proposal(proposal["id"])
    assert conflicted["status"] == "conflicted"
    assert conflicted["events"][-1]["details"]["file_written"] is False
    assert conflicted["events"][-1]["details"]["transient_exchange"] is False
    assert (
        conflicted["events"][-1]["details"]["transient_exchange_state"]
        == "not_observed"
    )
    assert conflicted["events"][-1]["details"]["final_target_preserved"] is True
    assert conflicted["events"][-1]["details"]["current_content_hash"] == _hash(external)


@pytest.mark.asyncio
async def test_retry_completes_ledger_after_replace_before_transition_failure(
    db_with_project,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _, manuscript_id, workspace, unit_id = await _source_fixture(
        db_with_project, tmp_path
    )
    before = _markdown(unit_id, "Before interrupted apply.")
    after = _markdown(unit_id, "After interrupted apply.")
    source = workspace / "main.md"
    source.write_text(before)
    proposal = await service.create_proposal(
        manuscript_id,
        ManuscriptSourceProposalCreate(
            origin="human",
            relative_path="main.md",
            expected_content_hash=_hash(before),
            content=after,
            created_by="web_ui",
            reason="Exercise recovery after the filesystem commit point.",
        ),
    )
    complete = service._complete_applied_transition

    async def fail_transition(*_args, **_kwargs) -> None:
        raise RuntimeError("simulated database interruption")

    monkeypatch.setattr(service, "_complete_applied_transition", fail_transition)
    transition = ManuscriptSourceProposalTransition(
        expected_revision=1,
        actor="web_ui",
        reason="Apply with a simulated post-replace interruption.",
    )
    with pytest.raises(RuntimeError, match="simulated database interruption"):
        await service.apply_proposal(proposal["id"], transition)
    assert source.read_text() == after
    assert (await service.get_proposal(proposal["id"]))["status"] == "proposed"

    with pytest.raises(ManuscriptSourceConflictError, match="already on disk"):
        await service.reject_proposal(
            proposal["id"],
            ManuscriptSourceProposalTransition(
                expected_revision=1,
                actor="web_ui",
                reason="Do not let reject falsify the crash-applied ledger.",
            ),
        )
    assert (await service.get_proposal(proposal["id"]))["status"] == "proposed"

    monkeypatch.setattr(service, "_complete_applied_transition", complete)
    recovered = await service.apply_proposal(proposal["id"], transition)
    assert recovered["status"] == "applied"
    assert recovered["events"][-1]["details"]["recovered_after_restart"] is True
    assert source.read_text() == after


@pytest.mark.asyncio
async def test_same_file_concurrent_applies_yield_without_event_loop_deadlock(
    db_with_project,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _, manuscript_id, workspace, unit_id = await _source_fixture(
        db_with_project, tmp_path
    )
    before = _markdown(unit_id, "Before concurrent applies.")
    first_after = _markdown(unit_id, "First concurrent proposal.")
    second_after = _markdown(unit_id, "Second concurrent proposal.")
    source = workspace / "main.md"
    source.write_text(before)
    proposals = []
    for content in (first_after, second_after):
        proposals.append(
            await service.create_proposal(
                manuscript_id,
                ManuscriptSourceProposalCreate(
                    origin="human",
                    relative_path="main.md",
                    expected_content_hash=_hash(before),
                    content=content,
                    created_by="web_ui",
                    reason="Exercise serialized same-file apply.",
                ),
            )
        )

    entered = asyncio.Event()
    release = asyncio.Event()
    original_inspect = service.inspect_content

    async def pause_first(*args, **kwargs):
        if args[3] == first_after:
            entered.set()
            await release.wait()
        return await original_inspect(*args, **kwargs)

    monkeypatch.setattr(service, "inspect_content", pause_first)
    transition = ManuscriptSourceProposalTransition(
        expected_revision=1,
        actor="web_ui",
        reason="Apply one of two concurrent proposals.",
    )
    first_task = asyncio.create_task(
        service.apply_proposal(proposals[0]["id"], transition)
    )
    await asyncio.wait_for(entered.wait(), timeout=1)
    second_task = asyncio.create_task(
        service.apply_proposal(proposals[1]["id"], transition)
    )
    await asyncio.sleep(0.05)
    assert not second_task.done()
    release.set()
    results = await asyncio.wait_for(
        asyncio.gather(first_task, second_task, return_exceptions=True), timeout=2
    )

    assert results[0]["status"] == "applied"
    assert isinstance(results[1], ManuscriptSourceConflictError)
    assert source.read_text() == first_after
    assert (await service.get_proposal(proposals[1]["id"]))["status"] == "conflicted"


@pytest.mark.asyncio
@pytest.mark.parametrize("closing_action", ["reject", "supersede"])
async def test_apply_serializes_reject_and_supersede_after_filesystem_commit(
    db_with_project,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    closing_action: str,
) -> None:
    service, _, manuscript_id, workspace, unit_id = await _source_fixture(
        db_with_project, tmp_path
    )
    before = _markdown(unit_id, "Before terminal-state race.")
    after = _markdown(unit_id, "Applied content wins the serialized race.")
    source = workspace / "main.md"
    source.write_text(before)
    proposal = await service.create_proposal(
        manuscript_id,
        ManuscriptSourceProposalCreate(
            origin="human",
            relative_path="main.md",
            expected_content_hash=_hash(before),
            content=after,
            created_by="web_ui",
            reason="Exercise terminal-state serialization.",
        ),
    )
    entered = asyncio.Event()
    release = asyncio.Event()
    original_complete = service._complete_applied_transition

    async def pause_after_replace(*args, **kwargs):
        entered.set()
        await release.wait()
        await original_complete(*args, **kwargs)

    monkeypatch.setattr(service, "_complete_applied_transition", pause_after_replace)
    transition = ManuscriptSourceProposalTransition(
        expected_revision=1,
        actor="web_ui",
        reason="Apply before a competing terminal transition.",
    )
    apply_task = asyncio.create_task(service.apply_proposal(proposal["id"], transition))
    await asyncio.wait_for(entered.wait(), timeout=1)
    if closing_action == "reject":
        close_task = asyncio.create_task(
            service.reject_proposal(
                proposal["id"],
                ManuscriptSourceProposalTransition(
                    expected_revision=1,
                    actor="web_ui",
                    reason="Competing rejection must not falsify the ledger.",
                ),
            )
        )
    else:
        close_task = asyncio.create_task(
            service.create_proposal(
                manuscript_id,
                ManuscriptSourceProposalCreate(
                    origin="human",
                    relative_path="main.md",
                    expected_content_hash=_hash(after),
                    content=_markdown(unit_id, "Attempted superseding content."),
                    created_by="web_ui",
                    reason="Competing supersession must not falsify the ledger.",
                    supersedes_proposal_id=proposal["id"],
                ),
            )
        )
    await asyncio.sleep(0.05)
    assert not close_task.done()
    release.set()
    applied, close_result = await asyncio.wait_for(
        asyncio.gather(apply_task, close_task, return_exceptions=True), timeout=2
    )

    assert applied["status"] == "applied"
    assert isinstance(close_result, ManuscriptSourceConflictError)
    assert (await service.get_proposal(proposal["id"]))["status"] == "applied"
    assert source.read_text() == after


@pytest.mark.asyncio
async def test_external_edit_after_recovery_is_preserved_before_final_replace(
    db_with_project,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _, manuscript_id, workspace, unit_id = await _source_fixture(
        db_with_project, tmp_path
    )
    before = _markdown(unit_id, "Before late external edit.")
    proposed = _markdown(unit_id, "Proposed content.")
    external = _markdown(unit_id, "External edit after recovery.")
    source = workspace / "main.md"
    source.write_text(before)
    proposal = await service.create_proposal(
        manuscript_id,
        ManuscriptSourceProposalCreate(
            origin="human",
            relative_path="main.md",
            expected_content_hash=_hash(before),
            content=proposed,
            created_by="web_ui",
            reason="Exercise final pre-replace hash verification.",
        ),
    )
    original_exchange = service._atomic_exchange_at
    injected = False

    def inject_external_edit(*args, **kwargs):
        nonlocal injected
        if not injected:
            injected = True
            source.write_text(external)
        original_exchange(*args, **kwargs)

    monkeypatch.setattr(service, "_atomic_exchange_at", inject_external_edit)
    with pytest.raises(ManuscriptSourceConflictError, match="immediately before"):
        await service.apply_proposal(
            proposal["id"],
            ManuscriptSourceProposalTransition(
                expected_revision=1,
                actor="web_ui",
                reason="Do not overwrite the late external edit.",
            ),
        )

    assert source.read_text() == external
    conflicted = await service.get_proposal(proposal["id"])
    assert conflicted["status"] == "conflicted"
    assert conflicted["events"][-1]["details"]["current_content_hash"] == _hash(
        external
    )
    assert conflicted["events"][-1]["details"]["file_written"] is True
    assert conflicted["events"][-1]["details"]["transient_exchange"] is True
    assert (
        conflicted["events"][-1]["details"]["transient_exchange_state"]
        == "observed"
    )
    assert conflicted["events"][-1]["details"]["final_target_preserved"] is True
    recovery = service._recovery_manifest_path(conflicted)
    assert (recovery.parent / "before.bin").read_text() == before


@pytest.mark.asyncio
async def test_retry_reconciles_failure_after_replace_before_directory_fsync(
    db_with_project,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _, manuscript_id, workspace, unit_id = await _source_fixture(
        db_with_project, tmp_path
    )
    before = _markdown(unit_id, "Before directory fsync failure.")
    after = _markdown(unit_id, "After directory fsync failure.")
    source = workspace / "main.md"
    source.write_text(before)
    proposal = await service.create_proposal(
        manuscript_id,
        ManuscriptSourceProposalCreate(
            origin="human",
            relative_path="main.md",
            expected_content_hash=_hash(before),
            content=after,
            created_by="web_ui",
            reason="Exercise the replace-to-directory-fsync crash window.",
        ),
    )
    original_fsync = os.fsync
    workspace_stat = workspace.stat()
    source_directory_fsyncs = 0

    def fail_second_directory_fsync(fd: int) -> None:
        nonlocal source_directory_fsyncs
        target = os.fstat(fd)
        if (
            stat.S_ISDIR(target.st_mode)
            and target.st_dev == workspace_stat.st_dev
            and target.st_ino == workspace_stat.st_ino
        ):
            source_directory_fsyncs += 1
            if source_directory_fsyncs == 2:
                raise OSError("simulated source-directory fsync failure")
        original_fsync(fd)

    monkeypatch.setattr(os, "fsync", fail_second_directory_fsync)
    transition = ManuscriptSourceProposalTransition(
        expected_revision=1,
        actor="web_ui",
        reason="Apply across a simulated directory-fsync failure.",
    )
    with pytest.raises(OSError, match="source-directory fsync failure"):
        await service.apply_proposal(proposal["id"], transition)
    assert source.read_text() == after
    assert (await service.get_proposal(proposal["id"]))["status"] == "proposed"

    retry_directory_fsyncs = 0

    def count_retry_directory_fsync(fd: int) -> None:
        nonlocal retry_directory_fsyncs
        target = os.fstat(fd)
        if (
            stat.S_ISDIR(target.st_mode)
            and target.st_dev == workspace_stat.st_dev
            and target.st_ino == workspace_stat.st_ino
        ):
            retry_directory_fsyncs += 1
        original_fsync(fd)

    monkeypatch.setattr(os, "fsync", count_retry_directory_fsync)
    recovered = await service.apply_proposal(proposal["id"], transition)
    assert recovered["status"] == "applied"
    assert recovered["events"][-1]["details"]["recovered_after_restart"] is True
    assert retry_directory_fsyncs >= 1


@pytest.mark.asyncio
async def test_retry_fsyncs_restored_external_source_before_terminal_conflict(
    db_with_project,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _, manuscript_id, workspace, unit_id = await _source_fixture(
        db_with_project, tmp_path
    )
    before = _markdown(unit_id, "Base before rollback durability failure.")
    after = _markdown(unit_id, "Proposal involved in rollback durability failure.")
    external = _markdown(unit_id, "External object restored before fsync failure.")
    source = workspace / "main.md"
    source.write_text(before)
    proposal = await service.create_proposal(
        manuscript_id,
        ManuscriptSourceProposalCreate(
            origin="human",
            relative_path="main.md",
            expected_content_hash=_hash(before),
            content=after,
            created_by="web_ui",
            reason="Retry the rollback durability barrier before terminal conflict.",
        ),
    )
    original_exchange = service._atomic_exchange_at
    injected = False

    def inject_external_before_exchange(*args, **kwargs):
        nonlocal injected
        if not injected:
            injected = True
            source.write_text(external)
        original_exchange(*args, **kwargs)

    monkeypatch.setattr(
        service, "_atomic_exchange_at", inject_external_before_exchange
    )
    original_fsync = os.fsync
    workspace_stat = workspace.stat()
    source_directory_fsyncs = 0

    def fail_rollback_directory_fsync(fd: int) -> None:
        nonlocal source_directory_fsyncs
        target = os.fstat(fd)
        if (
            stat.S_ISDIR(target.st_mode)
            and target.st_dev == workspace_stat.st_dev
            and target.st_ino == workspace_stat.st_ino
        ):
            source_directory_fsyncs += 1
            if source_directory_fsyncs == 2:
                raise OSError("simulated rollback source-directory fsync failure")
        original_fsync(fd)

    monkeypatch.setattr(os, "fsync", fail_rollback_directory_fsync)
    transition = ManuscriptSourceProposalTransition(
        expected_revision=1,
        actor="web_ui",
        reason="Preserve and durably restore the external source.",
    )
    with pytest.raises(
        ManuscriptSourceSecurityError, match="could not be rolled back safely"
    ):
        await service.apply_proposal(proposal["id"], transition)
    assert source.read_text() == external
    assert (await service.get_proposal(proposal["id"]))["status"] == "proposed"
    assert not (workspace / service._source_swap_name(proposal["id"])).exists()

    retry_directory_fsyncs = 0

    def count_retry_directory_fsync(fd: int) -> None:
        nonlocal retry_directory_fsyncs
        target = os.fstat(fd)
        if (
            stat.S_ISDIR(target.st_mode)
            and target.st_dev == workspace_stat.st_dev
            and target.st_ino == workspace_stat.st_ino
        ):
            retry_directory_fsyncs += 1
        original_fsync(fd)

    monkeypatch.setattr(os, "fsync", count_retry_directory_fsync)
    with pytest.raises(ManuscriptSourceConflictError, match="source changed"):
        await service.apply_proposal(proposal["id"], transition)
    assert retry_directory_fsyncs >= 1
    assert source.read_text() == external
    assert (await service.get_proposal(proposal["id"]))["status"] == "conflicted"


@pytest.mark.asyncio
@pytest.mark.parametrize("swap_state", ["proposed", "unexpected"])
async def test_terminal_conflict_cleans_only_a_known_proposal_swap(
    db_with_project,
    tmp_path: Path,
    swap_state: str,
) -> None:
    service, _, manuscript_id, workspace, unit_id = await _source_fixture(
        db_with_project, tmp_path
    )
    before = _markdown(unit_id, "Base before conflict-side swap cleanup.")
    after = _markdown(unit_id, "Proposal retained at the deterministic swap name.")
    external = _markdown(unit_id, "External source already restored at target.")
    unexpected = _markdown(unit_id, "Unexpected object at deterministic swap name.")
    source = workspace / "main.md"
    source.write_text(before)
    proposal = await service.create_proposal(
        manuscript_id,
        ManuscriptSourceProposalCreate(
            origin="human",
            relative_path="main.md",
            expected_content_hash=_hash(before),
            content=after,
            created_by="web_ui",
            reason="Reconcile a conflict-side deterministic swap.",
        ),
    )
    row = await service._require_proposal_row(proposal["id"])
    recovery = service._recovery_manifest_path(row)
    service._write_recovery(row, before.encode(), 0o644, recovery)
    source.write_text(external)
    swap = workspace / service._source_swap_name(proposal["id"])
    swap.write_text(after if swap_state == "proposed" else unexpected)
    transition = ManuscriptSourceProposalTransition(
        expected_revision=1,
        actor="web_ui",
        reason="Finish conflict-side recovery safely.",
    )

    if swap_state == "proposed":
        with pytest.raises(ManuscriptSourceConflictError, match="source changed"):
            await service.apply_proposal(proposal["id"], transition)
        assert not swap.exists()
        assert (await service.get_proposal(proposal["id"]))["status"] == "conflicted"
    else:
        with pytest.raises(
            ManuscriptSourceSecurityError, match="unexpected source swap"
        ):
            await service.apply_proposal(proposal["id"], transition)
        assert swap.read_text() == unexpected
        assert (await service.get_proposal(proposal["id"]))["status"] == "proposed"
    assert source.read_text() == external


@pytest.mark.asyncio
@pytest.mark.parametrize("closing_action", ["reject", "supersede"])
async def test_reject_and_supersede_fsync_prior_rollback_state_before_closing(
    db_with_project,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    closing_action: str,
) -> None:
    service, _, manuscript_id, workspace, unit_id = await _source_fixture(
        db_with_project, tmp_path
    )
    before = _markdown(unit_id, "Base before rollback-aware terminal close.")
    after = _markdown(unit_id, "Proposal left at swap after rollback.")
    external = _markdown(unit_id, "External target restored before terminal close.")
    superseding = _markdown(unit_id, "Replacement proposal after durable cleanup.")
    source = workspace / "main.md"
    source.write_text(before)
    proposal = await service.create_proposal(
        manuscript_id,
        ManuscriptSourceProposalCreate(
            origin="human",
            relative_path="main.md",
            expected_content_hash=_hash(before),
            content=after,
            created_by="web_ui",
            reason="Exercise rollback-aware reject and supersede.",
        ),
    )
    row = await service._require_proposal_row(proposal["id"])
    recovery = service._recovery_manifest_path(row)
    service._write_recovery(row, before.encode(), 0o644, recovery)
    source.write_text(external)
    swap = workspace / service._source_swap_name(proposal["id"])
    swap.write_text(after)
    original_fsync = os.fsync
    workspace_stat = workspace.stat()
    source_directory_fsyncs = 0

    def count_source_directory_fsync(fd: int) -> None:
        nonlocal source_directory_fsyncs
        target = os.fstat(fd)
        if (
            stat.S_ISDIR(target.st_mode)
            and target.st_dev == workspace_stat.st_dev
            and target.st_ino == workspace_stat.st_ino
        ):
            source_directory_fsyncs += 1
        original_fsync(fd)

    monkeypatch.setattr(os, "fsync", count_source_directory_fsync)
    if closing_action == "reject":
        result = await service.reject_proposal(
            proposal["id"],
            ManuscriptSourceProposalTransition(
                expected_revision=1,
                actor="web_ui",
                reason="Reject only after durable rollback cleanup.",
            ),
        )
        assert result["status"] == "rejected"
    else:
        result = await service.create_proposal(
            manuscript_id,
            ManuscriptSourceProposalCreate(
                origin="human",
                relative_path="main.md",
                expected_content_hash=_hash(external),
                content=superseding,
                created_by="web_ui",
                reason="Supersede only after durable rollback cleanup.",
                supersedes_proposal_id=proposal["id"],
            ),
        )
        assert result["status"] == "proposed"
        assert (await service.get_proposal(proposal["id"]))["status"] == "superseded"
    assert source_directory_fsyncs >= 1
    assert source.read_text() == external
    assert not swap.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_index", [1, 2, 3, 4])
async def test_recovery_hierarchy_retries_every_parent_directory_fsync(
    db_with_project,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_index: int,
) -> None:
    service, _, manuscript_id, workspace, unit_id = await _source_fixture(
        db_with_project, tmp_path
    )
    before = _markdown(unit_id, "Base for durable recovery hierarchy.")
    after = _markdown(unit_id, "Proposed durable recovery hierarchy.")
    source = workspace / "main.md"
    source.write_text(before)
    proposal = await service.create_proposal(
        manuscript_id,
        ManuscriptSourceProposalCreate(
            origin="human",
            relative_path="main.md",
            expected_content_hash=_hash(before),
            content=after,
            created_by="web_ui",
            reason="Exercise every recovery hierarchy durability barrier.",
        ),
    )
    row = await service._require_proposal_row(proposal["id"])
    recovery = service._recovery_manifest_path(row)
    original_fsync = os.fsync
    directory_fsyncs = 0

    def fail_selected_directory_fsync(fd: int) -> None:
        nonlocal directory_fsyncs
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            directory_fsyncs += 1
            if directory_fsyncs == failure_index:
                raise OSError(f"simulated recovery hierarchy fsync {failure_index}")
        original_fsync(fd)

    monkeypatch.setattr(os, "fsync", fail_selected_directory_fsync)
    with pytest.raises(OSError, match="recovery hierarchy fsync"):
        service._write_recovery(
            row,
            before.encode(),
            source.stat().st_mode & 0o777,
            recovery,
        )

    monkeypatch.setattr(os, "fsync", original_fsync)
    service._write_recovery(
        row,
        before.encode(),
        source.stat().st_mode & 0o777,
        recovery,
    )
    assert service._valid_recovery_manifest(recovery, row)
    assert source.read_text() == before


@pytest.mark.asyncio
async def test_retry_finishes_interrupted_exchange_with_exact_base_in_swap(
    db_with_project,
    tmp_path: Path,
) -> None:
    service, _, manuscript_id, workspace, unit_id = await _source_fixture(
        db_with_project, tmp_path
    )
    before = _markdown(unit_id, "Base retained by interrupted exchange.")
    after = _markdown(unit_id, "Proposed content visible after interrupted exchange.")
    source = workspace / "main.md"
    source.write_text(before)
    proposal = await service.create_proposal(
        manuscript_id,
        ManuscriptSourceProposalCreate(
            origin="human",
            relative_path="main.md",
            expected_content_hash=_hash(before),
            content=after,
            created_by="web_ui",
            reason="Reconcile a crash after exchange and before cleanup.",
        ),
    )
    row = await service._require_proposal_row(proposal["id"])
    recovery = service._recovery_manifest_path(row)
    service._write_recovery(row, before.encode(), 0o644, recovery)
    parent_fd, name = service._open_parent_fd(workspace, Path("main.md"))
    swap_name = service._source_swap_name(proposal["id"])
    try:
        service._prepare_source_swap(parent_fd, swap_name, after.encode(), 0o644)
        service._atomic_exchange_at(parent_fd, swap_name, parent_fd, name)
    finally:
        os.close(parent_fd)

    assert source.read_text() == after
    recovered = await service.apply_proposal(
        proposal["id"],
        ManuscriptSourceProposalTransition(
            expected_revision=1,
            actor="web_ui",
            reason="Resume the interrupted exchange.",
        ),
    )
    assert recovered["status"] == "applied"
    assert recovered["events"][-1]["details"]["recovered_after_restart"] is True
    assert (workspace / swap_name).read_text() == before


@pytest.mark.asyncio
async def test_retry_restores_external_file_displaced_by_interrupted_exchange(
    db_with_project,
    tmp_path: Path,
) -> None:
    service, _, manuscript_id, workspace, unit_id = await _source_fixture(
        db_with_project, tmp_path
    )
    before = _markdown(unit_id, "Base before interrupted external race.")
    after = _markdown(unit_id, "Proposed content after interrupted external race.")
    external = _markdown(unit_id, "External content displaced at the exchange point.")
    source = workspace / "main.md"
    source.write_text(before)
    proposal = await service.create_proposal(
        manuscript_id,
        ManuscriptSourceProposalCreate(
            origin="human",
            relative_path="main.md",
            expected_content_hash=_hash(before),
            content=after,
            created_by="web_ui",
            reason="Restore an external inode captured by an interrupted exchange.",
        ),
    )
    row = await service._require_proposal_row(proposal["id"])
    recovery = service._recovery_manifest_path(row)
    service._write_recovery(row, before.encode(), 0o644, recovery)
    source.write_text(external)
    parent_fd, name = service._open_parent_fd(workspace, Path("main.md"))
    swap_name = service._source_swap_name(proposal["id"])
    try:
        service._prepare_source_swap(parent_fd, swap_name, after.encode(), 0o644)
        service._atomic_exchange_at(parent_fd, swap_name, parent_fd, name)
    finally:
        os.close(parent_fd)

    assert source.read_text() == after
    with pytest.raises(ManuscriptSourceConflictError, match="external source version"):
        await service.apply_proposal(
            proposal["id"],
            ManuscriptSourceProposalTransition(
                expected_revision=1,
                actor="web_ui",
                reason="Restore the displaced external source.",
            ),
        )
    assert source.read_text() == external
    assert (await service.get_proposal(proposal["id"]))["status"] == "conflicted"
    assert not (workspace / swap_name).exists()


@pytest.mark.asyncio
async def test_markdown_and_latex_anchors_round_trip_and_invalid_links_block(
    db_with_project,
    tmp_path: Path,
) -> None:
    service, _, manuscript_id, workspace, unit_id = await _source_fixture(
        db_with_project, tmp_path
    )
    markdown = _markdown(unit_id, "Bounded prose.")
    (workspace / "main.md").write_text(markdown)
    snapshot = await service.read_file(manuscript_id, "main.md")
    assert snapshot["anchors"][0]["unit_id"] == unit_id
    assert not [item for item in snapshot["findings"] if item["severity"] == "error"]

    latex = (
        f"% rka:unit {unit_id} begin\n"
        "Bounded \\LaTeX{} prose.\n"
        f"% rka:unit {unit_id} end\n"
    )
    (workspace / "main.tex").write_text(latex)
    latex_snapshot = await service.read_file(manuscript_id, "main.tex")
    assert latex_snapshot["source_format"] == "latex"
    assert latex_snapshot["anchors"][0]["unit_id"] == unit_id

    invalid = markdown.replace(unit_id, "mun_01ZZZZZZZZZZZZZZZZZZZZZZZZ")
    with pytest.raises(ValueError, match="blocking anchor"):
        await service.create_proposal(
            manuscript_id,
            ManuscriptSourceProposalCreate(
                origin="human",
                relative_path="main.md",
                expected_content_hash=_hash(markdown),
                content=invalid,
                created_by="web_ui",
                reason="This foreign anchor must be rejected.",
            ),
        )


@pytest.mark.asyncio
async def test_path_traversal_symlink_and_unconfigured_root_fail_closed(
    db_with_project,
    tmp_path: Path,
) -> None:
    service, config, manuscript_id, workspace, _ = await _source_fixture(
        db_with_project, tmp_path
    )
    with pytest.raises(ManuscriptSourceSecurityError):
        await service.read_file(manuscript_id, "../secret.md")

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("secret")
    (workspace / "linked").symlink_to(outside, target_is_directory=True)
    with pytest.raises((ManuscriptSourceSecurityError, OSError)):
        await service.read_file(manuscript_id, "linked/secret.md")

    fifo = workspace / "blocking.md"
    os.mkfifo(fifo)
    with pytest.raises(ManuscriptSourceSecurityError, match="regular file"):
        await service.read_file(manuscript_id, "blocking.md")

    disabled = ManuscriptSourceService(
        db_with_project,
        config=config.model_copy(update={"manuscript_workspace_roots": ""}),
        project_id="proj_default",
    )
    with pytest.raises(ManuscriptSourceSecurityError, match="disabled"):
        await disabled.list_files(manuscript_id)


@pytest.mark.asyncio
async def test_symlinked_workspace_ref_fails_closed(
    db_with_project,
    tmp_path: Path,
) -> None:
    service, _, manuscript_id, workspace, unit_id = await _source_fixture(
        db_with_project, tmp_path
    )
    (workspace / "main.md").write_text(_markdown(unit_id, "Bounded prose."))
    alias = tmp_path / "workspace-alias"
    alias.symlink_to(workspace, target_is_directory=True)
    await db_with_project.execute(
        "UPDATE manuscripts SET workspace_ref = ? WHERE id = ? AND project_id = ?",
        [str(alias), manuscript_id, "proj_default"],
    )
    await db_with_project.commit()

    with pytest.raises(ManuscriptSourceSecurityError, match="symlink component"):
        await service.read_file(manuscript_id, "main.md")


@pytest.mark.asyncio
async def test_symlinked_recovery_directory_fails_before_source_write(
    db_with_project,
    tmp_path: Path,
) -> None:
    service, _, manuscript_id, workspace, unit_id = await _source_fixture(
        db_with_project, tmp_path
    )
    before = _markdown(unit_id, "Before unsafe recovery path.")
    after = _markdown(unit_id, "After unsafe recovery path.")
    source = workspace / "main.md"
    source.write_text(before)
    proposal = await service.create_proposal(
        manuscript_id,
        ManuscriptSourceProposalCreate(
            origin="human",
            relative_path="main.md",
            expected_content_hash=_hash(before),
            content=after,
            created_by="web_ui",
            reason="This must fail before writing through a recovery symlink.",
        ),
    )
    external = tmp_path / "external-locks"
    external.mkdir()
    marker = external / "keep.bin"
    marker.write_bytes(b"keep")
    recovery_root = Path(db_with_project.db_path).resolve().parent / (
        "manuscript-source-recovery"
    )
    recovery_root.mkdir(exist_ok=True)
    (recovery_root / "proj_default").symlink_to(external, target_is_directory=True)

    with pytest.raises(ManuscriptSourceSecurityError, match="recovery path"):
        await service.apply_proposal(
            proposal["id"],
            ManuscriptSourceProposalTransition(
                expected_revision=1,
                actor="web_ui",
                reason="Reject the unsafe recovery path.",
            ),
        )
    assert source.read_text() == before
    assert marker.read_bytes() == b"keep"


@pytest.mark.asyncio
async def test_overview_separates_quick_reader_from_private_risk(
    db_with_project,
    tmp_path: Path,
) -> None:
    service, _, manuscript_id, workspace, unit_id = await _source_fixture(
        db_with_project, tmp_path
    )
    (workspace / "main.md").write_text(_markdown(unit_id, "Bounded prose."))
    overview = await service.get_overview(manuscript_id)
    assert overview["quick_reader"][0]["anchor_state"] == "linked"
    assert overview["quick_reader"][0]["quick_reader_role"] == "Problem in one sentence."
    assert overview["public_private_boundary"]["draft_source"] == "public authoring artifact"
    assert "never copied automatically" in overview["public_private_boundary"][
        "private_reviewer_risks"
    ]


@pytest.mark.asyncio
async def test_overview_projects_unallocated_claim_adverse_evidence_privately(
    db_with_project,
    tmp_path: Path,
) -> None:
    service, _, manuscript_id, workspace, unit_id = await _source_fixture(
        db_with_project, tmp_path
    )
    support_id = await _evidence_claim(db_with_project, "Measured bounded support.")
    qualifier_id = await _evidence_claim(db_with_project, "Observed boundary condition.")
    counterevidence_id = await _evidence_claim(db_with_project, "Observed adverse case.")
    native = NativeManuscriptService(db_with_project, project_id="proj_default")
    manuscript = await native.get(manuscript_id)
    assert manuscript is not None
    context = await native.upsert_argument_spine(
        manuscript_id,
        expected_revision=manuscript.revision,
        spine={
            "claims": [
                {
                    "claim_id": "C1",
                    "claim_type": "empirical",
                    "status": "active",
                    "text": "The bounded mechanism produced the measured effect.",
                    "allowed_wording": "The effect held in the evaluated setting.",
                    "prohibited_wording": ["The mechanism always works."],
                    "evidence_ids": [support_id],
                    "qualifier_ids": [qualifier_id],
                    "counterevidence_ids": [counterevidence_id],
                    "unit_links": [{"unit_key": "U1", "relationship": "advances"}],
                }
            ],
            "units": [
                {
                    "unit_id": "U1",
                    "kind": "introduction",
                    "location": "main.md#u1",
                    "status": "planned",
                    "outline_level": 3,
                    "unit_role": "argument_block",
                    "rhetorical_move": "frame_problem",
                    "communicative_job": "Frame the bounded problem.",
                    "intended_takeaway": "The problem matters in the evaluated setting.",
                    "evidence_plan": ["Link one bounded source."],
                    "quick_reader_role": "Problem in one sentence.",
                    "evidence_ids": [support_id],
                }
            ],
        },
        actor="web_ui",
    )
    assert context["units"][0]["id"] == unit_id
    (workspace / "main.md").write_text(_markdown(unit_id, "Bounded prose."))

    overview = await service.get_overview(manuscript_id)
    assert {
        (risk["kind"], risk.get("claim_id"), risk.get("evidence_claim_id"))
        for risk in overview["private_reviewer_risks"]
        if risk["kind"].startswith("unallocated_")
    } == {
        ("unallocated_qualifier", context["claims"][0]["id"], qualifier_id),
        (
            "unallocated_counterevidence",
            context["claims"][0]["id"],
            counterevidence_id,
        ),
    }


@pytest.mark.asyncio
async def test_direct_source_reads_reject_invalid_utf8_and_configured_oversize(
    db_with_project,
    tmp_path: Path,
) -> None:
    service, config, manuscript_id, workspace, _ = await _source_fixture(
        db_with_project, tmp_path
    )
    (workspace / "invalid.md").write_bytes(b"\xff\xfe")
    with pytest.raises(ValueError, match="valid UTF-8"):
        await service.read_file(manuscript_id, "invalid.md")

    bounded = ManuscriptSourceService(
        db_with_project,
        config=config.model_copy(update={"manuscript_source_max_bytes": 32}),
        project_id="proj_default",
    )
    (workspace / "oversize.md").write_bytes(b"x" * 33)
    with pytest.raises(ValueError, match="size limit"):
        await bounded.read_file(manuscript_id, "oversize.md")


@pytest.mark.asyncio
async def test_provenance_comments_must_match_current_unit_bindings(
    db_with_project,
    tmp_path: Path,
) -> None:
    service, _, manuscript_id, workspace, unit_id = await _source_fixture(
        db_with_project, tmp_path
    )
    journal_id = generate_id("journal")
    evidence_id = generate_id("claim")
    manuscript_claim_id = generate_id("manuscript_claim")
    literature_id = generate_id("literature")
    reference_id = generate_id("manuscript_reference")
    await db_with_project.execute(
        """INSERT INTO journal
           (id, type, content, source, confidence, importance, status, project_id)
           VALUES (?, 'log', 'Observed bounded result.', 'executor',
                   'tested', 'high', 'active', 'proj_default')""",
        [journal_id],
    )
    await db_with_project.execute(
        """INSERT INTO claims
           (id, source_entry_id, claim_type, content, confidence, verified,
            evidence_status, stale, project_id)
           VALUES (?, ?, 'result', 'Observed bounded result.', 0.9, 1,
                   'supported', 0, 'proj_default')""",
        [evidence_id, journal_id],
    )
    await db_with_project.execute(
        """INSERT INTO manuscript_claims
           (id, manuscript_id, project_id, local_key, kind, state)
           VALUES (?, ?, 'proj_default', 'C1', 'empirical', 'active')""",
        [manuscript_claim_id, manuscript_id],
    )
    await db_with_project.execute(
        """INSERT INTO manuscript_claim_versions
           (claim_id, version, manuscript_id, project_id, exact_wording,
            allowed_wording, prohibited_wording)
           VALUES (?, 1, ?, 'proj_default', 'The bounded result held.',
                   'The bounded result held in the evaluated setting.',
                   '["The result always holds."]')""",
        [manuscript_claim_id, manuscript_id],
    )
    await db_with_project.execute(
        """INSERT INTO manuscript_claim_units
           (manuscript_id, project_id, manuscript_claim_id, claim_version,
            unit_id, relationship)
           VALUES (?, 'proj_default', ?, 1, ?, 'advances')""",
        [manuscript_id, manuscript_claim_id, unit_id],
    )
    await db_with_project.execute(
        """INSERT INTO manuscript_unit_evidence
           (manuscript_id, project_id, unit_id, evidence_claim_id, role, ordinal)
           VALUES (?, 'proj_default', ?, ?, 'support', 0)""",
        [manuscript_id, unit_id, evidence_id],
    )
    await db_with_project.execute(
        """INSERT INTO literature
           (id, title, authors, year, doi, status, added_by, project_id)
           VALUES (?, 'Prior bounded study', '[]', 2025, '10.1000/source-sync',
                   'cited', 'pi', 'proj_default')""",
        [literature_id],
    )
    await db_with_project.execute(
        """INSERT INTO manuscript_reference_members
           (id, manuscript_id, project_id, citation_key, literature_id)
           VALUES (?, ?, 'proj_default', 'prior2025', ?)""",
        [reference_id, manuscript_id, literature_id],
    )
    await db_with_project.execute(
        """INSERT INTO manuscript_unit_citations
           (id, manuscript_id, project_id, unit_id, reference_member_id,
            citation_role, supported_proposition, verification_state)
           VALUES (?, ?, 'proj_default', ?, ?, 'bounds',
                   'Prior work bounds the comparison.', 'self_attested')""",
        [
            generate_id("manuscript_unit_citation"),
            manuscript_id,
            unit_id,
            reference_id,
        ],
    )
    await db_with_project.commit()

    valid = (
        f"<!-- rka:unit {unit_id} begin -->\n"
        "Bounded prose.\n"
        f"<!-- rka:provenance claim={manuscript_claim_id} "
        f"evidence={evidence_id} citation=prior2025 -->\n"
        f"<!-- rka:unit {unit_id} end -->\n"
    )
    (workspace / "main.md").write_text(valid)
    snapshot = await service.read_file(manuscript_id, "main.md")
    assert len(snapshot["provenance"]) == 3
    assert all(item["verified"] for item in snapshot["provenance"])

    invalid = valid.replace("citation=prior2025", "citation=unbound2025")
    with pytest.raises(ValueError, match="blocking anchor or provenance"):
        await service.create_proposal(
            manuscript_id,
            ManuscriptSourceProposalCreate(
                origin="human",
                relative_path="main.md",
                expected_content_hash=_hash(valid),
                content=invalid,
                created_by="web_ui",
                reason="Reject an unbound citation marker.",
            ),
        )


@pytest.mark.asyncio
async def test_ai_source_proposal_requires_current_target_manifest(
    db_with_project,
    tmp_path: Path,
) -> None:
    service, _, manuscript_id, workspace, unit_id = await _source_fixture(
        db_with_project, tmp_path
    )
    before = _markdown(unit_id, "Before AI proposal.")
    (workspace / "main.md").write_text(before)
    patches = SemanticPatchService(db_with_project, project_id="proj_default")
    manifest = await patches.create_context_manifest(
        ContextManifestCreate(
            origin="host_agent",
            provider="openai",
            model="host-model",
            boundary="host_conversation",
            targets=[{"target_type": "manuscript", "target_id": manuscript_id}],
            constraints=["Preserve current evidence boundaries."],
        )
    )
    proposal = await service.create_proposal(
        manuscript_id,
        ManuscriptSourceProposalCreate(
            origin="host_agent",
            relative_path="main.md",
            expected_content_hash=_hash(before),
            content=_markdown(unit_id, "AI-proposed bounded revision."),
            created_by="web_ui",
            reason="Prepare disclosed host-agent prose for PI review.",
            provider="openai",
            model="host-model",
            boundary="host_conversation",
            context_manifest_id=manifest["id"],
        ),
    )
    assert proposal["context_manifest_id"] == manifest["id"]
    assert proposal["status"] == "proposed"

    native = NativeManuscriptService(db_with_project, project_id="proj_default")
    current = await native.get(manuscript_id)
    assert current is not None
    await native.update(
        manuscript_id,
        ManuscriptUpdate(expected_revision=current.revision, title="Revised source paper"),
        actor="pi",
    )
    with pytest.raises(ManuscriptSourceConflictError, match="revision is stale"):
        await service.create_proposal(
            manuscript_id,
            ManuscriptSourceProposalCreate(
                origin="host_agent",
                relative_path="main.md",
                expected_content_hash=_hash(before),
                content=_markdown(unit_id, "Stale-context proposal."),
                created_by="web_ui",
                reason="This must not pass with a stale disclosure manifest.",
                provider="openai",
                model="host-model",
                boundary="host_conversation",
                context_manifest_id=manifest["id"],
            ),
        )


@pytest.mark.asyncio
async def test_knowledge_pack_omits_local_source_candidate_and_ledger(
    db_with_project,
    tmp_path: Path,
) -> None:
    service, _, manuscript_id, workspace, unit_id = await _source_fixture(
        db_with_project, tmp_path
    )
    before = _markdown(unit_id, "Portable semantic context only.")
    sentinel = "LOCAL-CANDIDATE-MUST-NOT-ENTER-KNOWLEDGE-PACK"
    (workspace / "main.md").write_text(before)
    await service.create_proposal(
        manuscript_id,
        ManuscriptSourceProposalCreate(
            origin="human",
            relative_path="main.md",
            expected_content_hash=_hash(before),
            content=_markdown(unit_id, sentinel),
            created_by="web_ui",
            reason="Keep installation-local source out of the portable pack.",
        ),
    )

    pack_path, _ = await KnowledgePackService(
        db_with_project, project_id="proj_default"
    ).export_pack()
    with zipfile.ZipFile(pack_path) as archive:
        manifest_bytes = archive.read("manifest.json")
        manifest = json.loads(manifest_bytes)
    assert "manuscript_source_proposals" not in manifest["tables"]
    assert "manuscript_source_events" not in manifest["tables"]
    assert "manuscript_source_proposals" in manifest["portability"]["excluded_tables"]
    assert sentinel.encode() not in manifest_bytes
