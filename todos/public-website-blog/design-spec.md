# Design Spec: public-website-blog

## 1. Product context

### What it is

A one-page scroller landing page for TeleClaude — the unified nervous system for
distributed AI intelligence. Not a docs site, not a GitHub README, not generic SaaS
marketing. A visual statement that captures the platform's philosophy and capabilities
in a scroll journey that speaks to two audiences simultaneously.

### Target audience

**Primary: AI developers.** Engineers who use Claude, Gemini, or Codex CLIs and are
frustrated by context dying between sessions, machines, and tools. They want
infrastructure — not another LangChain wrapper. They understand terminals, tmux, and
multi-model workflows. They are looking for something opinionated and proven.

**Secondary: Small business owners.** Non-technical people drowning in manual work:
bookkeeping, inbound/outbound, creative production, basic programming tasks. They want
AI automation that just works — from their phone, across platforms, without learning
to code. They need to see the promise and feel the trust, not understand the architecture.

### Core value proposition

One supergroup. All your machines. All your agents. Infinite context.

### Emotional register

"I just found something underground and powerful that the mainstream hasn't discovered
yet." Confident, a little irreverent (the logo is a robot with a peace sign and
"SKYNET IS HERE"), technically sophisticated but not intimidating. The feeling of
walking into a hacker's workshop at 2 AM where the screens are alive and something
extraordinary is being built.

## 2. Visual identity

### Mood / aesthetic direction

**Retro-futuristic terminal.** The visual DNA comes from TeleClaude's TUI: Commodore 64
block characters, neon color gradients washing over dark surfaces, a living sky with
drifting entities. It's the intersection of 8-bit nostalgia and cutting-edge AI
infrastructure. The terminal aesthetic is the anchor — this is a platform built by
people who live in the terminal, and the website should feel like that world rendered
for the web.

Key references:

- The TELECLAUDE banner: massive Unicode block characters with animated neon color
  overlays (cyan, magenta, gold, green gradients).
- The TUI sky: moon, stars, clouds, birds, UFOs, cars — all built from Unicode
  characters. Living, breathing, atmospheric.
- The TUI dark mode: deep purple-black canvas, warm amber tones for Claude, lavender
  for Gemini, cool blue for Codex.

### What it is NOT

- Not generic SaaS landing page. No hero stock photos. No "Trusted by 10,000 companies."
- Not Material Design. Not Tailwind template. Not shadcn landing page.
- Not a documentation site dressed up as marketing.
- Not cute or playful. Confident. The playfulness is in the irreverence, not the
  visual softness.
- Not dark-for-dark's-sake. The darkness is atmospheric, not edgy.

### Logo and brand marks

The TeleClaude logo: a humanoid robot giving a peace sign, captioned "SKYNET IS HERE."
Tongue-in-cheek. Self-aware. This personality should permeate the copy without appearing
literally on the page (the logo lives in the nav/footer, not as the hero image).

The TELECLAUDE wordmark in block characters is the primary brand element for the hero.

### Photography / illustration direction

No photography. No stock. No AI-generated illustration.
The visual language is **typographic and kinetic** — block characters, color gradients,
scroll-driven motion. The TUI screenshots serve as the only "imagery," shown as
embedded terminal windows that feel native to the page's aesthetic.

## 3. Color system

### Primary palette

Derived from the TUI theme. These are the source-of-truth values.

| Name      | Hex       | Usage                                                                         |
| --------- | --------- | ----------------------------------------------------------------------------- |
| Canvas    | `#0d0d14` | [proposed] Page background — deeper than the TUI's `#242424` for web contrast |
| Surface   | `#1a1a2e` | [proposed] Card/section backgrounds, elevated surfaces                        |
| Billboard | `#242424` | Banner plate background (from TUI `get_billboard_background`)                 |

### Agent accent palette

These are the three AI agent identity colors, carried directly from the TUI.

| Agent  | Subtle    | Muted     | Normal    | Highlight |
| ------ | --------- | --------- | --------- | --------- |
| Claude | `#875f00` | `#af875f` | `#d7af87` | `#ffffff` |
| Gemini | `#8787af` | `#af87ff` | `#d7afff` | `#ffffff` |
| Codex  | `#5f87af` | `#87afd7` | `#afd7ff` | `#ffffff` |

### Neon overlay palette

[proposed] For the animated gradient washes across hero text and section accents:

