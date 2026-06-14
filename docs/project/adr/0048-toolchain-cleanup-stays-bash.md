---
date: '2026-06-13'
number: '48'
visibility: 'public'
description: "TeleClaude's toolchain cleanup stays in bash; the planned rewrite of the installer and quality recipes into Python is rejected."
---

# Toolchain cleanup stays bash; Python rewrite rejected — ADR

## Context

TeleClaude's toolchain cleanup needed a language decision. A Python direction had
been planned: rewrite the ~1086-line `bin/install.sh` into a testable Python
installer and move the Makefile's quality orchestration into Python, on the
argument that shell is untestable and unlintable. The competing fact: the
installer is ~90% idempotent shell-out — detect a tool, else `brew`/`apt`/`curl|sh`,
copy, symlink, adjust PATH.

## Decision

The installer and the relocated quality orchestration stay bash. The Python
rewrite is rejected.

## Consequences

- The cleanup proceeds in shell. There is no testable-installer guarantee:
  install correctness stays verified by observable behavior, as is appropriate
  for shell-out. Install logic that genuinely earns a test moves into the
  existing Python config helpers, not a wholesale rewrite.
- The rejected Python direction must not be resurrected without revisiting this
  record.

## Alternatives Considered

- **Rewrite the installer and quality recipes into Python.** Rejected: idempotent
  shell-out is not logic a Python port makes safer — a Python wrapper over
  `brew`/`curl|sh` yields only a mock-echo test surface ("assert that brew was
  called"), the fake-test anti-pattern the platform forbids. The genuinely
  logic-bearing config already lives in Python helpers
  (`bin/init/configure_agent_cli.py` and the inline YAML helper); the problem to
  solve was inline Makefile logic and install-path divergence, both addressable
  in bash.
