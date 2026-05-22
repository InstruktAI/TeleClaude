"""Snapshot tests for telec todo create and telec todo dump help output."""

from __future__ import annotations

import pytest
from syrupy.assertion import SnapshotAssertion

import teleclaude.cli.telec.help as help_mod


@pytest.mark.unit
def test_todo_create_help_output(snapshot: SnapshotAssertion) -> None:
    assert help_mod._usage_leaf("todo", "create") == snapshot


@pytest.mark.unit
def test_todo_list_help_output(snapshot: SnapshotAssertion) -> None:
    assert help_mod._usage_leaf("todo", "list") == snapshot


@pytest.mark.unit
def test_todo_freeze_help_output(snapshot: SnapshotAssertion) -> None:
    assert help_mod._usage_leaf("todo", "freeze") == snapshot


@pytest.mark.unit
def test_todo_unfreeze_help_output(snapshot: SnapshotAssertion) -> None:
    assert help_mod._usage_leaf("todo", "unfreeze") == snapshot


@pytest.mark.unit
def test_todo_deliver_help_output(snapshot: SnapshotAssertion) -> None:
    assert help_mod._usage_leaf("todo", "deliver") == snapshot


@pytest.mark.unit
def test_todo_dump_help_output(snapshot: SnapshotAssertion) -> None:
    assert help_mod._usage_leaf("todo", "dump") == snapshot
