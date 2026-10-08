"""Create, adopt or converge a project folder and return the config subject its declaration establishes."""

from __future__ import annotations

from collections.abc import Callable
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
from teleclaude.paths import ConfigFileName
from teleclaude.project_setup.init_flow import (
    ProjectDestination,
    ProjectInitializationResult,
    ProjectInitializationTrigger,
    adopt_project,
    converge_project,
    create_project,
    project_identity,
)
from teleclaude.services.project_catalog import get_project_catalog_service

_HELP_DESK_HOME_REFUSAL = "a person or company home keeps its help desk through company or global init"
_NOT_REGISTERED = "project {where} did not register after {operation}"


def _declared_subject(root: Path, identify_project: Callable[[Path], str]) -> tuple[ConfigSubjectKind, str | None]:
    """Return the config kind a folder declares and the identity its subject will have."""
    config_path = root.expanduser().resolve() / ConfigFileName.OVERLAY
    kind = load_declared_config_kind(config_path) if config_path.is_file() else ConfigKind.PROJECT
    subject_kind = ConfigSubjectKind(kind.value)
    if kind in (ConfigKind.PERSON, ConfigKind.COMPANY):
        return subject_kind, root.name
    if kind is ConfigKind.PROJECT:
        return subject_kind, identify_project(root)
    return subject_kind, None


def _run_project_operation(
    act: Callable[[], ProjectInitializationResult],
    *,
    where: str,
    subject_kind: ConfigSubjectKind,
    identity: str | None,
    operation: ResourceOperation,
    request_id: str | None,
) -> SubjectView:
    """Run one project act as an observed resource change and return the resulting subject view."""
    revision_before = _try_revision_before(subject_kind, identity)

    result: ProjectInitializationResult | None = None

    def _compute(evidence: OwnEvidence) -> SubjectView:
        nonlocal result
        evidence.enter_unobserved()
        result = act()
        ref = SubjectRef(ConfigSubjectKind(result.kind.value), result.identity)
        evidence.mark(target_id(ref.kind, ref.instance, TargetDocument.REGISTRY))
        if result.kind is ConfigKind.PROJECT:
            evidence.mark(target_id(ref.kind, ref.instance, TargetDocument.PLUMBING))
            catalog = get_project_catalog_service()
            catalog.refresh()
            node = catalog.get_by_slug(result.identity)
            if node is None:
                raise SubjectNotFound(_NOT_REGISTERED.format(where=where, operation=operation.value))
            ref = SubjectRef(ConfigSubjectKind.PROJECT, node.slug)
        return read_subject(ref)

    view = run_observed(
        _compute,
        request_id=request_id,
        kind=subject_kind,
        instance=identity,
        operation=operation,
        revision_before=revision_before,
    )
    emit_resource_change(
        request_id=request_id,
        kind=view.ref.kind,
        instance=view.ref.instance,
        operation=operation,
        outcome=ResourceChangeOutcome.UNCHANGED
        if result is not None and result.already_registered and revision_before == view.revision
        else ResourceChangeOutcome.COMMITTED,
        revision_before=revision_before,
        revision_after=view.revision,
    )
    return view


def init_project_subject(
    root: Path,
    *,
    request_id: str | None = None,
    trigger: ProjectInitializationTrigger = ProjectInitializationTrigger.CLI,
    help_desk: bool = False,
) -> SubjectView:
    """Converge the caller's registered folder and return its declared subject view."""
    subject_kind, identity = _declared_subject(root, project_identity)
    if help_desk and subject_kind in (ConfigSubjectKind.PERSON, ConfigSubjectKind.COMPANY):
        raise InvalidCandidate(_HELP_DESK_HOME_REFUSAL)
    return _run_project_operation(
        lambda: converge_project(root, trigger=trigger, help_desk=help_desk),
        where=str(root),
        subject_kind=subject_kind,
        identity=identity,
        operation=ResourceOperation.INIT,
        request_id=request_id,
    )


def adopt_project_subject(
    root: Path,
    *,
    request_id: str | None = None,
    trigger: ProjectInitializationTrigger = ProjectInitializationTrigger.CLI,
) -> SubjectView:
    """Register the caller's folder where it is and return its declared subject view."""
    subject_kind, identity = _declared_subject(root, project_identity)
    return _run_project_operation(
        lambda: adopt_project(root, trigger=trigger),
        where=str(root),
        subject_kind=subject_kind,
        identity=identity,
        operation=ResourceOperation.ADOPT,
        request_id=request_id,
    )


def create_project_subject(
    name: str,
    destination: ProjectDestination,
    *,
    request_id: str | None = None,
    trigger: ProjectInitializationTrigger = ProjectInitializationTrigger.CLI,
) -> SubjectView:
    """Make a new, empty project and return its declared subject view."""
    return _run_project_operation(
        lambda: create_project(name, destination, trigger=trigger),
        where=name,
        subject_kind=ConfigSubjectKind.PROJECT,
        identity=name,
        operation=ResourceOperation.CREATE,
        request_id=request_id,
    )