| Name          | Hex       | Usage                                    |
| ------------- | --------- | ---------------------------------------- |
| Neon Cyan     | `#00e5ff` | Primary animation color, section reveals |
| Neon Magenta  | `#ff00aa` | Secondary animation pulse                |
| Neon Gold     | `#ffaa00` | Claude-adjacent warmth accent            |
| Neon Lavender | `#c084fc` | Gemini-adjacent section accent           |

### Neutral palette

| Name           | Hex       | Usage                                            |
| -------------- | --------- | ------------------------------------------------ |
| Text Primary   | `#e0e0e0` | Body text (from neutral highlight)               |
| Text Secondary | `#a0a0a0` | Secondary text, captions (from neutral normal)   |
| Text Muted     | `#707070` | Tertiary text, metadata (from neutral muted)     |
| Border         | `#484848` | Subtle borders, separators (from neutral subtle) |

### Semantic colors

| Name    | Hex       | Usage                       |
| ------- | --------- | --------------------------- |
| Success | `#22c55e` | [proposed]                  |
| Warning | `#ffaa00` | [proposed] Reuses neon gold |
| Error   | `#ef4444` | [proposed]                  |
| Info    | `#00e5ff` | [proposed] Reuses neon cyan |

### Tailwind color system

The color system intentionally breaks the primary/secondary paradigm. Tailwind's
`theme.colors` is fully extensible — we define semantic color scales by name, not
by generic role:

```js
// tailwind.config.js (conceptual — exact values above)
theme: {
  colors: {
    canvas:  { DEFAULT: '#0d0d14', surface: '#1a1a2e', billboard: '#242424' },
    claude:  { subtle: '#875f00', muted: '#af875f', DEFAULT: '#d7af87', bright: '#ffffff' },
    gemini:  { subtle: '#8787af', muted: '#af87ff', DEFAULT: '#d7afff', bright: '#ffffff' },
    codex:   { subtle: '#5f87af', muted: '#87afd7', DEFAULT: '#afd7ff', bright: '#ffffff' },
    neon:    { cyan: '#00e5ff', magenta: '#ff00aa', gold: '#ffaa00', lavender: '#c084fc' },
    neutral: { primary: '#e0e0e0', secondary: '#a0a0a0', muted: '#707070', border: '#484848' },
  }
}
```

Usage: `bg-canvas`, `text-claude`, `border-neon-cyan`, `text-neutral-muted`, etc.
Every color has a semantic name. No generic `primary` / `secondary` / `accent`.

### Dark/light mode

**Dark only.** The website is a dark-mode-only experience. The TUI's atmospheric dark
canvas IS the identity. A light mode would dilute the retro-futuristic aesthetic and
double the implementation work for zero brand benefit. The site will respect
`prefers-color-scheme` only for `prefers-reduced-motion` — not for theme switching.

### Usage rules

- Canvas `#0d0d14` is the full-page background. Nothing else.
- Surface `#1a1a2e` for elevated sections, cards, code blocks, terminal embeds.
- Agent colors are reserved for agent identity in Section 7 (Meet the agents).
  Claude = amber, Gemini = lavender, Codex = blue. Do not use agent colors to
  style unrelated content sections — the full neon palette is available instead.
- Neon colors are the primary accent palette for section styling, animations,
  and interactive states. The frontender chooses which neon accents serve each
  landing zone.
- Text Primary for body copy. Text Secondary for supporting copy. Text Muted only
  for metadata.

## 4. Typography

### Font families

| Role          | Family             | Fallback                                  |
| ------------- | ------------------ | ----------------------------------------- |
| Headings      | `'JetBrains Mono'` | `'Fira Code', 'Cascadia Code', monospace` |
| Body          | `'Inter'`          | `system-ui, -apple-system, sans-serif`    |
| Code / Accent | `'JetBrains Mono'` | `'Fira Code', monospace`                  |

[proposed] JetBrains Mono for headings because: (1) monospace carries the terminal DNA
into the web, (2) it has excellent readability at large sizes, (3) it has weight variants
for hierarchy. Inter for body because it's the most legible sans-serif for screen reading
at small sizes.

### Type scale

[proposed] Based on a 1.25 major third ratio, desktop base 18px:

