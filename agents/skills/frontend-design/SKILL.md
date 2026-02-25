---
name: frontend-design
description: Distinctive, production-grade frontend interfaces. Use when building web components, pages, or applications to avoid generic AI aesthetics.
---

# Frontend Design

## Purpose

Produce distinctive, production-ready frontend interfaces with clear aesthetic intent, strong usability, and non-generic visual identity.

## Scope

Use when designing or implementing web UI such as components, pages, and full applications.

Design rules:

- Choose an intentional visual direction before coding.
- Match implementation complexity to the visual concept.
- Avoid generic AI-generated visual patterns and default-safe choices.

## Inputs

- Product context: audience, purpose, and primary tasks.
- Technical constraints: framework, accessibility, performance, browser support.
- Brand or tone expectations, if available.

## Outputs

- Cohesive visual direction with rationale.
- Implemented UI that reflects typography, color, motion, and layout choices consistently.
- Verification that desktop and mobile experiences both load and function correctly.
- Notes on intentional trade-offs and constraints.

## Procedure

1. Define the interface goal and the single most memorable experience outcome.
2. Pick a strong visual direction and commit to it (minimal, editorial, playful, brutalist, etc.).
3. Establish a design system baseline with CSS variables for color, spacing, and motion timing.
4. Select expressive typography that fits the concept; avoid generic default stacks.
5. Design spatial composition intentionally (asymmetry, overlap, density, or negative space as needed).
6. Add motion where it improves hierarchy and delight (for example entry choreography or reveal sequences).
7. Build atmosphere with layered backgrounds or texture rather than flat single-color defaults.
8. Validate responsiveness and usability on desktop and mobile breakpoints.
9. Refine details until the output feels authored for this context, not template-derived.

Anti-patterns to reject:

| Anti-pattern                             | Result                          | Preferred approach                             |
| ---------------------------------------- | ------------------------------- | ---------------------------------------------- |
| Default font and color stacks            | Generic, interchangeable UI     | Context-specific typography and palette        |
| Overloaded micro-interactions everywhere | Visual noise and weak hierarchy | Few meaningful motion moments                  |
| Reusing familiar boilerplate layouts     | No identity or memorability     | Composition tailored to narrative and use-case |
| Ignoring mobile until the end            | Broken real-world experience    | Design and test responsive behavior early      |
