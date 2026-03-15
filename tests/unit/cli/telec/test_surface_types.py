from __future__ import annotations

import importlib

from teleclaude.constants import HUMAN_ROLE_MEMBER, ROLE_ORCHESTRATOR

surface_types = importlib.import_module("teleclaude.cli.telec.surface_types")


def test_command_auth_prefers_system_roles_for_agent_callers() -> None:
    auth = surface_types.CommandAuth(system=frozenset({"orch"}), human=frozenset({"member"}))

    assert auth.allows("orch", None) is True
    assert auth.allows("worker", "member") is False
    assert auth.allows(None, "member") is True


def test_flag_as_tuple_preserves_short_long_and_description() -> None:
    flag = surface_types.Flag("--project", "-p", "Project path")

    assert flag.as_tuple() == ("-p", "--project", "Project path")


def test_command_def_visible_flags_omits_hidden_flags() -> None:
    command = surface_types.CommandDef(
        desc="demo",
        flags=[surface_types.Flag("--project"), surface_types.Flag("--help", hidden=True)],
    )

    assert [flag.long for flag in command.visible_flags] == ["--project"]


def test_command_def_tuples_reflect_flags_and_subcommands() -> None:
    command = surface_types.CommandDef(
        desc="root",
        flags=[surface_types.Flag("--project", "-p", "Project path")],
        subcommands={"show": surface_types.CommandDef(desc="Show data")},
    )

    assert command.flag_tuples == [("-p", "--project", "Project path")]
    assert command.subcmd_tuples == [("show", "Show data")]


def test_auth_shorthand_sets_include_expected_roles() -> None:
    assert ROLE_ORCHESTRATOR in surface_types._SYS_ORCH
    assert HUMAN_ROLE_MEMBER in surface_types._HR_MEMBER
