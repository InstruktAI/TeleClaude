---
description: Inspect, mutate, and diagnose TeleClaude machine configuration through
  its agent-facing CLI authority.
activation_trigger: Use whenever an agent needs to inspect, change, repair, or validate
  TeleClaude machine configuration.
---

# Machine Config Editing — Procedure

## Required reads

None.

## Goal

Change TeleClaude machine configuration through the supported agent surface while preserving the config context’s validation, serialization, and concurrency guarantees.

## Preconditions

- The intended configuration outcome is known.
- The applicable `telec config` command is available through `telec config --help`.

## Steps

1. Inspect current values with `telec config computer get [paths...]` when the mutation requires current-state context; the read also returns the revision the mutation carries. Do not inspect the backing file directly.
2. Select the semantic `telec config` operation that owns the change. Use `telec config computer patch --revision <revision>` for general field mutation, with `null` for a field to remove, and the narrower `env`, `notify`, `tts`, or `wizard` surface when that command owns the intent. A stale revision is refused; read again and reapply the change.
3. Invoke the operation once. The config context reads the latest committed document under its transaction, applies the operation, validates the complete candidate, and atomically replaces the file.
4. Treat a successful result as the completed mutation. Do not run `telec config validate` as post-write confirmation.
5. Use `telec config validate` only to diagnose existing configuration state or to investigate a failed mutation.

## Outputs

- A validated machine-config mutation committed through the config context, or a diagnostic that identifies why no mutation occurred.

## Recovery

- If validation rejects the candidate, correct the requested values and invoke the owning CLI operation again; do not edit the backing file.
- If no CLI operation can express the required mutation, record or route the missing capability as a tooling gap and leave configuration unchanged.

- When the daemon is unavailable, recover it by inspecting and editing the configuration files directly under the exception in `general/policy/machine-config-mutation-authority`. Once available, use its ordinary configuration commands again. This agent-operated recovery is separate from client execution.

## Discipline

The failure this procedure prevents is an agent bypassing the config context because the backing YAML file appears easier to edit. That bypass loses pre-write validation, transaction-wide locking, and ownership. The command surface is the operation; the file is an implementation detail.

## See Also

- ~/.teleclaude/docs/general/policy/machine-config-mutation-authority.md
