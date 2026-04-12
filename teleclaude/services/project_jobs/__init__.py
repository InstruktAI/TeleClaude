"""Project-job orchestration package.

Public exports:
    ProjectJobOrchestrator — iterate catalog projects subscribed to a job and
    dispatch a per-project executor for each.
"""

from teleclaude.services.project_jobs.orchestrator import ProjectJobOrchestrator

__all__ = ["ProjectJobOrchestrator"]
