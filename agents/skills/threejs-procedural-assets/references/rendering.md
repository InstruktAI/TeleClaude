# The rendering stack

Include this stack in every scene. It is invariant: only colors, positions
and intensities adapt to the subject. Geometry under a default lighting
setup always looks like a toy, no matter how good the mesh is.

## Boilerplate (single-file HTML)

```html
<script type="importmap">
  {
    "imports": {
      "three": "https://cdn.jsdelivr.net/npm/three@0.165.0/build/three.module.js",
      "three/addons/": "https://cdn.jsdelivr.net/npm/three@0.165.0/examples/jsm/"
    }
  }
</script>
```

```js
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.1; // tune 0.8–1.4 per scene
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
```

## Environment map (procedural — no external files)

An environment map is what makes PBR materials respond to the world.
Generate one from a small gradient scene:

```js
const pmrem = new THREE.PMREMGenerator(renderer);
const envScene = new THREE.Scene();
// large inverted sphere with a vertical gradient shader (or several
// colored planes acting as soft light panels for studio looks)
envScene.add(gradientSphere); // e.g. deep blue below → cyan above for underwater
scene.environment = pmrem.fromScene(envScene, 0.04).texture;
```

Match the gradient to the setting: underwater (deep blue → light cyan),
sky (horizon warm → zenith blue), studio (dark + bright panels). Also use
it (or a matching background/fog color) as `scene.background`.

## Lights

Three-point structure, always:

- **Key**: `DirectionalLight`, warmish, intensity ~2–3, casts shadows.
  Shadow camera sized tightly to the subject; `shadow.mapSize` 2048;
  small `shadow.radius`/bias tuning to avoid acne.
- **Rim/back**: second directional or spot from behind-above, tinted
  toward the environment color (blue underwater, warm at sunset),
  intensity ~1–2, no shadows. The rim highlight separates the subject
  from the background — this single light is the biggest cheap win.
- **Fill**: the environment map usually suffices; otherwise a low-intensity
  `HemisphereLight` tinted sky/ground. Never use flat `AmbientLight` at
  meaningful intensity — it kills form.

## Atmosphere

- `scene.fog = new THREE.FogExp2(color, density)` with color matched to
  the background. Fog gives depth ordering and scale; scenes without it
  read as objects floating in a void.
- Optional: sparse floating particles (dust/plankton/snow) — tiny additive
  points drifting slowly. Disproportionate realism return for ~30 lines.

## Materials

`MeshPhysicalMaterial` everywhere, tuned per surface — never one shared
default:

| Surface                | Settings                                                                |
| ---------------------- | ----------------------------------------------------------------------- |
| Skin (wet, e.g. whale) | roughness 0.35–0.5, clearcoat 0.4, clearcoatRoughness 0.3, slight sheen |
| Skin (matte/dry)       | roughness 0.6–0.8, sheen 0.3 with tinted sheenColor                     |
| Metal                  | metalness 1.0, roughness 0.2–0.5, needs env map to read as metal        |
| Car paint              | metalness 0.7, roughness 0.35, clearcoat 1.0, clearcoatRoughness 0.05   |
| Glass/water            | transmission 1.0, thickness, ior 1.33–1.5, roughness < 0.1              |
| Foliage                | roughness 0.7, DoubleSide, hue variation per instance                   |

Color detail belongs in the material too: countershading (dark dorsal →
light ventral, via vertex colors or a shader mix on the normal/height),
subtle hue noise, darker crevice tones. A single flat `color:` value is a
toy tell.

## Camera & composition

- Slight low angle looking up at creatures/vehicles reads heroic; pure
  side/front orthographic-feeling views read like a diagram.
- `OrbitControls` with damping for demos; gentle autonomous camera drift
  if uncontrolled.
- Frame with foreground/background elements (seafloor, distant terrain,
  particles) — a subject alone in a void undoes the rest of the stack.

## Post & verification

- If quality is paramount, add `EffectComposer` with `UnrealBloomPass` at
  low strength (~0.3) for highlights, and consider a vignette. Optional —
  the stack above does most of the work.
- If a headless browser (Playwright/Chromium) is available: screenshot the
  running scene, actually look at it, fix the worst thing, repeat once or
  twice. Blind output is a first draft.
