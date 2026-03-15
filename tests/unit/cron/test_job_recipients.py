"""Characterization tests for teleclaude.cron.job_recipients."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from teleclaude.cron.job_recipients import discover_job_recipients


def _write_yaml(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(content).strip() + "\n", encoding="utf-8")


class TestDiscoverJobRecipients:
    @pytest.mark.unit
    def test_returns_empty_without_global_config(self, tmp_path: Path) -> None:
        root = tmp_path / ".teleclaude"
        (root / "people").mkdir(parents=True, exist_ok=True)

        assert discover_job_recipients("digest", "subscription", root=root) == []

    @pytest.mark.unit
    def test_subscription_jobs_return_matching_enabled_subscribers_only(self, tmp_path: Path) -> None:
        root = tmp_path / ".teleclaude"
        _write_yaml(
            root / "teleclaude.yml",
            """
            people:
              - name: Alice Example
                username: alice
                email: alice@example.com
                role: member
              - name: Bob Example
                username: bob
                email: bob@example.com
                role: admin
            """,
        )
        _write_yaml(
            root / "people" / "alice" / "teleclaude.yml",
            """
            creds:
              telegram:
                user_name: alice
                user_id: 101
            subscriptions:
              - type: job
                job: digest
                notification:
                  preferred_channel: email
                  email: alice@example.com
            """,
        )
        _write_yaml(
            root / "people" / "bob" / "teleclaude.yml",
            """
            creds:
              telegram:
                user_name: bob
                user_id: 202
            subscriptions:
              - type: job
                job: digest
                enabled: false
            """,
        )

        recipients = discover_job_recipients("digest", "subscription", root=root)

        assert len(recipients) == 1
        assert recipients[0][0].telegram.user_name == "alice"
        assert recipients[0][1].preferred_channel == "email"
        assert recipients[0][1].email == "alice@example.com"

    @pytest.mark.unit
    def test_system_jobs_include_admins_and_explicit_subscribers(self, tmp_path: Path) -> None:
        root = tmp_path / ".teleclaude"
        _write_yaml(
            root / "teleclaude.yml",
            """
            people:
              - name: Alice Admin
                username: alice
                email: alice@example.com
                role: admin
              - name: Bob Member
                username: bob
                email: bob@example.com
                role: member
              - name: Charlie Broken
                username: charlie
                email: charlie@example.com
                role: member
            """,
        )
        _write_yaml(
            root / "people" / "alice" / "teleclaude.yml",
            """
            creds:
              telegram:
                user_name: alice
                user_id: 101
            """,
        )
        _write_yaml(
            root / "people" / "bob" / "teleclaude.yml",
            """
            creds:
              telegram:
                user_name: bob
                user_id: 202
            subscriptions:
              - type: job
                job: nightly
                notification:
                  preferred_channel: discord
            """,
        )
        (root / "people" / "charlie").mkdir(parents=True, exist_ok=True)
        (root / "people" / "charlie" / "teleclaude.yml").write_text("creds: [broken\n", encoding="utf-8")

        recipients = discover_job_recipients("nightly", "system", root=root)

        assert [(creds.telegram.user_name, notification.preferred_channel) for creds, notification in recipients] == [
            ("alice", "telegram"),
            ("bob", "discord"),
        ]
