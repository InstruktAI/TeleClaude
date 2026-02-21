"""Discover notification recipients for job results based on subscriptions."""

from __future__ import annotations

from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.config.loader import load_global_config, load_person_config
from teleclaude.config.schema import (
    CredsConfig,
    JobSubscription,
    SubscriptionNotification,
    SubscriptionsConfig,
)

logger = get_logger(__name__)


def discover_job_recipients(
    job_name: str,
    job_category: str,
    *,
    root: Path | None = None,
) -> list[tuple[CredsConfig, SubscriptionNotification]]:
    """Find all people who should receive results for a given job.

    For subscription jobs: returns people with a matching enabled JobSubscription.
    For system jobs: returns all admins plus any explicit enabled subscribers (deduped).
    """
    if root is None:
        root = Path.home() / ".teleclaude"

    global_cfg_path = root / "teleclaude.yml"
    if not global_cfg_path.exists():
        return []

    global_cfg = load_global_config(global_cfg_path)

    # Build email -> PersonEntry lookup for role checks
    people_by_email: dict[str, str] = {}  # email -> role
    for person in global_cfg.people:
        people_by_email[person.email] = person.role

    # Build person directory name -> email lookup
    email_by_dir: dict[str, str] = {}
    for person in global_cfg.people:
        key = person.name.lower().replace(" ", "")
        email_by_dir[key] = person.email
        if person.username:
            email_by_dir[person.username.lower()] = person.email

    people_dir = root / "people"
    if not people_dir.is_dir():
        return []

    recipients: list[tuple[CredsConfig, SubscriptionNotification]] = []
    seen_emails: set[str] = set()

    for person_dir in sorted(people_dir.iterdir()):
        if not person_dir.is_dir():
            continue
        person_cfg_path = person_dir / "teleclaude.yml"
        if not person_cfg_path.exists():
            continue

        try:
            person_cfg = load_person_config(person_cfg_path)
        except Exception as exc:
            logger.error("skipping bad person config", path=str(person_cfg_path), error=str(exc))
            continue

        dir_key = person_dir.name.lower().replace(" ", "")
        email = email_by_dir.get(dir_key, f"{person_dir.name}@local")
        role = people_by_email.get(email, "member")

        subs = person_cfg.subscriptions
        has_matching_sub = False
        sub_notification = SubscriptionNotification()

        if not isinstance(subs, SubscriptionsConfig):
            for sub in subs:
                if isinstance(sub, JobSubscription) and sub.job == job_name and sub.enabled:
                    has_matching_sub = True
                    sub_notification = sub.notification
                    break

        if job_category == "subscription":
            if has_matching_sub and email not in seen_emails:
                seen_emails.add(email)
                recipients.append((person_cfg.creds, sub_notification))
        elif job_category == "system":
            if email not in seen_emails:
                if role == "admin" or has_matching_sub:
                    seen_emails.add(email)
                    recipients.append((person_cfg.creds, sub_notification))

    return recipients
