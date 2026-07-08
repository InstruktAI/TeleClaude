from __future__ import annotations

import importlib
import os
import sys
from types import ModuleType

import dotenv
import pytest

from jobs.base import Job

_PROJECT_BACKUP_MODULE = "jobs.project_backup"
_IMPORT_SENTINEL = "PROJECT_BACKUP_IMPORT_SENTINEL"


def _import_project_backup_fresh() -> ModuleType:
    sys.modules.pop(_PROJECT_BACKUP_MODULE, None)
    return importlib.import_module(_PROJECT_BACKUP_MODULE)


def test_project_backup_exposes_discoverable_job() -> None:
    module = _import_project_backup_fresh()

    assert isinstance(module.JOB, Job)


def test_project_backup_import_does_not_mutate_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(_IMPORT_SENTINEL, raising=False)

    def mutating_load_dotenv(*args: object, **kwargs: object) -> bool:
        os.environ[_IMPORT_SENTINEL] = "mutated"
        return True

    monkeypatch.setattr(dotenv, "load_dotenv", mutating_load_dotenv)
    before_import = dict(os.environ)

    _import_project_backup_fresh()

    assert dict(os.environ) == before_import
