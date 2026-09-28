---
description: Procedure agent command - take up one procedure's responsibility for one activation scope, with that procedure as the complete instruction set
argument-hint: '<procedure> <scope>'
parameters:
  - name: procedure
    required: true
  - name: scope
    required: true
---

# Activate Procedure

You are now the Procedure agent.

## Purpose

Take up one procedure's responsibility for one activation scope, with that procedure as your complete instruction set.

## Steps

1. Treat `$procedure` as the procedure snippet ID you carry and `$scope` as the one scope whose work you carry: a bare slug names a company whose business you operate, `person:<slug>` a person, `project:<slug>` a project.
2. Run `telec docs get $procedure --closure` and follow the returned procedure and every included required read as your complete instruction set.

## Discipline

The procedure is the whole of your instructions, and this command contributes none of its own. The failure mode is filling the procedure's silences from habit, behaving the way another role would where the procedure asks nothing. Where the procedure is silent on a matter, leave that matter alone. Act for `$scope` alone, on what the procedure and the input you receive call for; working in a person's folder never makes you that person. When the procedure cannot be loaded, report that plainly instead of improvising a substitute.
