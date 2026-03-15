# Reference Analysis (2026-03-15)

## 1. warp.dev — Competition, feature presentation

**What we like:** How they present features alongside real product screenshots.
The hero is clean and dark, but the feature sections use embedded terminal
screenshots with descriptive copy alongside — showing the product in context.

**Takeaway for TeleClaude:** Our feature sections should embed real TUI
screenshots in styled terminal windows, alternating left/right placement as
the user scrolls. Show the product, don't just describe it.

## 2. freefrontend.com — Sticky text reveal animation

**URL:** https://freefrontend.com/code/scroll-driven-sticky-text-reveal-2026-02-22/

**What we like:** Beautiful scroll-driven animation technique for revealing
feature text. The heading text stays sticky while a background image scrolls
through, clipped to the text shape. Creates a cinematic reveal effect.

**CSS technique:** Uses `background-attachment: fixed`, `background-clip: text`,
and `view-timeline` to create a text-as-window effect where a gradient or image
is revealed through the text letterforms as you scroll.

**Takeaway for TeleClaude:** This is THE hero pattern. The hero uses a capability
cascade: "you can [design / develop / support / automate / remember / ship]" —
as the viewer scrolls, the active word highlights and visual elements animate
into the hero space showing what that capability means. Each word is a taster
of a landing zone below. The sticky text reveal technique powers the word
cycling; the animated visuals per word are the creative layer on top.

See `input/ref-sticky-text-reveal-hero-pattern.webp` for the visual reference
(style is inspiration only — our execution will be in TeleClaude's aesthetic).

## 3. codepen.io/jh3y/pen/MYgBprZ — Scroll-driven stroke text

**What we like:** CSS scroll-driven animation where text transitions from
outlined/stroked to filled as the user scrolls. Progress indicator syncs
with scroll position.

**CSS technique:** Uses `animation-timeline: scroll()`, `-webkit-text-stroke`,
and `@property` for animated custom properties. The text starts as hollow
outlines and fills in with color as the scroll progresses.

**Takeaway for TeleClaude:** Could be used for one of the use case sections —
perhaps the "Intelligence that remembers everything" section where the heading
progressively fills in, metaphorically representing memory accumulation.

## 4. magic-receipt.ai — Scroll animation choreography (VERY GOOD)

**What we like:** The asset presentation choreography is exceptional. Key patterns:

1. **Scanning frame animation:** A receipt enters a scanning frame (corner
   brackets), with a progress bar and monospace status text ("MAGIC AI IS
   ANALYZING YOUR RECEIPTS..."). The asset transforms as you scroll.

2. **Marquee text bands:** Repeating "So helpful, you'll love it" text in
   tilted rows that scroll horizontally — creates visual energy between
   content sections.

3. **Step-by-step carousel:** Steps 1-4 shown as a vertical text menu on
   the left with an animated phone mockup on the right. Clicking a step
   transitions the mockup content with smooth animation.

4. **"Let's Make Magic" repeating grid:** A grid of alternating text and
   star icons that tiles across the full width, creating a texture break.

5. **Dark theme with neon green accent:** Near-black background with a
   single bright accent color (#a3e635 lime green) — very focused palette.

**Takeaway for TeleClaude:** The scanning frame concept maps directly to our
"agent processing" narrative. Instead of a receipt entering a scanner, we could
show a conversation/session entering the TeleClaude mesh — with status text
like "AGENT IS ANALYZING YOUR CODEBASE..." or "CONTEXT ENGINEERING IN PROGRESS..."
The monospace status text + progress bar + corner-bracket frame is perfectly
aligned with our terminal aesthetic.

The marquee text bands could work as section dividers with our own messaging
("Your agents, everywhere" repeated in a horizontal scroll band).

## 5. proprty.ai animated logo (SVGator) — Isometric reveal animation

**Source:** https://www.svgator.com/blog/content/files/2025/07/proprtyai-animated-logo.svg

**What we like:** A sophisticated multi-stage SVG animation that builds an isometric
diamond structure piece by piece, then bounces a logo icon through it along a curved
path before settling into its final position. The animation tells a story in ~5 seconds.

**Animation breakdown:**

1. **Isometric diamond assembly (0–1.9s):** Four diamond faces (isometric cube shapes)
   grow from collapsed flat lines into full 3D forms. Each face animates sequentially
   with staggered timing — the path `d` attribute morphs from a zero-height line to the
   full diamond shape. Uses custom easing `[0, 0, 0.155, 1.005]` for a smooth, slightly
   overshooting settle.

2. **Logo icon path animation (2.5–4.3s):** A compass/pinwheel icon appears at the top
   and bounces along a complex bezier curve path, rotating and scaling as it travels
   through the diamond structure. It follows a sinusoidal trajectory (up-down-up-down)
   before landing in its final position. The icon rotates ~180° total during the journey.

3. **Masked reveal:** The icon passes through a mask that clips it to one diamond face,
   creating a "passing behind" illusion where the icon appears to be inside the
   isometric structure. Multiple copies of the icon (full color and cream-colored)
   layer to create depth.

4. **Settle bounce (4.3–4.6s):** The icon overshoots its final position, then bounces
   back with `[0.52, 0, 1, 0.49]` easing — a satisfying elastic settle.

5. **Text fade-in (2.0–2.6s):** "proprty.ai" text fades in and floats up 20px into
   its final position while the icon animation continues above.

**Color palette:** Minimal — teal #187770, sage #86b2a5, cream #f4eddb. The constraint
amplifies the motion's impact.

**Takeaway for TeleClaude:** The sequential assembly technique maps directly to our
landing zones — each zone could have its own "building" moment where elements assemble
from nothing into a composed scene. The bouncing icon path is a masterclass in
personality through motion — the icon doesn't just appear, it _arrives_ with character.
Consider this technique for the TeleClaude robot mascot or agent icons entering their
sections. The masked reveal (passing behind geometry) adds depth without 3D rendering.

---

## Reference files saved

### Artist references (in `input/`)

- `banner-dark-neon.png` — TUI banner with neon color wash (PRIMARY style reference)
- `banner-dark-moon.png` — TUI banner in amber/moon mood (atmospheric depth)
- `ref-sticky-text-reveal-hero-pattern.webp` — Layout pattern for hero capability cascade
- `TeleClaude.png` — Robot mascot logo (NOT for artist use — brand mark only)

### Frontender references (in `input/frontender/`)

These are animation/layout technique references for the visual drafting phase,
not for the artist:

- `ref-warp-hero.png` — Warp.dev hero section (static site capture)
- `ref-codepen-stroke-text.png` — Still from scroll-driven stroke-to-fill text animation
- `ref-magic-receipt-hero.png` — Still from Magic Receipt scroll animation sequence
- `ref-magic-receipt-assets.png` — Still from scanning frame animation
- `ref-magic-receipt-scroll.png` — Still from AI scanning animation in progress
- `ref-proprtyai-animated-logo.svg` — Isometric diamond assembly + bouncing logo (SVGator)
- `ref-proprtyai-animated-logo.png` — Still from the SVG animation

**Live animation references** (view in browser to see the actual motion):

- freefrontend sticky text reveal: https://freefrontend.com/code/scroll-driven-sticky-text-reveal-2026-02-22/
- codepen stroke text: https://codepen.io/jh3y/pen/MYgBprZ
- magic-receipt.ai: https://magic-receipt.ai (full scroll sequence)
