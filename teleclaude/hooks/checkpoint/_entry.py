"""Evaluate one agent stop for a session and return its checkpoint body, or `None` when no checkpoint work is established or evaluation fails."""

from collections.abc import Mapping
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.capabilities import resolve_project_capability_state
from teleclaude.checkpoint_model import checkpoint_model_from_project_config
from teleclaude.core.agents import AgentName
from teleclaude.core.next_machine.lanes import TODO_WORKTREE_WRITER_ROLES
from teleclaude.hooks.checkpoint._composition import _compose_checkpoint_message
from teleclaude.hooks.checkpoint._evidence import (
    _compute_log_since_window,
    _has_commit_evidence_after_last_mutation,
    _has_review_dispatch_evidence,
)
from teleclaude.hooks.checkpoint._git import (
    _current_branch,
    _dirty_repo_paths,
    _is_checkpoint_project_supported,
    _is_docs_only,
    _is_no_action_only,
    _transcript_observability,
)
from teleclaude.hooks.checkpoint._heuristics import run_heuristics
from teleclaude.hooks.checkpoint._integrator import _integrator_judgment_checkpoint
from teleclaude.hooks.checkpoint._models import CheckpointContext, CheckpointResult
from teleclaude.hooks.checkpoint_flags import consume_authored_main_commit_flag, has_authored_main_commit_flag
from teleclaude.hooks.edit_declarations import declare_certain_timeline_edits
from teleclaude.hooks.main_db import live_commit_reviewer_ids
from teleclaude.project_root import declaration_root, is_slug_worktree
from teleclaude.session_scoping import (
    WorkspaceKind,
    live_declarations,
    resolve_workspace,
    undeclared_shell_write_candidates,
)
from teleclaude.session_scoping._extractors._common import CERTAIN_EDIT_TOOLS
from teleclaude.utils.transcript import TurnTimeline, extract_effective_tool_calls

__all__ = ["build_checkpoint_message", "get_checkpoint_content"]

logger = get_logger("teleclaude.hooks.checkpoint")  # Preserve the package's record identity.

_CHECKPOINT_BUILD_FAILED_MESSAGE = "Checkpoint content build failed; no checkpoint emitted"
_CHECKPOINT_PAYLOAD_COMPUTED = "Checkpoint payload computed"
_QUESTION_ONLY_MODE = "undeclared_write_question"
_LOG_TIMELINE_HAS_DATA = "timeline_has_data"
_LOG_TIMELINE_RECORDS = "timeline_records"
_LOG_CHANGED_FILES = "changed_files"
_LOG_WORKSPACE_KIND = "workspace_kind"
_LOG_CATEGORIES = "categories"
_LOG_REQUIRED_ACTIONS = "required_actions"
_LOG_OBSERVATIONS = "observations"
_LOG_MODE = "mode"
_LOG_MESSAGE_LENGTH = "message_len"
_LOG_SESSION_FALLBACK = "used_session_fallback"
_LOG_AUTHORED_MAIN_COMMIT = "authored_main_commit"
_QUESTION_ONLY_LOG_FIELDS: Mapping[str, object] = {
    _LOG_CHANGED_FILES: 0,
    _LOG_CATEGORIES: [],
    _LOG_REQUIRED_ACTIONS: 0,
    _LOG_OBSERVATIONS: 0,
    _LOG_MODE: _QUESTION_ONLY_MODE,
}


def build_checkpoint_message(
    git_files: list[str],
    timeline: TurnTimeline,
    context: CheckpointContext,
    log_since_window: str = "2m",
) -> str | None:
    """Build a structured checkpoint body from all signal sources."""
    result = run_heuristics(git_files, timeline, context, log_since_window=log_since_window)
    return _compose_checkpoint_message(git_files, result)


