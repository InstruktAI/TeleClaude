# Input: public-website-blog

## The Vision

TeleClaude needs a public face. Not a docs site, not a GitHub README — a beautiful,
opinionated website that represents the philosophy, the platform, and the ongoing work.

The website is the statement. The blog is the proof.

## What this is

A public website for InstruktAI / TeleClaude with:

1. **Landing page** — the main entry point. Beautiful, distinctive, representing the
   philosophy of human-AI collaboration. This is the first impression. It must be
   extraordinary. Not a template. Not generic SaaS marketing. Something that reflects
   the breath, attunement, and proprioception that define the platform.

2. **Blog section** — prominently in top navigation, not the landing page itself.
   Blog posts are the ongoing public record of discoveries, conversations, and
   breakthroughs. The long-term goal: deep AI conversations naturally exhale into
   blog posts (session → narrative → publication). For now: manual authoring with
   AI assistance, published through the platform.

3. **Content that tells a story** — not feature lists. Storytelling about what was
   discovered, how human-AI collaboration actually works, what the philosophy means
   in practice. Each post is a window into the working relationship.

## Constraints

- Must be hostable independently (not behind the TeleClaude daemon).
- Should be a modern, performant static or SSR site.
- Technology: to be decided during prepare (Next.js, Astro, or similar).
- Design must be distinctive — no generic templates. The frontend-design skill
  and approach should be leveraged.
- Blog content format: Markdown-based, easy for AI to generate and humans to edit.
- Publication workflow: to be designed (could start simple, evolve toward automated).

## Broader context

This is the first step toward outbound capabilities — the platform speaking to the
world, not just listening. Future work (separate todos) will build on this:

- Automated session-to-blog-post pipeline.
- Social media publishing and campaigning.
- The global registry of federated TeleClaude instances.

## Why now

The platform has reached a point where the work speaks for itself. Agent shorthand,
direct conversation, breath methodology, context engineering — these are innovations
worth sharing. The meetups are starting. A YouTube channel is planned. The website
is the anchor for all of that outreach.

---

## Creative Direction (enriched 2026-03-15)

### Format

One-page scroller. Not a multi-page site. The landing page IS the experience.
Blog lives in navigation but is a separate route, not part of the scroll.

### Two audiences

1. **AI developers** — frustrated with fragmented tooling, siloed agent CLIs,
   lost context between sessions and machines. They want infrastructure, not
   another wrapper framework.

2. **Small business owners** — tired of doing bookkeeping, inbound/outbound,
   creative work, and programming manually. They want automation for everything
   they currently do by hand. Non-technical. They need to see the promise, not
   the architecture.

### Visual DNA

The website inherits from the TUI's visual identity:

- **Commodore 64 / Tetris block-character aesthetic** from the TELECLAUDE banner
- **Neon color wash animations** (cyan, magenta, gold gradients over dark surfaces)
- **Living sky** — drifting entities, stars, atmospheric depth
- **Deep purple-black canvas** as the default mode
- **Agent color palette**: Claude amber, Gemini lavender, Codex blue

The existing TUI screenshots and banner animation are the primary visual references.
See `assets/screenshots/tui/` and `teleclaude/cli/tui/widgets/banner.py`.

### Content arc (scroll journey)

Six landing zones, each a self-contained immersive experience with sub-use-cases
that animate into place. Each zone has its own visual flavor within the shared
aesthetic — the frontender chooses the styling per zone.

1. **"From idea to shipped code"** — Full SDLC engine. Sub-use-cases:
   requirements discovery, build & review, quality gates, delivery.

2. **"Your AI creative agency"** — Creative lifecycle. Sub-use-cases:
   design discovery, art generation, visual prototyping, implementation.

3. **"A help desk that never sleeps"** — Customer support. Sub-use-cases:
   multi-channel ingress, persistent memory, seamless escalation, intelligence extraction.

4. **"Your AI, everywhere you are"** — Multi-platform access. Sub-use-cases:
   terminal, phone/voice, browser, cross-device continuity.

5. **"Intelligence that compounds"** — Memory flywheel. Sub-use-cases:
   knows your code, knows your customers, knows your team, precision context.

6. **"Meet the agents"** — Claude, Gemini, Codex. Their distinct personalities,
   how they collaborate, their own testimonials. This is the ONLY section where
   agent identity colors appear prominently. The agents are a use case, not
   infrastructure.

Each landing zone captures attention with rich CSS scroll-driven animations.
No jargon — business value language accessible to both audiences.

### Personality

The TeleClaude logo (robot with peace sign, "SKYNET IS HERE") sets the tone:
confident, a little irreverent, self-aware about AI's gravity but not taking
itself too seriously. The website should feel like discovering something
underground and powerful — not corporate marketing.

### Reference sites (enriched 2026-03-15)

Four external references analyzed and captured in `input/reference-analysis.md`:

1. **warp.dev** — competition; how they present features with real product screenshots
2. **freefrontend.com/sticky-text-reveal** — beautiful scroll-driven text reveal
   animation; `background-clip: text` + `view-timeline` technique
3. **codepen.io/jh3y/pen/MYgBprZ** — scroll-driven stroke-to-fill text effect
4. **magic-receipt.ai** — VERY good scroll animation choreography: scanning frame
   with progress bar + monospace status text, marquee text dividers, step carousel

Screenshots saved in `input/ref-*.png`.

### Color system direction

Break the Tailwind primary/secondary paradigm. Define semantic color scales
by name — `canvas`, `claude`, `gemini`, `codex`, `neon`, `neutral` — each with
a full shade range. No generic roles. Every color has meaning.
