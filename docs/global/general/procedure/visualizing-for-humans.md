---
description: Produce the right visual form when a human needs to see something — a table, Mermaid, or, exceptionally, a live canvas — and deliver it rendered, inline for a one-off answer and as a served scratchpad page for material that keeps changing.
activation_trigger: Use when the human asks to see, draw, sketch, map, diagram, or visualize something — architecture, a flow, a sequence, a state machine, a decision, ownership, a timeline — or when a picture would land better than prose. Also activate before starting any canvas, whiteboard, or drawing server.
---

# Visualizing for Humans — Procedure

## Goal

Give the human a picture they can read, in the cheapest form that answers their
question, delivered rendered. The human reads on whatever device they are on,
phones included, where markdown tables and Mermaid source arrive as plain text;
a rich page reads at a glance. The agent is always the author; the human reads
and reacts. Reserve heavyweight canvas tooling for the rare case that genuinely
needs it.

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

4. **Deliver it rendered, in the form that fits its life in the session.** Read
   from the conversation whether the material is settled or still moving:
   - _One-off_ — the answer to a question asked once and done: a
     self-contained HTML page as an inline visual reply, where the runtime
     offers one.
   - _Living_ — material that is still converging, that the human returns to,
     or that this session or a handoff will extend (a design taking shape, an
     overview, a report): a page in the activity's scratchpad workspace
     (`general/procedure/scratchpad-workspace`). Its `index.html` links the
     workspace's pages, and a static web server started on the workspace
     folder serves it. Runtimes that detect local web servers offer it to the
     human at once, on every device the runtime reaches; revising the page and
     refreshing shows the change.

   The source from step 3 stays where it lives; the rendered page is what the
   human reads. Hand them something that opens, never a file path on a machine
   they are not at, and never something to install or learn.

5. **Escalation test — before starting any canvas server.** Both conditions must
   hold: the arrangement carries meaning the relations do not, **and** a person
   will actually manipulate the shapes. The words "collaborate", "scratchpad",
   "whiteboard", or "diagram" appearing in the request are not the test. If a
   human is only going to look at the result, Mermaid serves them better and
   costs a fraction. When the test passes, follow
   `sdlc/procedure/architecture-canvas` for the mechanics.

6. **Revise from the human's words, not from their edits.** Collaboration here
   means: the agent shows, the human reacts in prose, the agent re-authors the
   source and re-renders. Never wait for the human to draw, and never assume
   they will learn a tool to be understood.

7. **Promote nothing by default.** A picture is an aid, not a contract. Durable
   material follows the documentation rules of whatever owns it; Mermaid source
   travels inside that snippet, and exploratory renders stay in the scratchpad.

## Outputs

- A picture in the cheapest sufficient form, delivered rendered: inline for a
  one-off answer, a served scratchpad page for living material.
- Its source stored where the work lives — in the owning snippet, or in the
  activity's scratchpad workspace.

## Recovery

- **Mermaid fails to parse.** Simplify the labels before changing tools:
  parentheses, `+`, and `--` inside message text are the usual culprits.
- **Hand-placed elements keep colliding and coordinates need tuning.** That is a
  layout engine's job — the form was chosen wrong. Move to Mermaid.
- **Mermaid subgraphs will not express containment or adjacency.** The
  arrangement is the content; re-run step 5's test before reaching for a canvas.
- **The human received source instead of a picture** (a raw table, Mermaid
  text, a path). Render it and deliver it under step 4.
- **Living material was delivered as an inline reply** and keeps being
  revised. Move it to a page in the scratchpad workspace and serve it.
- **A canvas server was started without the test passing.** Stop it, deliver the
  Mermaid, and keep the scratchpad clean.