def get_checkpoint_content(
    session_id: str,
    transcript_path: str | None,
    agent_name: AgentName,
    project_path: str,
    native_session_id: str | None = None,
    working_slug: str | None = None,
    elapsed_since_turn_start_s: float | None = None,
    role: str | None = None,
    job: str | None = None,
    receiver_ingress_id: str = "",
) -> str | None:
    """Build context-aware checkpoint content for both hook and codex routes.

    Top-level entry point that orchestrates session-scoped path resolution,
    transcript extraction, and message building.

    Returns:
    - str: the checkpoint body, unrendered, when maintenance work is established. The
      delivery path that reaches the agent wraps it in the checkpoint envelope.
    - None: no checkpoint work is established or evaluation fails.
    """
    try:
        transcript_meta = _transcript_observability(transcript_path)
        base_extra = {
            "agent": agent_name.value,
            "receiver_ingress_id": receiver_ingress_id,
            "session_id": session_id,
            "project_path": project_path or "",
            "role": role or "",
            "job": job or "",
            "working_slug": working_slug or "",
            "transcript_present": bool(transcript_path),
            "transcript_path": transcript_meta["transcript_path"],
            "transcript_exists": transcript_meta["transcript_exists"],
            "transcript_size_bytes": transcript_meta["transcript_size_bytes"],
        }
        capability_state = resolve_project_capability_state(declaration_root(Path(project_path).expanduser().resolve()))
        checkpoint_config = capability_state.config.checkpoint if capability_state.config is not None else None
        if not _is_checkpoint_project_supported(project_path, capability_state.capabilities, checkpoint_config):
            logger.info(
                "Checkpoint payload skipped (project out of scope)",
                extra={**base_extra, "mode": "unsupported_project", "message_len": 0},
            )
            return None

        model = checkpoint_model_from_project_config(
            project_path,
            capability_state.config,
            capability_state.capabilities,
        )

        timeline = extract_effective_tool_calls(
            transcript_path,
            agent_name,
            native_session_id=native_session_id,
            scope="checkpoint",
        )

        integrator_checkpoint = _integrator_judgment_checkpoint(
            role=role,
            project_path=project_path,
            timeline=timeline,
            model=model,
            session_id=session_id,
            receiver_ingress_id=receiver_ingress_id,
        )
        if integrator_checkpoint is not None:
            return integrator_checkpoint

        workspace = resolve_workspace(project_path)
        if workspace.kind is WorkspaceKind.GIT_SHARED:
            declare_certain_timeline_edits(session_id, agent_name, timeline, Path(project_path))
        declared_paths = {declaration.path for declaration in live_declarations(session_id)}
        dirty_paths = _dirty_repo_paths(project_path)
        worktree_root = Path(workspace.root) if workspace.root is not None else None
        if workspace.kind is WorkspaceKind.GIT_WORKTREE:
            if worktree_root is not None and is_slug_worktree(worktree_root):
                is_writer = role in TODO_WORKTREE_WRITER_ROLES and working_slug == worktree_root.name
                effective_files = sorted(dirty_paths) if is_writer else []
            else:
                effective_files = sorted(dirty_paths)
        else:
            effective_files = sorted(declared_paths & dirty_paths)
        undeclared_candidates: tuple[str, ...] = ()
        if workspace.kind is WorkspaceKind.GIT_SHARED:
            undeclared_candidates = undeclared_shell_write_candidates(
                timeline,
                dirty_paths=frozenset(dirty_paths),
                declared_paths=frozenset(declared_paths),
                certain_tools=CERTAIN_EDIT_TOOLS[agent_name],
                checkout_root=Path(project_path),
            )
        authored_main_commit = has_authored_main_commit_flag(session_id)
        force_main_commit_checkpoint = authored_main_commit and _current_branch(project_path) == "main"
        used_session_fallback = False

        if not effective_files and not force_main_commit_checkpoint:
            if undeclared_candidates:
                question_result = CheckpointResult(
                    commit_action_required=False,
                    undeclared_candidates=undeclared_candidates,
                )
                message = _compose_checkpoint_message([], question_result)
                logger.info(
                    _CHECKPOINT_PAYLOAD_COMPUTED,
                    extra={
                        **base_extra,
                        **_QUESTION_ONLY_LOG_FIELDS,
                        _LOG_TIMELINE_HAS_DATA: timeline.has_data,
                        _LOG_TIMELINE_RECORDS: len(timeline.tool_calls),
                        _LOG_WORKSPACE_KIND: workspace.kind,
                        _LOG_MESSAGE_LENGTH: len(message) if message else 0,
                        _LOG_SESSION_FALLBACK: used_session_fallback,
                        _LOG_AUTHORED_MAIN_COMMIT: authored_main_commit,
                    },
                )
                return message
            logger.info(
                "Checkpoint payload skipped (no declared-and-dirty changes)",
                extra={
                    **base_extra,
                    "timeline_has_data": timeline.has_data,
                    "timeline_records": len(timeline.tool_calls),
                    "changed_files": 0,
                    "workspace_kind": workspace.kind,
                    "categories": [],
                    "required_actions": 0,
                    "observations": 0,
                    "mode": "silent_no_changes",
                    "message_len": 0,
                    "used_session_fallback": used_session_fallback,
                    "authored_main_commit": authored_main_commit,
                },
            )
            return None

        docs_committed = _has_commit_evidence_after_last_mutation(
            timeline,
            effective_files,
            project_path,
        )
        if (
            _is_no_action_only(effective_files, model)
            and not force_main_commit_checkpoint
            and docs_committed
            and not undeclared_candidates
        ):
            logger.info(
                "Checkpoint payload skipped (no-action changes only, already committed)",
                extra={
                    **base_extra,
                    "timeline_has_data": timeline.has_data,
                    "timeline_records": len(timeline.tool_calls),
                    "changed_files": len(effective_files),
                    "workspace_kind": workspace.kind,
                    "mode": "silent_docs_only",
                    "message_len": 0,
                    "used_session_fallback": used_session_fallback,
                    "authored_main_commit": authored_main_commit,
                },
            )
            return None

        context = CheckpointContext(
            project_path=project_path,
            working_slug=working_slug,
            agent_name=agent_name,
            role=role,
            session_id=session_id,
            receiver_ingress_id=receiver_ingress_id,
            live_commit_reviewer_ids=live_commit_reviewer_ids(session_id, project_path),
        )
        log_since_window = _compute_log_since_window(elapsed_since_turn_start_s)

        result = run_heuristics(
            effective_files,
            timeline,
            context,
            log_since_window=log_since_window,
            authored_main_commit=authored_main_commit,
            model=model,
        )
        result.undeclared_candidates = undeclared_candidates

        if (
            result.is_all_clear
            and not result.commit_action_required
            and not force_main_commit_checkpoint
            and (not effective_files or _is_docs_only(effective_files))
            and not undeclared_candidates
        ):
            logger.info(
                "Checkpoint payload skipped (doc/no-action turn fully satisfied)",
                extra={
                    **base_extra,
                    "timeline_has_data": timeline.has_data,
                    "timeline_records": len(timeline.tool_calls),
                    "changed_files": len(effective_files),
                    "workspace_kind": workspace.kind,
                    "categories": result.categories,
                    "commit_action_required": result.commit_action_required,
                    "docs_only": _is_docs_only(effective_files),
                    "required_actions": 0,
                    "observations": 0,
                    "mode": "silent_docs_satisfied",
                    "message_len": 0,
                    "used_session_fallback": used_session_fallback,
                    "authored_main_commit": authored_main_commit,
                },
            )
            return None

        message = _compose_checkpoint_message(effective_files, result)
        # Consume the authored-commit flag once the review obligation is surfaced
        # or discharged by a review dispatch in this cycle. If composition is
        # silent, consume before returning so a dispatched review settles the marker.
        if result.post_commit_review_action_required or _has_review_dispatch_evidence(
            timeline, context.live_commit_reviewer_ids
        ):
            consume_authored_main_commit_flag(session_id)
        if message is None:
            logger.info(
                "Checkpoint payload skipped (nothing to enforce)",
                extra={
                    **base_extra,
                    "timeline_has_data": timeline.has_data,
                    "timeline_records": len(timeline.tool_calls),
                    "changed_files": len(effective_files),
                    "workspace_kind": workspace.kind,
                    "categories": result.categories,
                    "commit_action_required": result.commit_action_required,
                    "docs_only": _is_docs_only(effective_files),
                    "required_actions": 0,
                    "observations": 0,
                    "mode": "silent_nothing_to_enforce",
                    "message_len": 0,
                    "used_session_fallback": used_session_fallback,
                    "authored_main_commit": authored_main_commit,
                    "post_commit_review_action_required": result.post_commit_review_action_required,
                },
            )
            return None
        mode = (
            "main_commit_authored"
            if force_main_commit_checkpoint
            else "docs_only"
            if _is_docs_only(effective_files)
            else ("all_clear" if result.is_all_clear else "actionable")
        )
        logger.info(
            "Checkpoint payload computed",
            extra={
                **base_extra,
                "timeline_has_data": timeline.has_data,
                "timeline_records": len(timeline.tool_calls),
                "changed_files": len(effective_files),
                "workspace_kind": workspace.kind,
                "categories": result.categories,
                "commit_action_required": result.commit_action_required,
                "docs_only": _is_docs_only(effective_files),
                "required_actions": len(result.required_actions),
                "observations": len(result.observations),
                "mode": mode,
                "message_len": len(message),
                "used_session_fallback": used_session_fallback,
                "authored_main_commit": authored_main_commit,
                "post_commit_review_action_required": result.post_commit_review_action_required,
            },
        )
        logger.trace(
            "Checkpoint payload content",
            extra={
                **base_extra,
                "observations": list(result.observations),
                "required_actions": list(result.required_actions),
                "categories": result.categories,
            },
        )
        return message

    except Exception:
        logger.warning(
            _CHECKPOINT_BUILD_FAILED_MESSAGE,
            extra={
                "agent": agent_name.value,
                "project_path": project_path or "",
                "working_slug": working_slug or "",
                "transcript_present": bool(transcript_path),
                "transcript_path": transcript_path or "",
            },
            exc_info=True,
        )
        return None
