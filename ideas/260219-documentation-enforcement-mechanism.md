# Idea: Implement Documentation Enforcement Mechanism

## Problem

Multiple discipline memories exist around documentation standards but no enforcement mechanism:

- ID 3: Module docstrings must be substantive (not one-liners) with purpose, inputs, outputs, integration
- ID 22: Artifacts describe target state, never transition state (no "not yet", "legacy", "will be")
- ID 24: AGENTS.md is generated from AGENTS.master.md (edit source, not output)

These are documented principles but violations still occur. Agents know the rules but don't consistently apply them.

## Observation

- Documentation discipline is a recurring friction point
- User frustration suggests principles are being re-explained instead of automatically enforced
- Violations are caught in review, but preventing them upstream would save cycles
- All three memories are classification "friction" or "gotcha"

## Opportunity

Implement multi-level enforcement:

1. **Linting**: Static checks in pre-commit hooks or CI
   - Module docstring presence and minimum length (200+ chars)
   - Generated file detection (AGENTS.md, etc.) with error on direct edits
   - Artifact state language scanning (flag "not yet", "legacy", "TODO (future)")

2. **AI Prompt Integration**:
   - Include enforcement rules in agent initialization
   - Add docstring requirement to code-generation prompts
   - Embed target-state-first principle in artifact authoring guidelines

3. **Code Review Automation**:
   - Automatic comment on PRs that violate standards
   - Link to enforcement rationale (memories/docs)

## Estimated Value

Medium-High. Prevents repeated friction cycles and scales documentation discipline.

## Risks

- Over-enforcement (false positives on legitimate transition content)
- Lint rule maintenance (docstring quality is subjective)
- Integration complexity (hooks + CI + prompts)

## Next Steps

1. Audit current pre-commit hooks for enforcement coverage
2. Design lint rules for docstring quality and artifact state language
3. Prototype with AGENTS.md generated-file detection (highest impact, lowest false positive rate)
4. Extend to module docstring enforcement in Python code