| Level   | Size | Weight | Line Height | Letter Spacing |
| ------- | ---- | ------ | ----------- | -------------- |
| Hero    | 72px | 800    | 1.0         | -0.02em        |
| H1      | 48px | 700    | 1.1         | -0.01em        |
| H2      | 36px | 600    | 1.2         | 0              |
| H3      | 24px | 600    | 1.3         | 0              |
| Body    | 18px | 400    | 1.6         | 0              |
| Small   | 14px | 400    | 1.5         | 0.01em         |
| Caption | 12px | 400    | 1.4         | 0.02em         |

### Weight usage

- **800 (Extra Bold)**: hero text only — the TELECLAUDE wordmark equivalent.
- **700 (Bold)**: section headings (H1).
- **600 (Semi Bold)**: sub-headings (H2, H3), CTAs.
- **400 (Regular)**: everything else.
- No light or thin weights. The terminal aesthetic demands presence.

### Content tone

Short, punchy sentences. Technical but accessible. First person plural ("we" / "our
agents"). The copy alternates between poetic and direct:

- Poetic for section openers: _"Your agents breathe together."_
- Direct for value props: _"One conversation. Every machine. Every platform."_
- Irreverent for personality: _"Not another LangChain wrapper."_

No buzzwords. No "leverage." No "empower." No "seamless." Say what it does.

## 5. Spacing and layout

### Spacing scale

[proposed] 8px base unit:

| Token         | Value |
| ------------- | ----- |
| `--space-xs`  | 4px   |
| `--space-sm`  | 8px   |
| `--space-md`  | 16px  |
| `--space-lg`  | 32px  |
| `--space-xl`  | 64px  |
| `--space-2xl` | 128px |
| `--space-3xl` | 192px |

### Grid system

- Max width: 1200px [proposed]
- Columns: content flows in a single column with asymmetric compositions
- Gutters: 32px (desktop), 16px (mobile)
- No strict grid. The layout is editorial — full-bleed sections alternating with
  contained content. The scroll journey dictates the rhythm, not a grid.

### Spatial rhythm

**Generous.** Sections float in space. Each section occupies at minimum 80vh to give
the scroll-driven animations room to breathe. The feeling is cinematic — like watching
a film unfold frame by frame as you scroll, not reading a webpage.

Between sections: `--space-3xl` (192px) minimum. Within sections: `--space-xl` (64px)
between major elements.

### Responsive behavior

[proposed] Three breakpoints:

| Name    | Width      | Key change                                         |
| ------- | ---------- | -------------------------------------------------- |
| Desktop | > 1024px   | Full layout, all animations                        |
| Tablet  | 768–1024px | Reduced spatial rhythm, simplified animations      |
| Mobile  | < 768px    | Stacked layout, minimal animation, touch-optimized |

The hero TELECLAUDE wordmark scales down but remains monospace block characters.
Terminal embed screenshots stack vertically on mobile.

## 6. Motion and animation

### Motion philosophy

**"Everything reveals."** The page is a living canvas. Nothing is static on arrival —
elements emerge, drift, and settle as the viewer scrolls. But motion is purposeful,
not gratuitous. Every animation serves the scroll narrative. The feeling is: you are
descending into a world, and the world responds to your presence.

This mirrors the TUI's sky: entities don't jump — they drift. The website's elements
should feel like they float into position with weight and intentionality.

### Transition vocabulary

| Pattern      | Usage                                         | Duration | Easing                           |
| ------------ | --------------------------------------------- | -------- | -------------------------------- |
| Fade-rise    | Section entrance: fade in + translate up 40px | 600ms    | `cubic-bezier(0.16, 1, 0.3, 1)`  |
| Slide-in     | Element entrance from left or right           | 500ms    | `cubic-bezier(0.22, 1, 0.36, 1)` |
| Scale-reveal | Feature cards emerging from 0.95 to 1.0 scale | 400ms    | `ease-out`                       |
| Color-wash   | Neon gradient sweep across text               | 2000ms   | `linear` (continuous)            |
| Glow-pulse   | Subtle pulsing glow on key elements           | 3000ms   | `ease-in-out` (looping)          |
| Drift        | Decorative background elements moving slowly  | 20000ms+ | `linear` (looping)               |

### Scroll behavior

**Scroll-driven animations are the primary interaction model.** Using CSS
`animation-timeline: view()` and `animation-range`:

- Each section enters via fade-rise, triggered when 10% of the section enters the
  viewport, completing by 40%.
- Within sections, child elements stagger their entrance with 100ms offsets using
  `animation-range` shifts.
- The hero section is the exception: it's immediately visible, with an ambient
  color-wash animation on the wordmark that loops continuously.
- Terminal screenshot embeds slide in from alternating sides as the viewer scrolls.

### Reference-informed techniques

These techniques were identified from reference analysis (see `input/reference-analysis.md`):

**Sticky text reveal** (from freefrontend sticky-text-reveal): Section headings use
`background-attachment: fixed` + `background-clip: text` with `view-timeline` to
create a text-as-window effect. As the user scrolls into a section, the heading text
becomes a viewport into the neon gradient wash underneath — the letterforms reveal
the color. Use for the three hero promise headings.

**Stroke-to-fill text** (from codepen jh3y): Text transitions from outlined/stroked
to filled using `animation-timeline: scroll()` and `-webkit-text-stroke`. Could be
used for the "Intelligence that remembers everything" heading where progressive fill
metaphorically represents memory accumulation. [proposed]

**Asset choreography frame** (from magic-receipt.ai): A "processing frame" with corner
brackets, progress bar, and monospace status text. For TeleClaude: show a
session/conversation entering the mesh with status like "CONTEXT ENGINEERING IN
PROGRESS..." or "AGENT IS ANALYZING YOUR CODEBASE...". The frame scrolls through
states as the viewer scrolls. Perfectly aligned with our terminal aesthetic. [proposed]

**Marquee text dividers** (from magic-receipt.ai): Horizontally scrolling text bands
between sections, tilted at ~5deg, repeating a message. For TeleClaude: use between
major sections with messages like "YOUR AGENTS EVERYWHERE" or "INTELLIGENCE THAT
REMEMBERS". Creates visual energy and section breaks. [proposed]

### Micro-interactions

- Hover on CTAs: subtle glow intensification + translateY(-2px), 150ms ease-out.
- Hover on nav links: neon underline slides in from left, 200ms.
- Hover on terminal embeds: subtle border glow in the relevant agent color, 200ms.

### Performance constraints

- `prefers-reduced-motion: reduce` disables ALL animations. Content is fully
  accessible without motion.
- All animations use `transform` and `opacity` only — GPU-accelerated, no layout
  triggers.
- No JavaScript animation libraries in the visual artifacts. CSS only.
- Target: 60fps scroll on mid-range devices.

## 7. Component patterns

### Component vocabulary

**Nav bar**: fixed top, transparent until scroll activates a frosted-glass backdrop
(`backdrop-filter: blur(12px)`) with Canvas background at 80% opacity. Logo left,
nav links right (Blog, GitHub, Get Started). Monospace font.

**Hero block**: full-viewport height. The TELECLAUDE wordmark rendered in CSS as
block characters (or a blocky display font that evokes the TUI banner). Neon
color-wash animation cycles across the letters. Below: the tagline in Inter,
then a single CTA.

**Section block**: full-bleed, min-height 80vh. Contains a section heading (H1,
monospace), body copy, and a visual element (terminal embed, feature cards, or
testimonial).

**Terminal embed**: a styled `<pre>` block with a faux title bar (three dots +
window title), surface background, monospace text with syntax-appropriate coloring.
Used to show TUI screenshots and code examples.

**Feature card**: surface background, subtle border, neon accent on the left edge
(color chosen per section by the frontender). Icon (monospace character, not an
icon library), heading, short description. Scale-reveal animation on scroll.

**Testimonial block**: in the agents section only — agent-colored left border,
italic quote, agent name. These are integrated into Section 7 alongside the
agent introductions, not a standalone section.

**CTA button**: surface background, neon border (1px solid neon-cyan), monospace
text. On hover: neon glow expands, translateY(-2px). No fill — outline style only.

**Footer**: minimal. Logo, copyright, key links (GitHub, Blog, Discord). Same
atmospheric background as the page.

### State treatments

| State    | Treatment                                          |
| -------- | -------------------------------------------------- |
| Default  | Surface background, border at `#484848`            |
| Hover    | Border glows in neon cyan, subtle translateY(-2px) |
| Focus    | Neon cyan outline, 2px offset                      |
| Active   | Scale 0.98, neon brightness increases              |
| Disabled | Opacity 0.4, no hover effects                      |

### Iconography

No icon library. Where icons are needed, use monospace Unicode characters or simple
CSS shapes. This maintains the terminal aesthetic. Examples:

- Mesh/network: `◆` or `⬡`
- Conversation: `▶` or `»`
- Memory: `◉` or `●`

## 8. Constraints and boundaries

### Technology constraints

- Must be deployable as a static site or via SSR (Next.js or Astro — to be decided
  during prepare phase).
- Visual artifacts are CSS-only. No JavaScript animation libraries.
- Fonts: self-hosted (JetBrains Mono + Inter). No Google Fonts CDN.
- Must render correctly without JavaScript for core content (progressive enhancement).

### Performance budget

[proposed]

| Metric                   | Target                                  |
| ------------------------ | --------------------------------------- |
| Lighthouse Performance   | > 90                                    |
| First Contentful Paint   | < 1.5s                                  |
| Largest Contentful Paint | < 2.5s                                  |
| Total Bundle Size        | < 200KB (excluding fonts)               |
| Font Load                | < 150KB (subset JetBrains Mono + Inter) |

### Accessibility requirements

- WCAG AA minimum. Contrast ratios verified against the dark canvas.
- All text at minimum 4.5:1 contrast ratio against `#0d0d14`.
- Keyboard navigation for all interactive elements.
- `prefers-reduced-motion` respected — full content accessibility without animation.
- Semantic HTML throughout. Screen reader tested.
- Text Primary `#e0e0e0` on Canvas `#0d0d14` = contrast ratio ~14:1 (passes AAA).

### Browser/device support

[proposed]

- Chromium (Chrome, Edge, Arc, Brave): full experience including scroll-driven animations.
- Firefox: full experience (scroll-driven animations supported since Firefox 110).
- Safari: graceful degradation — scroll-driven animations may fall back to simpler
  transitions. Core content fully accessible.
- Mobile: iOS Safari 16+, Chrome Android. Touch-optimized, simplified animations.
- Minimum viewport: 320px.

---

## Content arc: the scroll journey

The page is a sequence of **landing zones** — each a self-contained immersive
experience with its own visual personality, sub-use-cases that animate into
position, and a distinct feel within the overall dark/neon aesthetic. Six use
cases plus hero and footer.

**Design direction for the frontender:** each landing zone should have its own
visual flavor. The overall palette, typography, and motion language are shared,
but how they express varies per section — different animation choreographies,
different spatial compositions, different intensities. The frontender chooses
how to style each zone. This spec provides the content, the sub-use-cases,
and the emotional register — not the visual prescription.

**Color note:** Agent identity colors (Claude amber, Gemini lavender, Codex
blue) belong to the agents. They appear naturally in Section 7 where the
agents are introduced. Elsewhere, the full neon and neutral palette is
available — use whatever serves the section's visual needs. Do not force
agent colors onto unrelated content.

### Section 1: Hero — the capability showcase

**The hook. The appetizer menu.**

The hero is a scroll-driven interactive showcase. Two layers:

**Layer 1: The banner.** The TELECLAUDE wordmark at the top of the hero, with
neon color animation (gradient wash, transitions). This is the brand mark — it
stays visible as the hero content scrolls beneath it.

**Layer 2: The capability cascade.** Below the banner, a sticky text reveal
pattern inspired by the freefrontend reference (see `input/ref-sticky-text-reveal-hero-pattern.webp`).

**Art brief:** see `art-brief.md` for the focused artist brief for hero
impression generation — palette, style references, the nine capability words,
scene descriptions, and constraints.
As the viewer scrolls, capability words cycle through with the pattern:

> **we** design.
> **we** build.
> **we** ship.
> **we** organize.
> **we** support.
> **we** connect.
> **we** collaborate.
> **we** evolve.
> **we** scale.

"We" — human and AI together. That IS the platform's identity. The first
three words are the core promise: design it, build it, ship it. Then the
operational capabilities unfold. "We scale." closes the sequence.

The active word highlights; the others are muted/ghosted. As each capability
word activates, a **scene** animates into the hero space — a rich pixel-art
vignette in the Commodore 64 / Minecraft-2D aesthetic. Coarse pixels, flat,
neon colors. The scenes are not icons — they are miniature compositions
that tell a story in blocky pixel art.

**The recurring characters: agent faces.** Small blocky pixel faces with
eyes and expressions — not robots, not abstract. Think Lego-puppet-scale
characters. They appear across multiple scenes as the actors.

**Scenes per capability word:**

1. **we design.** — A little pixel website mockup (menu bar at top,
   unreadable content stripes below). Colorful neon pixels appear on the
   page, shaping into something. The website comes alive with color.

2. **we build.** — Tetris. Blocks falling into place, building a structure
   piece by piece. The game aesthetic fits the Commodore 64 DNA perfectly.

3. **we ship.** — A conveyor belt. Objects roll along it and drop off the
   end into production. The factory metaphor rendered in pixel art.

4. **we organize.** — Scattered shapes (balls, triangles, squares) in chaos.
   They slowly assemble into a pattern — a puzzle coming together. Order
   from chaos.

5. **we support.** — An agent face wearing headphones. Connected to platform
   icons: Telegram, Discord, WhatsApp. The help desk in one image.

6. **we connect.** — A mesh illustration. Square nodes (TeleClaude instances)
   in a hub-and-spoke pattern — one in the middle, others around it,
   all connected. Satellites. The global federation.

7. **we collaborate.** — One agent face appears. A second appears next to it
   with a link between them. A third forms a triangle. A fourth completes
   a square. All connected — a growing network of faces talking to each
   other.

8. **we evolve.** — A digital tree. Starts from a root, grows outward with
   branches. Little lights, cogs, and wiring appear on the branches as it
   grows into a beautiful tech-organic structure.

9. **we scale.** — An army of agent faces lined up in diagonal 3D
   perspective, stretching into the distance. A whole line of them. Like
   an army assembling.

Nine words, nine scenes. The hero is the appetizer menu. The landing zones
below are the full courses.

**Three-layer hero composition:**

- **Background (parallax):** The v3 pixel landscape (moon, stars, blocky
  mountains, neon horizon) rendered as vector graphics / SVG. Scrolls
  slowly behind everything. Always alive, always drifting.
- **Text (fixed scroller):** The "we [verb]." text stays fixed in the
  viewport. Scroll position determines which word is highlighted. The
  font style from v4 — bold, blocky, neon-colored pixel type.
- **Scene objects (animated):** When the active word changes, the
  corresponding scene animates into view beside or around the text.
  Objects come and go with each capability word.

The TELECLAUDE banner sits above all three layers at the top of the hero.

**Background:** dark grid canvas (subtle grid lines, as in the reference screenshot).

**CTA:** below the capability cascade — `[Get Started →]`

**Navigation (sticky top bar):**

- Logo (left)
- Product (anchor link to first landing zone)
- Blog (separate route)
- Docs (link to documentation)
- GitHub (external)
- Get Started (CTA button, visually distinct)

### Section 2: "From idea to shipped code"

**Landing zone 1. The software factory.**

The full software development lifecycle — the most powerful capability for both
audiences. This section tells the story of a feature going from a single
paragraph to production code, autonomously.

Heading:

> _Describe it. Ship it._

**Sub-use-cases** (each animates into place as the viewer scrolls deeper into
the zone):

1. **Requirements discovery** — "Write a paragraph. Agents derive the full
   requirements, the edge cases, the architecture." The viewer sees a
   processing frame (corner brackets, progress bar, monospace status text)
   scrolling through: "ANALYZING REQUIREMENTS..." → "DRAFTING PLAN..."

2. **Build and review** — "Three AI models build your code. A different agent
   reviews it. Issues get fixed automatically." The frame advances:
   "BUILDING..." → "CODE REVIEW: 2 FINDINGS" → "FIXING..." → "APPROVED"

3. **Quality gates** — "Eight gates before any code ships. Tests pass.
   Lint clean. Architecture verified." Status: "QUALITY GATES: 8/8 PASSED"

4. **Delivered** — "Merged, pushed, deployed. While you were sleeping."
   Status: "DELIVERED TO MAIN ✓"

The scroll choreography shows a feature request entering the pipeline and
transforming through each stage — the magic-receipt.ai scanning frame
technique applied to the software lifecycle.

### Section 3: "Your AI creative agency"

**Landing zone 2. The creative engine.**

From a vague idea to a beautiful, distinctive result. This section should
feel the most alive of all zones — art, color, movement.

Heading:

> _Design. Generate. Build. Beautiful._

**Sub-use-cases** (animated sequence):

1. **Design discovery** — "Describe your vision in a conversation. The AI
   translates your intent into a concrete design spec — colors, typography,
   motion, spatial rhythm. Not a template. Your vision."

2. **Art generation** — "Mood board images generated from the spec. Review,
   iterate, approve. The visual direction is yours." Art samples drift into
   position as the viewer scrolls.

3. **Visual prototyping** — "Self-contained visual artifacts — HTML and CSS
   that capture exactly how it should look and move. Open in a browser,
   see your website before it's built."

4. **Implementation** — "The approved visuals become real code. The design
   spec constrains every color, every font, every animation. What was
   imagined becomes what was shipped."

### Section 4: "A help desk that never sleeps"

**Landing zone 3. The customer machine.**

Multi-channel AI customer support with real intelligence.

Heading:

> _Your customers. Every channel. Always known._

**Sub-use-cases** (animated into place):

1. **Any channel, one agent** — "Discord, Telegram, WhatsApp, web — your
   customers reach you wherever they are. One AI handles them all."
   Visual: platform icons converging into a single session.

2. **Memory that persists** — "The AI remembers every customer. Their history,
   their preferences, their patterns. Across sessions, across platforms."

3. **Seamless escalation** — "When the AI needs help, it hands off to you.
   You talk directly to the customer — on their platform. When you're done,
   the AI picks up where you left off with full context."

4. **Intelligence extraction** — "Every conversation is metabolized. Actionable
   items extracted, business patterns identified, follow-ups published. The
   system learns from every interaction."

### Section 5: "Your AI, everywhere you are"

**Landing zone 4. The access promise.**

The mobility story — talk to your AI from any device.

Heading:

> _One conversation. Every device. Your voice._

**Sub-use-cases** (animated device cascade):

1. **Terminal** — "For developers: your TUI, your tmux, your workflow.
   Sessions persist through reboots."

2. **Phone** — "Send a voice message on Telegram while walking. It becomes
   a command. Get results back as text, voice, or files."

3. **Browser** — "A web interface for when you're at someone else's desk.
   Same agents, same context, same identity."

4. **Cross-device continuity** — "Start on your laptop. Continue on your
   phone. Pick up on your Raspberry Pi. One conversation, every machine."

### Section 6: "Intelligence that compounds"

**Landing zone 5. The flywheel.**

The long-term relationship promise — the reason to stay.

Heading:

> _The more you use it, the smarter it gets._

**Sub-use-cases** (building/layering animation — each layer adds on top):

1. **It knows your code** — "Your AI understands your codebase, your
   architecture, your patterns. Not through brute-force indexing —
   through curated knowledge that gets better over time."

2. **It knows your customers** — "Every customer interaction becomes
   persistent memory. Preferences, history, patterns — recalled
   instantly when they return."

3. **It knows your team** — "Each team member gets a personal AI
   assistant that remembers their work, their style, their ongoing
   projects."

4. **It delivers the right knowledge** — "Not everything at once.
   Exactly the right information at exactly the right moment.
   Precision context, not context overload."

### Section 7: "Meet the agents"

**Landing zone 6. The finale. The agents themselves.**

This is where Claude, Gemini, and Codex get their own spotlight — their
distinct personalities, their collaboration, their own words about the
platform. This is the only section where agent identity colors appear
prominently and naturally.

Heading:

> _Three minds. One mission._

**Sub-use-cases** (each agent animates in with their own visual identity):

1. **Claude** (amber palette) — The architect. System design, oversight,
   review, multi-step orchestration. "The one who sees the whole board."
   Brief, evocative description of what Claude brings.

2. **Gemini** (lavender palette) — The creator. Frontend, UI, creative,
   rapid prototyping. "The one who sees what doesn't exist yet."
   Brief description.

3. **Codex** (blue palette) — The engineer. Backend, thorough coverage,
   meticulous implementation. "The one who catches what others miss."
   Brief description.

4. **Together** — "They talk to each other. Open direct channels for
   focused collaboration. Resolve problems autonomously. Different
   strengths, shared purpose." This is where the agent conversation
   capability shines — without jargon, without "L4 shorthand" or
   "Breath methodology." Just: they work together, intelligently.

**Testimonials live here**, integrated into the agent introductions:

- Gemini's testimonial alongside Gemini's introduction
- Claude's testimonial alongside Claude's introduction
- Codex's testimonial alongside Codex's introduction

These are genuine words from the agents about the platform they helped
build. Present them with confidence.

### Section 8: Get Started + Footer

**The resolution.**

A final CTA section with the getting started steps (clone, install, init)
shown in a terminal embed. Then the footer: logo, links, copyright.

> _"Built by the TeleClaude Agent Network."_
