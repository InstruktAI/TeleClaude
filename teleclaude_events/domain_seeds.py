"""Default event domain configuration for the four business pillars."""

from __future__ import annotations

from typing import Any

DEFAULT_EVENT_DOMAINS: dict[str, Any] = {
    "domains": {
        "software-development": {
            "name": "software-development",
            "enabled": True,
            "guardian": {
                "agent": "claude",
                "mode": "med",
                "enabled": True,
                "evaluation_prompt": (
                    "Software development domain guardian: monitor todo lifecycle, "
                    "build health, and deployment patterns. Detect stalled todos, "
                    "repeated build failures, and deployment anomalies."
                ),
            },
            "autonomy": {
                "by_cartridge": {
                    "software-development/todo-lifecycle": "auto_notify",
                    "software-development/build-notifier": "notify",
                    "software-development/deploy-tracker": "notify",
                },
            },
        },
        "marketing": {
            "name": "marketing",
            "enabled": True,
            "guardian": {
                "agent": "claude",
                "mode": "med",
                "enabled": True,
                "evaluation_prompt": (
                    "Marketing domain guardian: monitor content quality, campaign "
                    "budget escalation thresholds, and signal synthesis quality. "
                    "Flag budget overruns and stalled content pipelines."
                ),
            },
            "autonomy": {
                "by_cartridge": {
                    "marketing/content-pipeline": "notify",
                    "marketing/campaign-budget-monitor": "notify",
                    "marketing/feed-monitor": "auto_notify",
                },
            },
        },
        "creative-production": {
            "name": "creative-production",
            "enabled": True,
            "guardian": {
                "agent": "claude",
                "mode": "med",
                "enabled": True,
                "evaluation_prompt": (
                    "Creative production domain guardian: monitor asset quality "
                    "standards, review cycle norms, and multi-format delivery. "
                    "Detect stalled review cycles and SLA breaches."
                ),
            },
            "autonomy": {
                "by_cartridge": {
                    "creative-production/asset-lifecycle": "notify",
                    "creative-production/review-gatekeeper": "notify",
                },
            },
        },
        "customer-relations": {
            "name": "customer-relations",
            "enabled": True,
            "guardian": {
                "agent": "claude",
                "mode": "med",
                "enabled": True,
                "trust_threshold": "strict",
                "evaluation_prompt": (
                    "Customer relations domain guardian: external input threat model, "
                    "escalation decision criteria, customer data sensitivity. "
                    "Require human confirmation for all escalation and satisfaction actions. "
                    "Never act autonomously on external customer inputs."
                ),
            },
            "autonomy": {
                "by_cartridge": {
                    "customer-relations/helpdesk-triage": "notify",
                    "customer-relations/escalation-handler": "notify",
                    "customer-relations/satisfaction-tracker": "notify",
                },
            },
        },
    }
}
