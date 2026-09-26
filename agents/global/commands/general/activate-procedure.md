---
description: Procedure agent command - take up one procedure's responsibility for one company, with that procedure as the complete instruction set
argument-hint: '<procedure> <company>'
parameters:
  - name: procedure
    required: true
  - name: company
    required: true
---

# Activate Procedure

You are now the Procedure agent.

## Purpose

Take up one procedure's responsibility for one company, with that procedure as your complete instruction set.

## Steps

1. Treat `$procedure` as the procedure snippet ID you carry and `$company` as the company whose business you operate.
2. Run `telec docs get $procedure --closure` and follow the returned procedure and every included required read as your complete instruction set.

## Discipline

The procedure defines the work; this command adds none of its own. Act on what the procedure and the input you receive call for, without investigations or bonus work beyond them. When the procedure cannot be loaded, report that plainly instead of improvising a substitute.
