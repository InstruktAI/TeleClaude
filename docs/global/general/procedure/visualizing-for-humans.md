---
description: Produce the right visual form when a human needs to see something — a table, Mermaid source, or, exceptionally, a live canvas.
activation_trigger: Use when the human asks to see, draw, sketch, map, diagram, or visualize something — architecture, a flow, a sequence, a state machine, a decision, ownership, a timeline — or when a picture would land better than prose. Also activate before starting any canvas, whiteboard, or drawing server.
---

# Visualizing for Humans — Procedure

## Goal

Give the human a picture they can read, in the cheapest form that answers their
question. The agent is always the author; the human reads and reacts. Reserve
heavyweight canvas tooling for the rare case that genuinely needs it.

## Preconditions

- The question the picture must answer is known, or is asked before drawing.
- The material is grounded. A diagram asserts structure with more authority than
  prose, so drawing something unverified spreads a guess in a form that looks
  like a finding.
- Charts and data visualization are out of scope; that is the `dataviz` skill's
  territory.

## Steps

1. **Name the question the picture answers.** The common ones: _what exists and
   how is it wired_, _what happens in what order and what is passed_, _how is
   this decided_, _what states can this be in_, _who owns what_. Different
   questions want different pictures, and a picture that answers none of them is
   decoration. When the question is not obvious from the request, ask it rather
   than defaulting to boxes and lines.

2. **Pick the form by one discriminator: is the arrangement derivable from the
   relations, or is the arrangement itself the information?**
   - _Derivable_ — a sequence, a decision chain, a state machine, a dependency
     graph, an entity model. What connects to what determines the layout, so a
     layout engine draws it better than any hand placement. Use **Mermaid**.
   - _Not derivable_ — containment, zones, adjacency, relative size, "these are
     peers and that one contains them". Those facts are not edges, so no engine
     can infer them. Hand placement on a **canvas** is the only way to state
     them — and only under step 5's test.
   - _Neither_ — the content is an enumeration: who owns what, what each layer is
     responsible for, which gate applies where. A **markdown table** is more
     precise than any drawing, diffs cleanly, and needs no interpretation. Many
     requests to "draw this" are table requests.

3. **Default to Mermaid, and treat its source as the artifact.** Write it as a
   fenced block in the document that owns the contract, or as a `.mmd` file
   beside the work. Text diffs, versions with what it describes, renders
   wherever markdown renders, and reads directly as structure for the next
   agent — which no drawing does. Prefer `LR` over `TD` when a chain of
   decisions runs long, or the result sprawls vertically.

4. **Hand the human something they can open.** A path to the source when their
   surface renders Mermaid, or a rendered image when it does not. Do not make
   them install or learn anything.

5. **Escalation test — before starting any canvas server.** Both conditions must
   hold: the arrangement carries meaning the relations do not, **and** a person
   will actually manipulate the shapes. The words "collaborate", "scratchpad",
   "whiteboard", or "diagram" appearing in the request are not the test. If a
   human is only going to look at the result, Mermaid serves them better and
   costs a fraction. When the test passes, follow
   `software-development/procedure/architecture-canvas` for the mechanics.

6. **Revise from the human's words, not from their edits.** Collaboration here
   means: the agent shows, the human reacts in prose, the agent re-authors the
   source and re-renders. Never wait for the human to draw, and never assume
   they will learn a tool to be understood.

7. **Promote nothing by default.** A picture is an aid, not a contract. Durable
   material follows the documentation rules of whatever owns it; Mermaid source
   travels inside that snippet, and exploratory renders stay in the scratchpad.

## Outputs

- A picture in the cheapest sufficient form, delivered so the human can open it.
- Its source stored where the work lives — in the owning snippet, or in the
  activity's scratchpad workspace.

## Recovery

- **Mermaid fails to parse.** Simplify the labels before changing tools:
  parentheses, `+`, and `--` inside message text are the usual culprits.
- **Hand-placed elements keep colliding and coordinates need tuning.** That is a
  layout engine's job — the form was chosen wrong. Move to Mermaid.
- **Mermaid subgraphs will not express containment or adjacency.** The
  arrangement is the content; re-run step 5's test before reaching for a canvas.
- **A canvas server was started without the test passing.** Stop it, deliver the
  Mermaid, and keep the scratchpad clean.
