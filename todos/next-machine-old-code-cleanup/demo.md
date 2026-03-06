# Demo: next-machine-old-code-cleanup

## Validation

```bash
# 1. Verify finalize lock references removed from target docs
import pathlib

target_docs = [
    'docs/global/software-development/procedure/lifecycle/finalize.md',
    'docs/project/design/architecture/next-machine.md',
    'docs/global/software-development/concept/finalizer.md',
    'docs/project/design/architecture/session-lifecycle.md',
]

stale_terms = ['.finalize-lock', 'acquire_finalize_lock', 'release_finalize_lock',
               'get_finalize_lock_holder', 'orchestrator-owned apply']

for doc_path in target_docs:
    content = pathlib.Path(doc_path).read_text()
    for term in stale_terms:
        assert term not in content, f'Stale reference "{term}" found in {doc_path}'

print('PASS: No stale finalize lock references in target docs')
```

```bash
# 2. Verify integrator is mentioned in next-machine dispatch table
content = pathlib.Path('docs/project/design/architecture/next-machine.md').read_text()
assert 'integrator' in content.lower(), 'Integrator not mentioned in next-machine.md'
print('PASS: Integrator referenced in next-machine architecture doc')
```

```bash
# 3. Verify finalize procedure describes integrator handoff
content = pathlib.Path('docs/global/software-development/procedure/lifecycle/finalize.md').read_text()
assert 'integrator' in content.lower(), 'Integrator not mentioned in finalize procedure'
assert 'queue' in content.lower() or 'event' in content.lower(), \
    'Finalize procedure missing event/queue handoff description'
print('PASS: Finalize procedure describes integrator handoff')
```

## Guided Presentation

### Step 1: Show the problem — stale documentation

Open `docs/project/design/architecture/next-machine.md` and search for "Finalize Lock".
Observe that the old section describing file-based locks is gone. In its place (or in the
dispatch table), the integrator role appears.

### Step 2: Verify finalize procedure

Open `docs/global/software-development/procedure/lifecycle/finalize.md`. Stage A (worker
prepare) is unchanged. Stage B now describes integrator handoff: the orchestrator emits an
event and moves on, the singleton integrator processes the candidate from its queue.

### Step 3: Verify concept alignment

Open `docs/global/software-development/concept/finalizer.md`. The concept now accurately
describes the two-stage model: worker finalize-prepare + integrator apply.

### Step 4: Verify session lifecycle cleanup

Open `docs/project/design/architecture/session-lifecycle.md`. Step 9 (Resource Cleanup)
no longer mentions finalize lock release — that mechanism no longer exists.
