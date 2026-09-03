"""Shared pre-creation validity prompt for todo entry surfaces."""

CREATION_VALIDITY_GATE_ITEM = (
    "- Validity — create only work whose intent and known contract have converged. If either is still forming,\n"
    "   create nothing; hold and icebox do not make it valid.\n\n"
    "- Direct execution — if the settled work belongs in-context, execute it with the authority already held\n"
    "   and create no lifecycle record.\n\n"
    "Authority: software-development/policy/todo-creation-discipline.\n"
)


def render_todo_creation_gate(approval_flag: str) -> str:
    return (
        "Nothing was created. Face these before this work enters the lifecycle\n"
        "(software-development/policy/todo-creation-discipline governs every one):\n\n"
        f"{CREATION_VALIDITY_GATE_ITEM}\n"
        "- Doc-only - documentation, ADRs, README, agent artifacts? After the\n"
        "   applicable authoring gate opens, execute it in-context per\n"
        "   general/policy/documentation-discipline; create no todo, whatever its size.\n\n"
        "- Existing home - already covered, or a small addition to a todo that\n"
        "   has not started build? Amend it instead of creating a sibling:\n"
        "     telec todo list\n"
        "     telec todo artifacts read <slug> input\n\n"
        "- Ownership & authority - owning project of the changed files correct\n"
        "   (--project-root)? A process-layer change carries a live human\n"
        "   decision per software-development/policy/process-change-authority?\n"
        "   A human who shaped this filing declared (--human-involved)?\n\n"
        "Only once these are faced, create with:\n"
        f"  telec todo create {approval_flag} <slug> <content> --kind <feature|change|bug|task>\n"
    )


__all__ = ["CREATION_VALIDITY_GATE_ITEM", "render_todo_creation_gate"]
