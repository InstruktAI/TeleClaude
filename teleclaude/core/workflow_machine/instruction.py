"""The instruction an entry verb returns to the holding driver.

Every element comes from the item's state and the driver's governing publication, so a change to the
procedure headers changes the instruction with no code change
(``local/projects/teleclaude/spec/feature/workflow/item-lifecycle``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from teleclaude.entry_declarations import EndingAct, EntryDeclarations, WorkflowDeclaration
from teleclaude.types.workflow_record import Act, Phase

HOLDING_TEMPLATE: Final = "You hold {item}, now in {phase}. Your session {session} is its claim."
WORKTREE_TEMPLATE: Final = "Branch {branch} in worktree {worktree}: the builder works only there."
CHILD_TEMPLATE: Final = (
    "Start your child with `telec todo child {item}`: {procedure} as {role}, launched with "
    "agents {agents} at {mode} thinking."
)
CHILD_RUNNING_TEMPLATE: Final = "Your child {sessions} is running; continue with it."
ACT_TEMPLATE: Final = "- `telec todo act {item} {act}{arguments}` -> {leads_to}"
ACT_HEADING: Final = "The acts that end this phase and the phase each leads to:"
OTHER_ACTS_TEMPLATE: Final = "Record anything else with `telec todo act {item} <act>`: note, reviewed, finding, reply, waiting, kickback, release."
SEPARATOR: Final = " "
LIST_SEPARATOR: Final = ", "
LINE_SEPARATOR: Final = "\n"
ACT_ARGUMENTS: Final[Mapping[Act, str]] = {
    Act.PREPARED: " --revision <digest of the intent body you judged>",
    Act.WAITING: " --person <slug> <the question>",
    Act.STAMP: " --sha <integration head>",
    Act.KICKBACK: " <reason>",
}
NO_ARGUMENTS: Final = ""


@dataclass(frozen=True)
class InstructionFacts:
    """What the instruction states."""

    item: str
    phase: Phase
    session_id: str
    branch: str
    worktree: str
    child_sessions: Sequence[str]


def _ending_act_line(item: str, ending: EndingAct) -> str:
    return ACT_TEMPLATE.format(
        item=item,
        act=ending.act.value,
        arguments=ACT_ARGUMENTS.get(ending.act, NO_ARGUMENTS),
        leads_to=ending.leads_to.value,
    )


def render_instruction(
    facts: InstructionFacts,
    workflow: WorkflowDeclaration,
    child: EntryDeclarations,
) -> str:
    """The instruction for the holding driver of one phase."""
    lines = [HOLDING_TEMPLATE.format(item=facts.item, phase=facts.phase.value, session=facts.session_id)]
    if facts.worktree:
        lines.append(WORKTREE_TEMPLATE.format(branch=facts.branch, worktree=facts.worktree))
    if facts.child_sessions:
        lines.append(CHILD_RUNNING_TEMPLATE.format(sessions=LIST_SEPARATOR.join(facts.child_sessions)))
    else:
        dispatch = child.dispatch
        lines.append(
            CHILD_TEMPLATE.format(
                item=facts.item,
                procedure=workflow.child,
                role=child.role.name.value,
                agents=LIST_SEPARATOR.join(agent.value for agent in dispatch.agents) if dispatch else NO_ARGUMENTS,
                mode=dispatch.thinking_mode.value if dispatch else NO_ARGUMENTS,
            )
        )
    lines.append(ACT_HEADING)
    lines.extend(_ending_act_line(facts.item, ending) for ending in workflow.acts)
    lines.append(OTHER_ACTS_TEMPLATE.format(item=facts.item))
    return LINE_SEPARATOR.join(lines)
