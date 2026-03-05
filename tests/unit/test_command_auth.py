"""Unit tests for CommandAuth metadata and is_command_allowed()."""

import pytest

from teleclaude.cli.telec import CLI_SURFACE, CommandDef, is_command_allowed
from teleclaude.constants import (
    HUMAN_ROLE_ADMIN,
    HUMAN_ROLE_CONTRIBUTOR,
    HUMAN_ROLE_CUSTOMER,
    HUMAN_ROLE_MEMBER,
    HUMAN_ROLE_NEWCOMER,
    ROLE_ORCHESTRATOR,
    ROLE_WORKER,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _collect_leaves(surface: dict[str, CommandDef], prefix: str = "") -> list[tuple[str, CommandDef]]:
    """Recursively collect (path, CommandDef) for every leaf node."""
    results = []
    for name, cmd in surface.items():
        path = f"{prefix} {name}".strip() if prefix else name
        if cmd.subcommands:
            results.extend(_collect_leaves(cmd.subcommands, path))
        else:
            results.append((path, cmd))
    return results


# ---------------------------------------------------------------------------
# Task 4.2: Completeness — every leaf must have auth
# ---------------------------------------------------------------------------


def test_every_leaf_has_auth():
    """Every leaf CommandDef in CLI_SURFACE must have auth populated."""
    leaves = _collect_leaves(CLI_SURFACE)
    assert leaves, "CLI_SURFACE has no leaf commands — something is wrong"
    missing = [(path, cmd) for path, cmd in leaves if cmd.auth is None]
    if missing:
        paths = [path for path, _ in missing]
        pytest.fail(f"Leaf commands missing auth: {paths}")


# ---------------------------------------------------------------------------
# Task 4.1: Behavioral tests for is_command_allowed()
# ---------------------------------------------------------------------------


class TestAdminBypass:
    """Admin bypasses human-role check for all commands except escalate."""

    def test_admin_allowed_orchestrator_only_command(self):
        assert is_command_allowed("sessions start", ROLE_ORCHESTRATOR, HUMAN_ROLE_ADMIN)

    def test_admin_allowed_all_system_command(self):
        assert is_command_allowed("sessions result", ROLE_ORCHESTRATOR, HUMAN_ROLE_ADMIN)

    def test_admin_allowed_version(self):
        assert is_command_allowed("version", ROLE_ORCHESTRATOR, HUMAN_ROLE_ADMIN)

    def test_admin_allowed_roadmap_add(self):
        assert is_command_allowed("roadmap add", ROLE_ORCHESTRATOR, HUMAN_ROLE_ADMIN)

    def test_admin_allowed_config_wizard(self):
        assert is_command_allowed("config wizard", ROLE_ORCHESTRATOR, HUMAN_ROLE_ADMIN)


class TestAdminEscalateExclusion:
    """Admin is explicitly excluded from sessions escalate."""

    def test_admin_denied_sessions_escalate(self):
        assert not is_command_allowed("sessions escalate", ROLE_ORCHESTRATOR, HUMAN_ROLE_ADMIN)

    def test_admin_denied_sessions_escalate_worker_system(self):
        # Even if we pretend admin is a worker, admin is excluded from escalate
        assert not is_command_allowed("sessions escalate", ROLE_WORKER, HUMAN_ROLE_ADMIN)


class TestWorkerRestrictions:
    """Workers are denied orchestrator-only commands."""

    def test_worker_denied_sessions_start(self):
        assert not is_command_allowed("sessions start", ROLE_WORKER, HUMAN_ROLE_MEMBER)

    def test_worker_denied_sessions_run(self):
        assert not is_command_allowed("sessions run", ROLE_WORKER, HUMAN_ROLE_MEMBER)

    def test_worker_denied_todo_prepare(self):
        assert not is_command_allowed("todo prepare", ROLE_WORKER, HUMAN_ROLE_MEMBER)

    def test_worker_denied_roadmap_list(self):
        assert not is_command_allowed("roadmap list", ROLE_WORKER, HUMAN_ROLE_MEMBER)

    def test_worker_denied_sessions_revive(self):
        assert not is_command_allowed("sessions revive", ROLE_WORKER, HUMAN_ROLE_ADMIN)

    def test_worker_denied_sync(self):
        assert not is_command_allowed("sync", ROLE_WORKER, HUMAN_ROLE_MEMBER)


class TestWorkerAllowed:
    """Workers are allowed commands with system=all."""

    def test_worker_allowed_sessions_result(self):
        assert is_command_allowed("sessions result", ROLE_WORKER, HUMAN_ROLE_MEMBER)

    def test_worker_allowed_sessions_file(self):
        assert is_command_allowed("sessions file", ROLE_WORKER, HUMAN_ROLE_MEMBER)

    def test_worker_allowed_sessions_widget(self):
        assert is_command_allowed("sessions widget", ROLE_WORKER, HUMAN_ROLE_MEMBER)

    def test_worker_allowed_sessions_escalate(self):
        assert is_command_allowed("sessions escalate", ROLE_WORKER, HUMAN_ROLE_MEMBER)

    def test_worker_allowed_docs_index(self):
        assert is_command_allowed("docs index", ROLE_WORKER, HUMAN_ROLE_MEMBER)

    def test_worker_allowed_docs_get(self):
        assert is_command_allowed("docs get", ROLE_WORKER, HUMAN_ROLE_MEMBER)

    def test_worker_allowed_version(self):
        assert is_command_allowed("version", ROLE_WORKER, HUMAN_ROLE_MEMBER)

    def test_worker_allowed_todo_validate(self):
        assert is_command_allowed("todo validate", ROLE_WORKER, HUMAN_ROLE_MEMBER)

    def test_worker_allowed_todo_verify_artifacts(self):
        assert is_command_allowed("todo verify-artifacts", ROLE_WORKER, HUMAN_ROLE_MEMBER)

    def test_worker_allowed_sessions_list(self):
        assert is_command_allowed("sessions list", ROLE_WORKER, HUMAN_ROLE_MEMBER)

    def test_worker_allowed_sessions_send(self):
        assert is_command_allowed("sessions send", ROLE_WORKER, HUMAN_ROLE_MEMBER)

    def test_worker_allowed_sessions_tail(self):
        assert is_command_allowed("sessions tail", ROLE_WORKER, HUMAN_ROLE_MEMBER)

    def test_worker_allowed_sessions_unsubscribe(self):
        assert is_command_allowed("sessions unsubscribe", ROLE_WORKER, HUMAN_ROLE_MEMBER)

    def test_worker_allowed_computers_list(self):
        assert is_command_allowed("computers list", ROLE_WORKER, HUMAN_ROLE_MEMBER)

    def test_worker_allowed_projects_list(self):
        assert is_command_allowed("projects list", ROLE_WORKER, HUMAN_ROLE_MEMBER)

    def test_worker_allowed_agents_availability(self):
        assert is_command_allowed("agents availability", ROLE_WORKER, HUMAN_ROLE_MEMBER)

    def test_worker_allowed_channels_list(self):
        assert is_command_allowed("channels list", ROLE_WORKER, HUMAN_ROLE_MEMBER)

    def test_worker_allowed_channels_publish(self):
        assert is_command_allowed("channels publish", ROLE_WORKER, HUMAN_ROLE_MEMBER)


class TestMemberPermissions:
    """Members have broad access but not admin-only commands."""

    def test_member_allowed_sessions_start(self):
        assert is_command_allowed("sessions start", ROLE_ORCHESTRATOR, HUMAN_ROLE_MEMBER)

    def test_member_allowed_sessions_end(self):
        assert is_command_allowed("sessions end", ROLE_ORCHESTRATOR, HUMAN_ROLE_MEMBER)

    def test_member_allowed_roadmap_list(self):
        assert is_command_allowed("roadmap list", ROLE_ORCHESTRATOR, HUMAN_ROLE_MEMBER)

    def test_member_allowed_todo_create(self):
        assert is_command_allowed("todo create", ROLE_ORCHESTRATOR, HUMAN_ROLE_MEMBER)

    def test_member_denied_config_wizard(self):
        assert not is_command_allowed("config wizard", ROLE_ORCHESTRATOR, HUMAN_ROLE_MEMBER)

    def test_member_denied_config_patch(self):
        assert not is_command_allowed("config patch", ROLE_ORCHESTRATOR, HUMAN_ROLE_MEMBER)

    def test_member_denied_agents_status(self):
        assert not is_command_allowed("agents status", ROLE_ORCHESTRATOR, HUMAN_ROLE_MEMBER)

    def test_member_denied_sessions_revive(self):
        assert not is_command_allowed("sessions revive", ROLE_ORCHESTRATOR, HUMAN_ROLE_MEMBER)

    def test_member_denied_sessions_restart(self):
        assert not is_command_allowed("sessions restart", ROLE_ORCHESTRATOR, HUMAN_ROLE_MEMBER)


class TestContributorRestrictions:
    """Contributors cannot start/send/run sessions or do planning ops."""

    def test_contributor_denied_sessions_start(self):
        assert not is_command_allowed("sessions start", ROLE_ORCHESTRATOR, HUMAN_ROLE_CONTRIBUTOR)

    def test_contributor_denied_sessions_send(self):
        assert not is_command_allowed("sessions send", ROLE_ORCHESTRATOR, HUMAN_ROLE_CONTRIBUTOR)

    def test_contributor_denied_sessions_run(self):
        assert not is_command_allowed("sessions run", ROLE_ORCHESTRATOR, HUMAN_ROLE_CONTRIBUTOR)

    def test_contributor_denied_roadmap_add(self):
        assert not is_command_allowed("roadmap add", ROLE_ORCHESTRATOR, HUMAN_ROLE_CONTRIBUTOR)

    def test_contributor_allowed_sessions_result(self):
        assert is_command_allowed("sessions result", ROLE_ORCHESTRATOR, HUMAN_ROLE_CONTRIBUTOR)

    def test_contributor_allowed_todo_create(self):
        assert is_command_allowed("todo create", ROLE_ORCHESTRATOR, HUMAN_ROLE_CONTRIBUTOR)

    def test_contributor_allowed_bugs_report(self):
        assert is_command_allowed("bugs report", ROLE_ORCHESTRATOR, HUMAN_ROLE_CONTRIBUTOR)

    def test_contributor_allowed_docs_get(self):
        assert is_command_allowed("docs get", ROLE_ORCHESTRATOR, HUMAN_ROLE_CONTRIBUTOR)

    def test_contributor_allowed_sessions_escalate(self):
        assert is_command_allowed("sessions escalate", ROLE_ORCHESTRATOR, HUMAN_ROLE_CONTRIBUTOR)


class TestNewcomerRestrictions:
    """Newcomers have read-heavy access only."""

    def test_newcomer_denied_sessions_start(self):
        assert not is_command_allowed("sessions start", ROLE_ORCHESTRATOR, HUMAN_ROLE_NEWCOMER)

    def test_newcomer_denied_sessions_send(self):
        assert not is_command_allowed("sessions send", ROLE_ORCHESTRATOR, HUMAN_ROLE_NEWCOMER)

    def test_newcomer_denied_todo_dump(self):
        assert not is_command_allowed("todo dump", ROLE_ORCHESTRATOR, HUMAN_ROLE_NEWCOMER)

    def test_newcomer_denied_content_dump(self):
        assert not is_command_allowed("content dump", ROLE_ORCHESTRATOR, HUMAN_ROLE_NEWCOMER)

    def test_newcomer_allowed_docs_index(self):
        assert is_command_allowed("docs index", ROLE_ORCHESTRATOR, HUMAN_ROLE_NEWCOMER)

    def test_newcomer_allowed_sessions_list(self):
        assert is_command_allowed("sessions list", ROLE_ORCHESTRATOR, HUMAN_ROLE_NEWCOMER)

    def test_newcomer_allowed_bugs_report(self):
        assert is_command_allowed("bugs report", ROLE_ORCHESTRATOR, HUMAN_ROLE_NEWCOMER)

    def test_newcomer_allowed_sessions_escalate(self):
        assert is_command_allowed("sessions escalate", ROLE_ORCHESTRATOR, HUMAN_ROLE_NEWCOMER)

    def test_newcomer_denied_roadmap_add(self):
        assert not is_command_allowed("roadmap add", ROLE_ORCHESTRATOR, HUMAN_ROLE_NEWCOMER)


class TestCustomerRestrictions:
    """Customers can only use version, docs, auth, and escalate."""

    def test_customer_allowed_version(self):
        assert is_command_allowed("version", ROLE_ORCHESTRATOR, HUMAN_ROLE_CUSTOMER)

    def test_customer_allowed_docs_index(self):
        assert is_command_allowed("docs index", ROLE_ORCHESTRATOR, HUMAN_ROLE_CUSTOMER)

    def test_customer_allowed_docs_get(self):
        assert is_command_allowed("docs get", ROLE_ORCHESTRATOR, HUMAN_ROLE_CUSTOMER)

    def test_customer_allowed_auth_login(self):
        assert is_command_allowed("auth login", ROLE_ORCHESTRATOR, HUMAN_ROLE_CUSTOMER)

    def test_customer_allowed_auth_whoami(self):
        assert is_command_allowed("auth whoami", ROLE_ORCHESTRATOR, HUMAN_ROLE_CUSTOMER)

    def test_customer_allowed_sessions_escalate(self):
        assert is_command_allowed("sessions escalate", ROLE_ORCHESTRATOR, HUMAN_ROLE_CUSTOMER)

    def test_customer_denied_sessions_start(self):
        assert not is_command_allowed("sessions start", ROLE_ORCHESTRATOR, HUMAN_ROLE_CUSTOMER)

    def test_customer_denied_sessions_list(self):
        assert not is_command_allowed("sessions list", ROLE_ORCHESTRATOR, HUMAN_ROLE_CUSTOMER)

    def test_customer_denied_roadmap_list(self):
        assert not is_command_allowed("roadmap list", ROLE_ORCHESTRATOR, HUMAN_ROLE_CUSTOMER)

    def test_customer_denied_bugs_report(self):
        assert not is_command_allowed("bugs report", ROLE_ORCHESTRATOR, HUMAN_ROLE_CUSTOMER)

    def test_customer_denied_todo_validate(self):
        assert not is_command_allowed("todo validate", ROLE_ORCHESTRATOR, HUMAN_ROLE_CUSTOMER)

    def test_customer_denied_config_get(self):
        assert not is_command_allowed("config get", ROLE_ORCHESTRATOR, HUMAN_ROLE_CUSTOMER)


class TestEdgeCases:
    """Edge cases: unknown paths, None roles, path formats."""

    def test_unknown_command_path_returns_false(self):
        assert not is_command_allowed("nonexistent command", ROLE_ORCHESTRATOR, HUMAN_ROLE_ADMIN)

    def test_unknown_top_level_returns_false(self):
        assert not is_command_allowed("foobar", ROLE_ORCHESTRATOR, HUMAN_ROLE_ADMIN)

    def test_empty_path_returns_false(self):
        assert not is_command_allowed("", ROLE_ORCHESTRATOR, HUMAN_ROLE_ADMIN)

    def test_none_system_role_treated_as_orchestrator(self):
        # TUI/terminal callers have no session context → treated as orchestrator
        assert is_command_allowed("sessions start", None, HUMAN_ROLE_MEMBER)

    def test_none_system_role_blocks_orchestrator_only_for_worker(self):
        # None system_role → orchestrator, so orchestrator-only commands ARE allowed
        assert is_command_allowed("roadmap list", None, HUMAN_ROLE_MEMBER)

    def test_none_human_role_denied(self):
        # No human identity → fail closed
        assert not is_command_allowed("sessions start", ROLE_ORCHESTRATOR, None)

    def test_none_human_role_denied_even_for_universal_command(self):
        assert not is_command_allowed("version", ROLE_ORCHESTRATOR, None)

    def test_dot_separated_path(self):
        # "sessions.start" should work the same as "sessions start"
        assert is_command_allowed("sessions.start", ROLE_ORCHESTRATOR, HUMAN_ROLE_MEMBER)

    def test_telec_prefixed_path(self):
        # "telec sessions start" should strip the prefix
        assert is_command_allowed("telec sessions start", ROLE_ORCHESTRATOR, HUMAN_ROLE_MEMBER)

    def test_todo_demo_subcommand_path(self):
        assert is_command_allowed("todo demo list", ROLE_ORCHESTRATOR, HUMAN_ROLE_MEMBER)

    def test_config_people_subcommand_path(self):
        assert is_command_allowed("config people list", ROLE_ORCHESTRATOR, HUMAN_ROLE_ADMIN)

    def test_config_people_denied_for_member(self):
        assert not is_command_allowed("config people list", ROLE_ORCHESTRATOR, HUMAN_ROLE_MEMBER)

    def test_config_env_subcommand_path(self):
        assert is_command_allowed("config env set", ROLE_ORCHESTRATOR, HUMAN_ROLE_ADMIN)
