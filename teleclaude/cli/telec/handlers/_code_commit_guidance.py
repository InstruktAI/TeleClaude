"""Commit-gate continuation guidance: the printed card `telec code commit` shows
before `--approved`, plus the scope/diffstat/review-lane helpers it composes from.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from sqlalchemy.exc import OperationalError

from teleclaude import agent_artifacts
from teleclaude.constants import (
    CHECKPOINT_BASE_AGENTS_BINDING,
    COMMIT_REVIEW_DISCARD_COMMAND_TEMPLATE,
    COMMIT_REVIEW_DISCARD_PLACEHOLDER,
    COMMIT_REVIEW_INTENT_TEST,
    SlashCommand,
)
from teleclaude.core.db import get_db
from teleclaude.core.next_machine.runtime.sessions import list_live_commit_reviewers_for_initiator
from teleclaude.git import GitCommandError, Repo
from teleclaude.project_root import DOC_LAYER_PATTERN
from teleclaude.quality.scope import WorkspaceScopeResolution, resolve_workspace_scope_resolution
from teleclaude.session_identity import get_session_id

_STANDALONE_PROSE_PATTERNS = ("*.md", "*.txt", "*.rst")
_NON_CODE_DOCUMENTATION_PATTERNS = (DOC_LAYER_PATTERN, *_STANDALONE_PROSE_PATTERNS)
_SCOPE_DIFFSTAT_HEADER = "Scope as resolved now — read this before you write the message:"
_SCOPE_DIFFSTAT_EMPTY = "Scope as resolved now: nothing. A commit would carry no change."
_SCOPE_DIFFSTAT_UNAVAILABLE = "Scope as resolved now: unavailable. Read the diff yourself before committing."
_GIT_DIFF_HEAD_REF = "HEAD"
_GIT_STAT_FLAG = "--stat"
_GIT_PATHSPEC_SEPARATOR = "--"
_SCOPE_DIFFSTAT_LINE_SEPARATOR = "\n"
_AGENT_ARTIFACT_LANE_MIXED = (
    "a mix of authored agent artifacts (doc-hygiene review candidate) and incorporated skill packages (no review)"
)
_AGENT_ARTIFACT_LANE_AUTHORED = "authored agent artifacts, a doc-hygiene review candidate"
_AGENT_ARTIFACT_LANE_INCORPORATED = (
    "only incorporated skill package bodies — no independent review; covered by the pre-adoption security gate"
)
_AGENT_ARTIFACT_LANE_NONE = "none — the pending scope touches no agent-artifact source"
_REVIEW_VERDICT_GUIDANCE = (
    "   Wait for the reviewer's stamped verdict before reporting done. REQUEST CHANGES remains with\n"
    "   you for evidence-based rejection or in-scope remediation and re-review. What\n"
    "   you and the reviewer cannot resolve, you hold: go idle with it and route it\n"
    "   nowhere (general/principle/autonomy).\n"
)
_UNCLASSIFIED_ARTIFACT_LANE_TEMPLATE = (
    "Malformed agent-artifact path(s) could not be classified: {paths}. "
    "The commit card continues so the author can reach lint's finding. "
    "Classified lane for other paths: {lane}."
)
_ARTIFACT_PATH_LIST_SEPARATOR = ", "
_COMMIT_REVIEW_REUSE_GUIDANCE = (
    "   Reuse the reviewer already open at the mode this series needs; a different lane\n"
    "   gets its own reviewer (--mode fast for doc-hygiene, --mode med for code review):\n"
)
_COMMIT_REVIEW_START_GUIDANCE = (
    "   Start the reviewer for this series (--mode fast for doc-hygiene, --mode med for code review):\n"
)
_COMMIT_REVIEW_DISPATCH_TEMPLATE = (
    "     telec sessions run --command {command} --args '<sha1,sha2,...>' --mode <fast|med>\n"
)

__all__ = [
    "_NON_CODE_DOCUMENTATION_PATTERNS",
    "_commit_stage_paths",
    "_print_commit_review_guidance",
]


def _commit_stage_paths(scope_resolution: WorkspaceScopeResolution) -> list[str]:
    return list(scope_resolution.repository_scoped_dirty_paths)


async def _commit_reviewers_async(project_root: Path, initiator_session_id: str) -> tuple[tuple[str, str], ...]:
    """Resolve every live commit-review session open for this project and driver."""
    runtime_db = await get_db()
    return await list_live_commit_reviewers_for_initiator(
        runtime_db, project_root, initiator_session_id, SlashCommand.REVIEW_COMMITS.value
    )


def _resolve_open_commit_reviewers(project_root: Path) -> tuple[tuple[str, str], ...]:
    """Resolve the open commit reviewers for this driver as (session id, mode) pairs.

    Advisory only — this backs a printed hint, never a gate. Any resolution
    failure (no session identity, no runtime, an unreachable database) yields
    an empty result so the caller falls back to the start-only form; resolving
    this hint can never become a new way for ``telec code commit`` to fail.

    Every open reviewer is reported with its mode rather than one arbitrary
    holder: mode is part of the review subject, so a bare session id could
    address the doc-hygiene lane while the series needs the code lane.
    """
    initiator_session_id = get_session_id()
    if not initiator_session_id:
        return ()
    try:
        return asyncio.run(_commit_reviewers_async(project_root, initiator_session_id))
    except (OperationalError, OSError, RuntimeError):
        return ()


def _pending_commit_pathspec(project_root: Path) -> list[str]:
    """Best-effort pathspec this project's next commit would carry.

    Purely advisory: any resolution failure yields an empty list so the
    printed guidance falls back to its patterns-only phrasing rather than
    ever blocking on this lookup.
    """
    try:
        scope_resolution = resolve_workspace_scope_resolution(project_root, context_root=None)
        return _commit_stage_paths(scope_resolution)
    except (OSError, ValueError, RuntimeError):
        return []


def _agent_artifact_review_lane(project_root: Path, pathspec: list[str]) -> str:
    """Describe the agent-artifact review lane the pending pathspec actually carries.

    Distinguishes authored artifacts (commands, masters, addenda, the skill
    catalog master — required doc-hygiene review) from incorporated skill
    package bodies (no independent review; covered by the pre-adoption
    security gate in ``general/procedure/skill-management``), using the
    matched registry record rather than the checkpoint binding's include list.
    """
    sources: list[agent_artifacts.ArtifactSource | None] = []
    unclassified_paths: list[Path] = []
    for path in pathspec:
        try:
            sources.append(agent_artifacts.classify_candidate(project_root, Path(path)))
        except agent_artifacts.UnclassifiedSourceError:
            # Aborting here would hide lint's concrete finding and block access to the commit guidance.
            unclassified_paths.append(Path(path))
            sources.append(None)
    matched = [source for source in sources if source is not None]
    has_authored = any(source.authorship is agent_artifacts.ArtifactAuthorship.AUTHORED for source in matched)
    has_incorporated = any(source.authorship is agent_artifacts.ArtifactAuthorship.INCORPORATED for source in matched)
    if has_authored and has_incorporated:
        lane = _AGENT_ARTIFACT_LANE_MIXED
    elif has_authored:
        lane = _AGENT_ARTIFACT_LANE_AUTHORED
    elif has_incorporated:
        lane = _AGENT_ARTIFACT_LANE_INCORPORATED
    else:
        lane = _AGENT_ARTIFACT_LANE_NONE
    if unclassified_paths:
        paths = _ARTIFACT_PATH_LIST_SEPARATOR.join(str(path) for path in unclassified_paths)
        return _UNCLASSIFIED_ARTIFACT_LANE_TEMPLATE.format(paths=paths, lane=lane)
    return lane


def _resolved_scope_diffstat(project_root: Path, context_root: Path | None) -> str:
    """Render the diffstat of what a commit would carry from the resolved scope.

    The card is read by the author composing its commit message, so the stat is
    the change itself rather than a claim about it: a message written from the
    author's own edits diverges visibly here from what the pathspec will take.
    """
    try:
        scope_resolution = resolve_workspace_scope_resolution(project_root, context_root=context_root)
        paths = _commit_stage_paths(scope_resolution)
        if not paths:
            return _SCOPE_DIFFSTAT_EMPTY
        stat = Repo(str(project_root)).git.diff(_GIT_DIFF_HEAD_REF, _GIT_STAT_FLAG, _GIT_PATHSPEC_SEPARATOR, *paths)
    except (GitCommandError, RuntimeError, OSError):
        # The card's own content is the commit-first and review-routing
        # instruction the agent must act on; the stat is an aid beside it. A
        # scope that will not resolve must not take the instruction down with
        # it, so the stat degrades to naming its own absence and the agent is
        # told to read the diff itself.
        return _SCOPE_DIFFSTAT_UNAVAILABLE
    if not stat.strip():
        return _SCOPE_DIFFSTAT_EMPTY
    return f"{_SCOPE_DIFFSTAT_HEADER}{_SCOPE_DIFFSTAT_LINE_SEPARATOR}{stat}"


def _print_commit_review_guidance(project_root: Path, context_root: Path | None) -> None:
    """Print the active commit-gate continuation instructions for shared main.

    The sealed contract makes ``--approved`` the single gate for any commit on
    main; the bare ``telec code commit`` invocation enters the commit gate. The
    caller owns the exit code, but the printed surface is a continuation
    instruction: commit or reach a concrete blocker before reporting done.
    """
    open_reviewers = _resolve_open_commit_reviewers(project_root)
    documentation_patterns = ", ".join(_NON_CODE_DOCUMENTATION_PATTERNS)
    standalone_prose_patterns = ", ".join(_STANDALONE_PROSE_PATTERNS)
    agent_artifact_patterns = ", ".join(CHECKPOINT_BASE_AGENTS_BINDING.scope.include)
    agent_artifact_lane = _agent_artifact_review_lane(project_root, _pending_commit_pathspec(project_root))
    if open_reviewers:
        already_open = "".join(
            f"     already open at {mode or 'unknown'}: telec sessions send {session_id} "
            "'review commits <sha1,sha2,...>'\n"
            for session_id, mode in open_reviewers
        )
        review_dispatch = (
            _COMMIT_REVIEW_REUSE_GUIDANCE
            + _COMMIT_REVIEW_DISPATCH_TEMPLATE.format(command=SlashCommand.REVIEW_COMMITS.value)
            + already_open
        )
    else:
        review_dispatch = _COMMIT_REVIEW_START_GUIDANCE + _COMMIT_REVIEW_DISPATCH_TEMPLATE.format(
            command=SlashCommand.REVIEW_COMMITS.value
        )
    scope_diffstat = _resolved_scope_diffstat(project_root, context_root)
    discard_command = COMMIT_REVIEW_DISCARD_COMMAND_TEMPLATE.format(sha=COMMIT_REVIEW_DISCARD_PLACEHOLDER)
    print(
        "COMMIT GATE ACTIVE — CONTINUE NOW\n"
        "\n"
        "This output is not informational. Follow it until one terminal state:\n"
        "- a commit is created and its review routing is decided, then completed or started as instructed; or\n"
        "- a concrete blocker is reached.\n"
        "\n"
        f"{scope_diffstat}\n"
        "\n"
        "Required next steps:\n"
        "1. Declare what you are working on, if you have not already:\n"
        "  telec code add <path> [<path> ...]\n"
        "   The declared set is your authoritative commit scope. Late declaration is fine —\n"
        "   declare the moment you notice a path isn't declared yet.\n"
        "\n"
        "2. Commit the declared work yourself. Never ask the human before committing.\n"
        "   If your declared set contains multiple separable intents, split with --only:\n"
        "  telec code commit --approved '<msg>' --only <path> [<path> ...]\n"
        "   A tracked file you wrote from a shell command also needs `telec code add`:\n"
        "   only declared paths are committed, so an undeclared shell write is outside\n"
        "   scope and will not be committed.\n"
        "\n"
        "   Foreign staged files are excluded by pathspec. Do not unstage them.\n"
        "\n"
        "3. After committing, the commit is a review candidate. What the diff touched names the\n"
        "   candidate; you decide whether review is owed:\n"
        "   Remediation only — the diff just applies an open review's findings and adds no\n"
        "       new reviewable surface -> send it back to that same reviewer to confirm; do\n"
        "       not offer a fresh review. Its APPROVE is terminal.\n"
        f"   Any path matched by neither documentation ({documentation_patterns}) nor agent artifacts\n"
        f"       ({agent_artifact_patterns}) ->\n"
        "       code review candidate (--mode med).\n"
        f"   Documentation snippets ({DOC_LAYER_PATTERN}) -> doc-hygiene review candidate\n"
        "       (--mode fast; you may not review your own).\n"
        f"   Agent artifacts ({agent_artifact_patterns}) -> the pending scope carries\n"
        f"       {agent_artifact_lane}.\n"
        f"   Standalone descriptive prose ({standalone_prose_patterns}) outside {DOC_LAYER_PATTERN} -> no\n"
        "       independent review; directive text follows the functional-code review path.\n"
        "\n"
        f"   {COMMIT_REVIEW_INTENT_TEST}\n"
        "   A commit that owes review goes to an independent reviewer you dispatch.\n"
        f"   A commit that owes none is discarded with: {discard_command}\n"
        "\n"
        f"{review_dispatch}"
        f"{_REVIEW_VERDICT_GUIDANCE}",
        file=sys.stderr,
    )
