"""TeleClaude jobs — scheduled task definitions.

Job modules define what work to do. Scheduling is configured in teleclaude.yml,
not in the job code. See docs/project/design/architecture/jobs-runner.md.
"""

from jobs.base import Job

__all__ = ["Job"]
