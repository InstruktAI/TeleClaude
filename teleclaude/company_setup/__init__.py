"""Company onboarding: deterministic scaffolding primitives.

Side-effecting, judgment-laden steps (the profile question, snippet generation)
live in the company-onboarding agent procedure, dispatched explicitly via
`telec sessions run`; this package owns only the deterministic primitives —
folder scaffolding and inbox SHA tracking.
"""

from teleclaude.company_setup.onboard_flow import (
    compute_inbox_changes,
    record_processed_files,
    scaffold_company,
)

__all__ = [
    "compute_inbox_changes",
    "record_processed_files",
    "scaffold_company",
]
