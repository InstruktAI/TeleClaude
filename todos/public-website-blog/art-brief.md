# Art Brief: Hero Impressions

## The ask

Generate **9 images** — one per capability word — showing what the hero of
the TeleClaude website looks like at each scroll moment.

The hero is a scroll-driven capability showcase with three layers:

1. **Background (parallax):** A pixel landscape — moon, stars, blocky
   mountains, neon-lit horizon. Always present, slowly drifting. See v3 below.
2. **Text (fixed scroller):** The "we [verb]." text, fixed in the viewport.
   Bold, blocky pixel font. The active word is highlighted in neon; others
   are muted/ghosted. See v4 below for font style.
3. **Scene objects (animated):** When the active word changes, a pixel-art
   scene animates in beside or around the text. Each scene is a miniature
   composition — not an icon, not a diagram.

The TELECLAUDE banner sits above all three layers at the top.

Each image is a snapshot of one scroll moment: all three layers visible,
the active word highlighted, and that word's scene in place.

## The nine capability words (in order)

1. **we design.**
2. **we build.**
3. **we ship.**
4. **we organize.**
5. **we support.**
6. **we connect.**
7. **we collaborate.**
8. **we evolve.**
9. **we scale.**

"We" = human and AI together. The first three are the core promise.
"We scale." closes the sequence.

## Scene descriptions

Each capability word has a specific pixel-art scene. These are coarse,
flat, blocky — Commodore 64 / Minecraft-2D aesthetic. Not detailed
illustrations. Not smooth. Not 3D-rendered. Pixel blocks.

### Recurring characters: agent faces

Small blocky pixel faces with eyes and expressions. Not robots, not
abstract shapes. Think Lego-puppet scale — just a few pixels for each
feature. They appear across multiple scenes as the actors in the story.

### The nine scenes

1. **we design.** — A little pixel website mockup (menu bar at top,
   content stripes below). Colorful neon pixels appear on the page,
   bringing it alive with color. The website is being designed.

2. **we build.** — Tetris. Blocks falling into place, building a
   structure piece by piece. The game aesthetic fits the Commodore 64
   DNA perfectly.

3. **we ship.** — A conveyor belt. Objects roll along it and drop off
   the end into production. The factory metaphor in pixel art.

4. **we organize.** — Scattered shapes (balls, triangles, squares) in
   chaos. They slowly assemble into a pattern — a puzzle coming
   together. Order from chaos.

5. **we support.** — An agent face wearing headphones. Connected to
   platform icons: Telegram, Discord, WhatsApp. The help desk in
   one image.

6. **we connect.** — A mesh. Square nodes (TeleClaude instances) in a
   hub-and-spoke pattern — one in the middle, others around it, all
   connected. Satellites. The global federation.

7. **we collaborate.** — One agent face appears. A second appears next
   to it with a link between them. A third forms a triangle. A fourth
   completes a square. All connected — a growing network of faces.

8. **we evolve.** — A digital tree. Starts from a root, grows outward
   with branches. Little lights, cogs, and wiring appear on the
   branches. A beautiful tech-organic structure.

9. **we scale.** — An army of agent faces lined up in diagonal 3D
   perspective, stretching into the distance. A whole line of them.
   Like an army assembling.

## Aesthetic

**Commodore 64 / Minecraft-2D mashup.** Coarse pixels, flat colors,
blocky shapes. Not smooth vector art. Not detailed illustration. Not 3D.
The pixel grid is visible — individual squares are distinguishable.

Colors are from the neon palette — cyan, magenta, gold, lavender — on a
near-black canvas. The scenes glow against the dark background.

## Existing art (in art/ folder)

- `website-hero-mockup-v3.jpg` — THE background layer reference. Pixel
  landscape: moon, stars, blocky mountains, neon cyan horizon, lavender
  and magenta pixel clouds. This is the parallax background.
- `website-hero-mockup-v4.jpg` — THE text layer reference. Bold blocky
  pixel fonts ("FUTURE SOFTWARE TODAY", "WE DESIGN WE BUILD WE SHIP")
  with pixel-art terminal/browser windows. This is the font style and
  the concept of objects appearing next to text.

Both v3 and v4 define the visual DNA. New images should feel like they
belong in the same world.

## Emotional register

"I just found something underground and powerful that the mainstream hasn't
discovered yet." Confident, a little irreverent, technically sophisticated
but not intimidating. The feeling of walking into a hacker's workshop at
2 AM where the screens are alive and something extraordinary is being built.

## Color palette

| Name          | Hex       | Role                  |
| ------------- | --------- | --------------------- |
| Canvas        | `#0d0d14` | Page background       |
| Surface       | `#1a1a2e` | Elevated elements     |
| Neon Cyan     | `#00e5ff` | Primary accent        |
| Neon Magenta  | `#ff00aa` | Secondary accent      |
| Neon Gold     | `#ffaa00` | Warm accent           |
| Neon Lavender | `#c084fc` | Soft accent           |
| Text Primary  | `#e0e0e0` | Main text             |
| Text Muted    | `#707070` | Inactive/ghosted text |

## Style references (in input/ folder)

- `banner-dark-neon.png` — THE primary style reference. The TELECLAUDE banner
  with rainbow neon color wash over block characters, living sky with entities,
  dark canvas. This is the visual DNA.
- `banner-dark-moon.png` — Same banner in a different mood. Gold/amber tones,
  moon, stars. Shows the atmospheric depth.
- `ref-sticky-text-reveal-hero-pattern.webp` — Layout pattern reference ONLY
  (not style). Shows the "you can [verb]" cycling text concept on a dark grid.
  Our version uses "we [verb]." in TeleClaude's aesthetic, not this style.

## What this is NOT

- Not generic SaaS marketing
- Not Material Design or Tailwind template aesthetic
- Not cute or playful — confident and irreverent
- Not dark-for-dark's-sake — the darkness is atmospheric
- Not smooth vector art or 3D renders — coarse pixel art only
- Do NOT use the robot mascot logo
- Do NOT reference external websites

## Constraints

- Dark mode only. Canvas `#0d0d14` background.
- The banner is at the top of every image (consistent anchor).
- The active capability word is highlighted; others are muted/ghosted.
- The v3 pixel landscape is visible in the background of every image.
- Agent faces appear in scenes where characters are needed.
- Each image should feel like a distinct moment in a scroll journey,
  not nine versions of the same layout.
