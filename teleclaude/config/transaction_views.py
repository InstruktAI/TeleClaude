"""Read configuration subjects from already-held file transactions."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from teleclaude.config.machine import config_path
from teleclaude.config.machine_config_mutation import inspect_machine_config_transaction
from teleclaude.config.migrations.read import upcast_for_read
from teleclaude.config.person_resource import person_overlay_path, person_view
from teleclaude.config.resource_catalog import load_mapping
from teleclaude.config.resource_contract import SubjectNotFound, SubjectView
from teleclaude.config.resources import computer_view_from
from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef
from teleclaude.file_transaction import FileTransaction
from teleclaude.paths import GLOBAL_CONFIG_PATH

_UNSUPPORTED_SUBJECT_ERROR = "held transactions support computer and person configuration subjects"


def read_subject_in_transactions(ref: SubjectRef, transactions: Mapping[Path, FileTransaction]) -> SubjectView:
    """Read a computer or person subject without reacquiring its held locks."""
    if ref.kind is ConfigSubjectKind.COMPUTER:
        inspection = inspect_machine_config_transaction(transactions[config_path])
        return computer_view_from(inspection.raw, inspection.revision)
    if ref.kind is ConfigSubjectKind.PERSON:
        if ref.instance is None:
            raise SubjectNotFound(_UNSUPPORTED_SUBJECT_ERROR)
        overlay_path = person_overlay_path(ref.instance)
        global_raw = upcast_for_read(
            GLOBAL_CONFIG_PATH,
            load_mapping(transactions[GLOBAL_CONFIG_PATH].read_text(), GLOBAL_CONFIG_PATH),
            subject=SubjectRef(ConfigSubjectKind.GLOBAL),
        )
        overlay_raw = upcast_for_read(
            overlay_path,
            load_mapping(transactions[overlay_path].read_text(), overlay_path),
            subject=ref,
        )
        return person_view(ref.instance, global_raw, overlay_raw)
    raise ValueError(_UNSUPPORTED_SUBJECT_ERROR)
