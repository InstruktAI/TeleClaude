"""Adopt a folder and return the config subject its declaration establishes."""

from __future__ import annotations

from pathlib import Path

from teleclaude.config.context_root import load_declared_config_kind
from teleclaude.config.resource_contract import (
    InvalidCandidate,
    OwnEvidence,
    ResourceChangeOutcome,
    ResourceOperation,
    SubjectNotFound,
    SubjectView,
    TargetDocument,
    emit_resource_change,
    run_observed,
    target_id,
)
from teleclaude.config.resources import _try_revision_before, read_subject
from teleclaude.config.schema import ConfigKind
from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef
from teleclaude.docs_index import get_project_slug
from teleclaude.paths import ConfigFileName
from teleclaude.project_setup.init_flow import ProjectInitializationResult, ProjectInitializationTrigger, init_project
from teleclaude.services.project_catalog import get_project_catalog_service

_HELP_DESK_HOME_REFUSAL = "a person or company home keeps its help desk through company or global init"


def init_project_subject(
    root: Path,
    *,
    request_id: str | None = None,
    trigger: ProjectInitializationTrigger = ProjectInitializationTrigger.CLI,
    help_desk: bool = False,
) -> SubjectView:
    """Adopt the caller's folder and return its declared subject view."""
    config_path = root.expanduser().resolve() / ConfigFileName.OVERLAY
    kind = load_declared_config_kind(config_path) if config_path.is_file() else ConfigKind.PROJECT
    subject_kind = ConfigSubjectKind(kind.value)
    if help_desk and kind in (ConfigKind.PERSON, ConfigKind.COMPANY):
        raise InvalidCandidate(_HELP_DESK_HOME_REFUSAL)
    if kind in (ConfigKind.PERSON, ConfigKind.COMPANY):
        identity = root.name
    elif kind is ConfigKind.PROJECT:
        identity = get_project_slug(root)
    else:
        identity = None
    revision_before = _try_revision_before(subject_kind, identity)

    result: ProjectInitializationResult | None = None

    def _compute(evidence: OwnEvidence) -> SubjectView:
        nonlocal result
        evidence.enter_unobserved()
        result = init_project(root, trigger=trigger, help_desk=help_desk)
        ref = SubjectRef(ConfigSubjectKind(result.kind.value), result.identity)
        evidence.mark(target_id(ref.kind, ref.instance, TargetDocument.REGISTRY))
        if result.kind is ConfigKind.PROJECT:
            evidence.mark(target_id(ref.kind, ref.instance, TargetDocument.PLUMBING))
            catalog = get_project_catalog_service()
            catalog.refresh()
            node = catalog.get_by_slug(result.identity)
            if node is None:
                raise SubjectNotFound(f"project at {root} did not register after init")
            ref = SubjectRef(ConfigSubjectKind.PROJECT, node.slug)
        return read_subject(ref)

    view = run_observed(
        _compute,
        request_id=request_id,
        kind=subject_kind,
        instance=identity,
        operation=ResourceOperation.INIT,
        revision_before=revision_before,
    )
    emit_resource_change(
        request_id=request_id,
        kind=view.ref.kind,
        instance=view.ref.instance,
        operation=ResourceOperation.INIT,
        outcome=ResourceChangeOutcome.UNCHANGED
        if result is not None and result.already_registered and revision_before == view.revision
        else ResourceChangeOutcome.COMMITTED,
        revision_before=revision_before,
        revision_after=view.revision,
    )
    return view
