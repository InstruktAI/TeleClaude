# Geometry construction techniques by asset class

Read the section matching the asset class. Code patterns are sketches of the
structure, not complete programs — keep the structure, expand the detail.

## Contents

1. Organic bodies (lofted spline surfaces)
2. Terrain (heightfields)
3. Hard-surface (profiles, bevels, greebles)
4. Vegetation (branching + instancing)
5. Fluid & cloth (wave displacement)
6. Scatter & crowds (instancing with variation)

---

## 1. Organic bodies

The universal pattern for anything with a body: **define a spine, sweep
cross-sections along it, build a custom BufferGeometry.**

- Spine: a `CatmullRomCurve3` through hand-placed control points capturing
  the dorsal profile (a whale's spine dips at the blowhole, rises at the
  peduncle; get these landmarks from anatomy, not symmetry).
- Width and height profiles: separate 1D functions of t (0→1 along the
  spine) so the cross-section is elliptical and independently shaped —
  bodies are never circular in section. Encode landmarks as piecewise
  curves or `CatmullRomCurve3` in 2D.
- Cross-section shape can itself vary with t (blend a rounded-triangle
  section near a belly, flatten near a tail).

```js
function buildLoftedBody(spine, widthProfile, heightProfile, segs = 160, radial = 64) {
  const positions = [],
    indices = [];
  const frames = spine.computeFrenetFrames(segs, false); // stable orientation
  for (let i = 0; i <= segs; i++) {
    const t = i / segs;
    const center = spine.getPointAt(t);
    const w = widthProfile(t),
      h = heightProfile(t);
    for (let j = 0; j <= radial; j++) {
      const a = (j / radial) * Math.PI * 2;
      // ellipse in the normal/binormal plane of the spine frame
      const offset = frames.normal[i]
        .clone()
        .multiplyScalar(Math.cos(a) * h)
        .add(frames.binormal[i].clone().multiplyScalar(Math.sin(a) * w));
      positions.push(...center.clone().add(offset).toArray());
    }
  }
  // standard grid index buildup, then:
  // geometry.computeVertexNormals()
}
```

- Cap the ends by converging the profile functions to ~0 (with a small
  epsilon to avoid degenerate normals) — never plug holes with spheres.
- **Fins, flukes, limbs**: separate lofts with airfoil-like cross-sections
  (thick leading edge, thin trailing edge — a flattened teardrop), swept
  along their own short spline, root sunk slightly _into_ the body so the
  junction reads as continuous. Never flat planes or scaled boxes.
- **Skin detail**: after building positions, displace along normals with
  2–3 octaves of simplex noise at ~0.5–2% of body radius. Import a noise
  implementation or inline a compact simplex function.
- **Eyes, mouth line, blowhole**: small dedicated geometry or dark
  MeshPhysicalMaterial insets; these landmarks anchor realism cheaply.
- **Swimming/walking**: per-frame, add a traveling sine offset to the spine
  control points (amplitude growing toward the tail for swimmers), rebuild
  or shader-deform. The whole body must flex; a rigid body with a flapping
  tail is a classic toy tell.

## 2. Terrain

- Heightfield on a `PlaneGeometry` with high resolution (512×512 segments
  is fine).
- **Fractal noise**: sum 5–6 octaves of simplex, each octave ~2× frequency
  and ~0.5× amplitude (`lacunarity 2.0, gain 0.5`).
- **Domain warping** is what separates good terrain from obvious noise:
  perturb the sample position with another noise field before sampling
  (`h = fbm(p + k * vec2(fbm(p), fbm(p + 31.4)))`).
- **Erosion cues** cheaply: ridge noise (`1 - abs(noise)`) for mountain
  crests; raise valleys to a floor for alluvial flats.
- **Material by slope and altitude**: compute per-vertex color (or a shader
  mix) — grass on flat low, rock on steep, snow above a noisy altitude
  threshold. A uniform-color terrain always looks fake.
- Finish with fog and distance haze (see rendering reference) — aerial
  perspective is half of what makes terrain read as large.

## 3. Hard-surface

- Build from **2D profiles**: draw the side/top profile as a `THREE.Shape`
  (with `bezierCurveTo` for curved bodywork), then `ExtrudeGeometry` with
  bevel enabled. `LatheGeometry` for anything rotationally symmetric
  (nozzles, domes, wheels).
- **Bevels are mandatory.** Raw 90° edges are the #1 tell of generated 3D —
  real objects always catch light on an edge radius. `bevelEnabled: true,
bevelThickness/bevelSize` at ~1–2% of part size, 3+ bevel segments.
- **Panel lines and cuts**: thin dark inset strips or floating slightly
  raised/sunk geometry along the surface; suggest doors, hatches, joints.
- **Greebles** for spaceships/machinery: scatter small beveled detail
  meshes (via InstancedMesh) over hull zones — variation in scale and
  rotation, clustered rather than uniform.
- **Materials sell hard-surface**: metalness near 1 with low-mid roughness
  for metal, clearcoat for car paint, distinct rougher material for trim,
  emissive strips for tech. One material over a whole vehicle looks like a
  toy from a mold.
- Wheels/joints as separate parts with their own rotation axes.

## 4. Vegetation

- **Trunk & branches**: recursive skeleton (L-system-like). Each branch: a
  spline from base to tip, radius tapering by a power law
  (`r_child ≈ r_parent * 0.6–0.75`), children placed along the parent with
  golden-angle azimuth spacing and upward bias. Build each branch as a
  tapered tube (`TubeGeometry` along the spline or a mini-loft). 3–4
  recursion levels.
- **Leaves/needles**: never model individually as scene children —
  `InstancedMesh` with thousands of instances of a simple leaf shape
  (a bent quad or cross-quad), positioned at branch tips, randomized in
  scale/orientation/hue. Double-sided material.
- **Grass**: InstancedMesh of curved blade quads (bend via a slight arc in
  the geometry), tens of thousands of instances, per-instance random lean
  and height, hue variation via `setColorAt`. Wind = time-phased lean in a
  vertex shader keyed on instance position.
- **Coral/alien flora**: same skeleton recursion with different taper and
  angle parameters; noise-displace the surfaces.

## 5. Fluid & cloth

- High-resolution plane, displaced in a **vertex shader** (CPU displacement
  only for small meshes).
- **Water**: sum 4+ Gerstner waves (crest sharpening, not plain sine) with
  varied direction, wavelength and amplitude, plus a high-frequency simplex
  layer for chop. Compute normals analytically in the shader from the wave
  derivatives — do not leave the normals flat, they carry all the specular
  life. Material: low roughness, high transmission or dark blue-green with
  strong env reflection; add fresnel-driven color shift.
- **Cloth/flags**: layered traveling sines along the free edge, amplitude
  scaled by distance from the fixed edge, plus low-frequency flutter noise.
- Foam/spray: emissive-ish white via crest height threshold in the shader,
  or a light particle system — small touches, big realism return.

## 6. Scatter & crowds

- One `InstancedMesh` per object type; per-instance matrix (position,
  rotation, non-uniform scale) and `setColorAt` hue variation.
- **Distribution is the realism lever**: cluster with noise (sample a
  density field, reject uniformly-random placement), align to terrain
  normals, sink bases slightly into the ground.
- Vary within a type: 2–3 geometry variants of a rock/tree re-used across
  instances beats one variant at 3× the count.
- For distant scatter, swap to cheaper variants or impostor quads —
  density at the horizon matters more than per-instance fidelity.
