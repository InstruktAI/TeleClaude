---
name: threejs-procedural-assets
description: Generate high-end, realistic-looking procedural 3D assets and scenes in Three.js without external model files. Use this skill whenever the user asks for any 3D object, creature, vehicle, terrain, plant, water, building, game scene, or visualization in Three.js / WebGL / react-three-fiber — even if they don't say "realistic" or "high quality", and even for seemingly simple requests like "make a whale" or "add a tree". It prevents the default low-quality output (primitive-assembly geometry, flat lighting) by mandating proper geometry construction and a physically based rendering stack.
---

# Three.js Procedural Assets

## Why this skill exists

When asked for a 3D asset, the lowest-effort path is to glue together spheres,
cylinders and boxes, apply a default `MeshStandardMaterial`, add one directional
light, and stop. The result always looks like a toy. That path is banned here.

Perceived realism comes from exactly three things, and this skill addresses each:

1. **Correct silhouette** — the outline must be built from continuous curved
   surfaces (splines, lofts, fields), never from intersecting primitives.
2. **A frequency hierarchy of detail** — large forms, then mid-frequency
   features, then fine surface noise. Real objects have all three bands;
   toy renders have only the first.
3. **Physically plausible light response** — tone mapping, an environment
   map, tuned PBR materials, soft shadows. The same mesh looks 5× better
   under a proper rendering stack, so the stack is non-negotiable even for
   "quick" demos.

## Workflow

1. Classify the asset (table below) and read the matching section of
   `references/geometry.md` for the construction technique and code pattern.
2. Read `references/rendering.md` and include its rendering stack verbatim,
   adapting only colors/positions to the scene.
3. Build the geometry following the detail cascade (below).
4. Animate by deforming geometry, not by rigidly transforming whole meshes.
5. Self-check against the checklist at the end before declaring done.

## Asset classification

| Asset class    | Examples                        | Construction technique                                    | Banned shortcut                       |
| -------------- | ------------------------------- | --------------------------------------------------------- | ------------------------------------- |
| Organic body   | whale, fish, human, dragon      | Lofted spline surface: spine curve + swept cross-sections | Sphere/cylinder assembly              |
| Terrain        | mountains, dunes, islands       | Multi-octave simplex heightfield + domain warping         | Single-octave noise, uniform color    |
| Hard-surface   | car, spaceship, robot, building | Extruded/beveled 2D profiles, panel cuts, greebles        | Plain boxes, unbeveled 90° edges      |
| Vegetation     | trees, grass, coral             | Recursive branching skeleton + InstancedMesh foliage      | Cone-on-cylinder "tree"               |
| Fluid/cloth    | ocean, flags, curtains          | Plane + layered wave displacement in vertex shader        | Static plane with blue/white material |
| Scatter/crowds | rocks, forests, cities          | InstancedMesh with per-instance variation                 | Cloned meshes in a loop               |

Composite assets (a game scene, a diorama) decompose into these classes;
apply the right technique to each part. If an asset fits no row, derive the
technique from the principle: _find the mathematical structure that generates
the shape, and implement that_ — models are far better at implementing a
named algorithm than at freehand-sculpting with primitives.

## The detail cascade (apply to every asset)

Work top-down through three frequency bands:

- **Silhouette (low frequency).** Profile curves (`CatmullRomCurve3`,
  hand-tuned control points) drive the large form. Use generous tessellation:
  100+ segments along the main axis, 48–64 radial/cross segments. Polygon
  count is not the bottleneck in Three.js — a 100k-triangle asset renders
  fine; an under-tessellated one never looks good.
- **Mid frequency.** The features that make the object _that_ object: fin
  ridges, nostrils, panel lines, wheel arches, branch collars, dune crests.
  Model these into the geometry (profile modulation, extra lofted parts,
  boolean-style cuts) — do not skip to noise.
- **High frequency.** Low-amplitude simplex-noise vertex displacement for
  skin/surface detail, or procedural bump via `material.bumpMap` from a
  canvas texture. Amplitude should be barely visible — its job is to break
  up perfect smoothness, which is itself a "CG toy" tell.

Always finish geometry with smooth vertex normals (`computeVertexNormals()`
after displacement, or analytic normals in a shader).

## Motion

Animate by deformation: bend the spine spline over time for a swimming or
walking creature, run wind sway through branch hierarchies, advance wave
phases in the vertex shader. Rigid rotation/translation of whole meshes is
only for things that genuinely move rigidly (wheels, doors, camera). A
per-frame geometry rebuild of a lofted body is affordable up to ~50k
vertices; beyond that, do the deformation in a vertex shader.

## Effort calibration

Treat every asset as a showcase piece. A proper single-asset scene lands
around 500–900 lines; a multi-asset scene more. Never simplify geometry to
primitives to save effort, never drop the rendering stack, never reduce
segment counts to "keep it simple". If output length is constrained, cut
scope (fewer assets), not quality.

## Language/format

Default to a single self-contained HTML file with an ES-module script and
an import map for `three` (see `references/rendering.md`). If the user's
project is TypeScript or react-three-fiber, write idiomatic TS/r3f instead —
the geometry and rendering rules are identical.

## Self-check before delivering

- Silhouette built from curves/fields, zero visible primitive intersections?
- All three detail bands present?
- Beveled edges on all hard-surface parts (no raw 90° edges catching light)?
- Rendering stack complete: ACES tone mapping, environment map via
  PMREMGenerator, key + rim light, soft shadows, fog/atmosphere, tuned
  `MeshPhysicalMaterial` per surface?
- Motion via deformation where applicable?
- If a headless browser is available: render, screenshot, look at it, and
  fix what looks wrong — one iteration on visual feedback is worth more
  than any amount of blind polish.
