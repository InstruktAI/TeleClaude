"""Company onboarding: deterministic scaffolding primitives and the AI dispatch.

Side-effecting, judgment-laden steps (the profile question, snippet generation)
live in the company-onboarding agent procedure; this package owns only the
deterministic primitives — folder scaffolding, inbox SHA tracking, and the
fire-and-forget analysis dispatch.
"""

from teleclaude.company_setup.onboard_flow import (
    compute_inbox_changes,
    record_processed_files,
    run_company_onboard,
    scaffold_company,
)

__all__ = [
    "compute_inbox_changes",
    "record_processed_files",
    "run_company_onboard",
    "scaffold_company",
]
