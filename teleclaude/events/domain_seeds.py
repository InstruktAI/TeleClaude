"""Default event domain configuration for the three business pillars."""

from __future__ import annotations

from teleclaude.core.models import JsonDict

DEFAULT_EVENT_DOMAINS: JsonDict = {
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
    }
}
