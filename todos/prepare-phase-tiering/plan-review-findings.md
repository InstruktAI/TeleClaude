# Plan Review Findings: prepare-phase-tiering

Critical:
- `implementation-plan.md` still does not reconcile the repo's current work-entry gates with the proposed Tier 3 and split-inherited direct-build paths. The plan sends Tier 3 todos and children inheriting an approved implementation plan straight to `prepare_phase=prepared` ([implementation-plan.md](/Users/Morriz/Workspace/InstruktAI/TeleClaude/todos/prepare-phase-tiering/implementation-plan.md):131 and [implementation-plan.md](/Users/Morriz/Workspace/InstruktAI/TeleClaude/todos/prepare-phase-tiering/implementation-plan.md):220), but `next_work()` currently rejects work items that lack `requirements.md`, `implementation-plan.md`, or `dor.score >= 8` ([core.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/teleclaude/core/next_machine/core.py):1641 and [core.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/teleclaude/core/next_machine/core.py):3667). The approved requirements also mark Phase B changes out of scope while requiring those items to be claimable immediately ([requirements.md](/Users/Morriz/Workspace/InstruktAI/TeleClaude/todos/prepare-phase-tiering/requirements.md):39 and [requirements.md](/Users/Morriz/Workspace/InstruktAI/TeleClaude/todos/prepare-phase-tiering/requirements.md):91). The drafter needs to resolve that contract mismatch explicitly before this plan can be approved.

Important:

Suggestions:
