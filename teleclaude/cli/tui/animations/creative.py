"""Creative TUI animations — new and consolidated animation classes."""

from __future__ import annotations

import colorsys
import math
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

from teleclaude.cli.tui.animations.base import Animation, RenderBuffer, Spectrum, Z_BILLBOARD, Z_FOREGROUND, Z_SKY
from teleclaude.cli.tui.animation_colors import hex_to_rgb, rgb_to_hex
from teleclaude.cli.tui.pixel_mapping import (
    BIG_BANNER_HEIGHT,
    BIG_BANNER_LETTERS,
    BIG_BANNER_WIDTH,
    LOGO_HEIGHT,
    LOGO_LETTERS,
    LOGO_WIDTH,
    PixelMap,
)

if TYPE_CHECKING:
    from teleclaude.cli.tui.animation_colors import ColorPalette


# ---------------------------------------------------------------------------
# Shared utility
# ---------------------------------------------------------------------------

_HUE_BANDS = [
    (175, 200, 3),  # Cyan / Teal
    (295, 330, 3),  # Hot Pink / Magenta
    (115, 140, 2),  # Electric Lime
    (18,   38, 2),  # Electric Orange
    (258, 278, 2),  # Electric Purple
    (210, 235, 1),  # White-leaning Blue
]
_HUE_WEIGHTS = [b[2] for b in _HUE_BANDS]


def _pick_hue(rng) -> float:
    """Pick a random neon-safe hue (degrees) from weighted bands."""
    band = rng.choices(_HUE_BANDS, weights=_HUE_WEIGHTS)[0]
    return rng.uniform(band[0], band[1])


def _hue_to_hex(hue_deg: float, sat: float = 1.0, val: float = 1.0) -> str:
    r, g, b = colorsys.hsv_to_rgb(hue_deg / 360.0, sat, val)
    return rgb_to_hex(int(r * 255), int(g * 255), int(b * 255))


def _all_letter_pixels(is_big: bool) -> List[Tuple[int, int]]:
    letters = BIG_BANNER_LETTERS if is_big else LOGO_LETTERS
    result = []
    for i in range(len(letters)):
        result.extend(PixelMap.get_letter_pixels(is_big, i))
    return result


# ---------------------------------------------------------------------------
# NeonFlicker
# ---------------------------------------------------------------------------

class NeonFlicker(Animation):
    """Per-letter independent neon tube buzz — bright, dim, flicker, off."""

    _STATES = ["bright", "dim", "flicker", "off"]
    _TRANSITIONS = {
        "bright":  [5, 1, 1, 0.3],
        "dim":     [3, 2, 1, 0.2],
        "flicker": [2, 1, 3, 0.1],
        "off":     [2, 1, 0.5, 0.1],
    }

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self._initialized = False
        self._states: List[str] = []
        self._timers: List[int] = []
        self._main_color: str = "#00ffff"

    def _lazy_init(self, num_letters: int) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._main_color = _hue_to_hex(_pick_hue(self.rng))
        self._states = [
            self.rng.choices(self._STATES, weights=[5, 1, 0.3, 0])[0]
            for _ in range(num_letters)
        ]
        self._timers = [self.rng.randint(5, 20) for _ in range(num_letters)]

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        letters = BIG_BANNER_LETTERS if self.is_big else LOGO_LETTERS
        num = len(letters)
        self._lazy_init(num)

        result: dict[tuple[int, int], str | int] = {}
        r0, g0, b0 = hex_to_rgb(self._main_color)

        for i in range(num):
            self._timers[i] -= 1
            if self._timers[i] <= 0:
                state = self._states[i]
                self._states[i] = self.rng.choices(self._STATES, weights=self._TRANSITIONS[state])[0]
                new_state = self._states[i]
                if new_state == "flicker":
                    self._timers[i] = self.rng.randint(1, 3)
                elif new_state == "off":
                    self._timers[i] = self.rng.randint(3, 10)
                else:
                    self._timers[i] = self.rng.randint(5, 20)

            state = self._states[i]
            if state == "bright":
                v = 0.9 + self.rng.random() * 0.1
            elif state == "dim":
                v = 0.35 + self.rng.random() * 0.2
            elif state == "flicker":
                v = self.rng.random()
            else:  # off
                v = 0.05 + self.rng.random() * 0.04

            color = rgb_to_hex(int(r0 * v), int(g0 * v), int(b0 * v))
            for p in PixelMap.get_letter_pixels(self.is_big, i):
                result[p] = color

        return result


# ---------------------------------------------------------------------------
# Plasma
# ---------------------------------------------------------------------------

class Plasma(Animation):
    """Demo-scene plasma: overlapping sine waves form a boiling color field."""

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self._params: Optional[dict] = None

    def _lazy_init(self) -> None:
        if self._params is not None:
            return
        self._params = {
            "f1": self.rng.uniform(0.3, 0.7),
            "f2": self.rng.uniform(0.3, 0.7),
            "f3": self.rng.uniform(0.2, 0.5),
            "s1": self.rng.uniform(0.07, 0.14),
            "hue_base": _pick_hue(self.rng) / 360.0,
        }

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        self._lazy_init()
        p = self._params
        t = frame * p["s1"]
        result: dict[tuple[int, int], str | int] = {}

        letters = BIG_BANNER_LETTERS if self.is_big else LOGO_LETTERS
        for i in range(len(letters)):
            for x, y in PixelMap.get_letter_pixels(self.is_big, i):
                v1 = math.sin(x * p["f1"] + t)
                v2 = math.sin(y * p["f2"] + t * 1.3)
                v3 = math.sin((x + y) * p["f3"] + t * 0.7)
                plasma = (v1 + v2 + v3 + 3.0) / 6.0  # 0..1
                hue = (p["hue_base"] + plasma * 0.35) % 1.0
                r, g, b = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
                result[(x, y)] = rgb_to_hex(int(r * 255), int(g * 255), int(b * 255))

        return result


# ---------------------------------------------------------------------------
# Glitch
# ---------------------------------------------------------------------------

class Glitch(Animation):
    """Digital corruption: random channel shifts and wrong-color bursts."""

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self._params: Optional[dict] = None

    def _lazy_init(self) -> None:
        if self._params is not None:
            return
        hue = _pick_hue(self.rng)
        main = _hue_to_hex(hue)
        comp = _hue_to_hex((hue + 180) % 360)
        self._params = {
            "base": main,
            "glitch_colors": ["#ffffff", comp, "#ff0000", "#00ff00"],
        }

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        self._lazy_init()
        p = self._params
        # Burst: 3-frame corruption window every ~12 frames
        burst = (frame % 12) < 3 and self.rng.random() < 0.75

        r0, g0, b0 = hex_to_rgb(p["base"])
        result: dict[tuple[int, int], str | int] = {}

        letters = BIG_BANNER_LETTERS if self.is_big else LOGO_LETTERS
        for i in range(len(letters)):
            for x, y in PixelMap.get_letter_pixels(self.is_big, i):
                if burst and self.rng.random() < 0.25:
                    result[(x, y)] = self.rng.choice(p["glitch_colors"])
                elif burst and self.rng.random() < 0.12:
                    rgb = [r0, g0, b0]
                    ch = self.rng.randint(0, 2)
                    rgb[ch] = max(0, min(255, rgb[ch] + self.rng.randint(-100, 100)))
                    result[(x, y)] = rgb_to_hex(*rgb)
                else:
                    v = 0.80 + self.rng.random() * 0.20
                    result[(x, y)] = rgb_to_hex(int(r0 * v), int(g0 * v), int(b0 * v))

        return result


# ---------------------------------------------------------------------------
# ChromaticAberration
# ---------------------------------------------------------------------------

class ChromaticAberration(Animation):
    """RGB channels offset horizontally — neon edge fringing."""

    supports_small = False

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self._params: Optional[dict] = None
        self._pixel_set: set[tuple[int, int]] = set()

    def _lazy_init(self) -> None:
        if self._params is not None:
            return
        self._params = {
            "offset": self.rng.randint(1, 2),
            "drift": self.rng.uniform(0.015, 0.05),
        }
        pixels = _all_letter_pixels(self.is_big)
        self._pixel_set = set(pixels)

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        self._lazy_init()
        p = self._params
        ps: set[tuple[int, int]] = self._pixel_set or set()

        off = max(1, p["offset"] + round(math.sin(frame * p["drift"]) * 0.5))

        result: dict[tuple[int, int], str | int] = {}

        # Render all letter pixels with channel-shifted colors
        for x, y in ps:
            # R from pixel shifted right (+off), B from pixel shifted left (-off)
            has_r = (x + off, y) in ps
            has_b = (x - off, y) in ps
            r = 220 if has_r else 25
            g = 190  # green center always present
            b = 220 if has_b else 25
            result[(x, y)] = rgb_to_hex(r, g, b)

        # Fringe pixels just outside edges
        for x, y in ps:
            for dx in (-off, off):
                fp = (x + dx, y)
                if fp not in ps:
                    r_src = (fp[0] + off, fp[1]) in ps
                    b_src = (fp[0] - off, fp[1]) in ps
                    r = 160 if r_src else 0
                    g = 0
                    b = 160 if b_src else 0
                    if r or b:
                        result[fp] = rgb_to_hex(r, g, b)

        return result


# ---------------------------------------------------------------------------
# Comet
# ---------------------------------------------------------------------------

class Comet(Animation):
    """Bright comet streak — white core, colored trail, letter flare on contact."""

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self._params: Optional[dict] = None

    def _lazy_init(self) -> None:
        if self._params is not None:
            return
        hue = _pick_hue(self.rng)
        self._params = {
            "color": _hue_to_hex(hue),
            "speed": self.rng.uniform(2.5, 4.5),
            "trail": self.rng.randint(7, 14),
        }

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        self._lazy_init()
        p = self._params
        width = BIG_BANNER_WIDTH if self.is_big else LOGO_WIDTH

        cx = (frame * p["speed"]) % (width + p["trail"] + 6) - p["trail"]
        r0, g0, b0 = hex_to_rgb(p["color"])
        result: dict[tuple[int, int], str | int] = {}

        letters = BIG_BANNER_LETTERS if self.is_big else LOGO_LETTERS
        for i in range(len(letters)):
            for x, y in PixelMap.get_letter_pixels(self.is_big, i):
                dist = x - cx  # negative = in trail
                if -p["trail"] < dist <= 0:
                    fade = 1.0 + dist / p["trail"]  # 1.0 at head, 0 at tail
                    if dist > -2:
                        # Head flare: white blast
                        r = int(r0 + (255 - r0) * fade)
                        g = int(g0 + (255 - g0) * fade)
                        b = int(b0 + (255 - b0) * fade)
                    else:
                        r = int(r0 * fade)
                        g = int(g0 * fade)
                        b = int(b0 * fade)
                    result[(x, y)] = rgb_to_hex(r, g, b)
                else:
                    # Unlit dim base
                    result[(x, y)] = rgb_to_hex(int(r0 * 0.15), int(g0 * 0.15), int(b0 * 0.15))

        return result


# ---------------------------------------------------------------------------
# Fireworks
# ---------------------------------------------------------------------------

class Fireworks(Animation):
    """Expanding color bursts from random letter pixel positions."""

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self._bursts: List[dict] = []
        self._next_burst: int = 0
        self._pixels: Optional[List[Tuple[int, int]]] = None

    def _lazy_init(self) -> None:
        if self._pixels is not None:
            return
        self._pixels = _all_letter_pixels(self.is_big)
        self._next_burst = self.rng.randint(0, 5)

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        self._lazy_init()
        pixels = self._pixels

        # Spawn
        if frame >= self._next_burst and len(self._bursts) < 3 and pixels:
            hue = _pick_hue(self.rng)
            self._bursts.append({
                "center": self.rng.choice(pixels),
                "color": _hue_to_hex(hue),
                "start": frame,
                "max_r": self.rng.uniform(3.5, 6.0),
                "life": self.rng.randint(18, 28),
            })
            self._next_burst = frame + self.rng.randint(10, 22)

        self._bursts = [b for b in self._bursts if frame - b["start"] < b["life"]]

        result: dict[tuple[int, int], str | int] = {p: "#0a0a0a" for p in pixels}

        for burst in self._bursts:
            age = frame - burst["start"]
            progress = age / burst["life"]
            radius = progress * burst["max_r"]
            fade = 1.0 - progress
            bx, by = burst["center"]
            r0, g0, b0 = hex_to_rgb(burst["color"])

            for x, y in pixels:
                dist = math.sqrt((x - bx) ** 2 + (y - by) ** 2)
                ring_dist = abs(dist - radius)
                if ring_dist < 1.2:
                    ring_fade = (1.0 - ring_dist / 1.2) * fade
                    flash = 255 if progress < 0.12 else 0
                    r = min(255, int(r0 * ring_fade) + flash)
                    g = min(255, int(g0 * ring_fade) + flash)
                    b = min(255, int(b0 * ring_fade) + flash)
                    result[(x, y)] = rgb_to_hex(r, g, b)

        return result


# ---------------------------------------------------------------------------
# EQBars
# ---------------------------------------------------------------------------

class EQBars(Animation):
    """Audio equalizer bars — per-letter column pulses driven by fake beat."""

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self._params: Optional[dict] = None

    def _lazy_init(self, num: int) -> None:
        if self._params is not None:
            return
        self._params = {
            "freqs": [self.rng.uniform(0.06, 0.18) for _ in range(num)],
            "phases": [self.rng.uniform(0, math.pi * 2) for _ in range(num)],
            "amps": [self.rng.uniform(0.65, 1.0) for _ in range(num)],
        }

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        letters = BIG_BANNER_LETTERS if self.is_big else LOGO_LETTERS
        num = len(letters)
        self._lazy_init(num)
        p = self._params
        height = BIG_BANNER_HEIGHT if self.is_big else LOGO_HEIGHT

        result: dict[tuple[int, int], str | int] = {}

        for i in range(num):
            # Fake beat: two sine harmonics
            level = (
                math.sin(frame * p["freqs"][i] + p["phases"][i]) * 0.5
                + math.sin(frame * p["freqs"][i] * 2.1 + p["phases"][i] * 0.8) * 0.3
                + 0.2
            ) * p["amps"][i]
            level = max(0.0, min(1.0, level))
            lit = max(1, int(level * height))

            for x, y in PixelMap.get_letter_pixels(self.is_big, i):
                from_bottom = height - 1 - y
                if from_bottom < lit:
                    # Color: green → yellow → red from bottom to top
                    row_frac = from_bottom / max(1, lit - 1) if lit > 1 else 1.0
                    r = min(255, int(510 * min(1.0, row_frac)))
                    g = min(255, int(510 * (1.0 - min(1.0, row_frac))))
                    b = 0
                    if from_bottom == lit - 1:  # top of bar: bright flash
                        r, g, b = 255, 255, 80
                    result[(x, y)] = rgb_to_hex(r, g, b)
                else:
                    result[(x, y)] = "#080808"

        return result


# ---------------------------------------------------------------------------
# LavaLamp
# ---------------------------------------------------------------------------

class LavaLamp(Animation):
    """Slow metaball color blobs drifting through letter pixels."""

    _NUM_BLOBS = 4

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self._blobs: Optional[List[dict]] = None
        self._w = 0
        self._h = 0

    def _lazy_init(self) -> None:
        if self._blobs is not None:
            return
        self._w = BIG_BANNER_WIDTH if self.is_big else LOGO_WIDTH
        self._h = BIG_BANNER_HEIGHT if self.is_big else LOGO_HEIGHT

        self._blobs = []
        for _ in range(self._NUM_BLOBS):
            hue = _pick_hue(self.rng)
            self._blobs.append({
                "color": _hue_to_hex(hue),
                "cx_phase": self.rng.uniform(0, math.pi * 2),
                "cy_phase": self.rng.uniform(0, math.pi * 2),
                "cx_speed": self.rng.uniform(0.018, 0.045),
                "cy_speed": self.rng.uniform(0.025, 0.060),
                "radius": self.rng.uniform(10, 18),
            })

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        self._lazy_init()
        w, h = self._w, self._h

        centers = []
        for blob in self._blobs:
            cx = w / 2 + math.sin(frame * blob["cx_speed"] + blob["cx_phase"]) * (w / 2.2)
            cy = h / 2 + math.sin(frame * blob["cy_speed"] + blob["cy_phase"]) * (h / 1.5)
            centers.append((cx, cy, blob["radius"], blob["color"]))

        result: dict[tuple[int, int], str | int] = {}
        letters = BIG_BANNER_LETTERS if self.is_big else LOGO_LETTERS
        for i in range(len(letters)):
            for x, y in PixelMap.get_letter_pixels(self.is_big, i):
                r_acc = g_acc = b_acc = total = 0.0
                for cx, cy, radius, color in centers:
                    dist = math.sqrt((x - cx) ** 2 + (y - cy) ** 2)
                    if dist < radius:
                        w_val = (1.0 - dist / radius) ** 2
                        r0, g0, b0 = hex_to_rgb(color)
                        r_acc += r0 * w_val
                        g_acc += g0 * w_val
                        b_acc += b0 * w_val
                        total += w_val

                if total > 0:
                    r = min(255, int(r_acc / total))
                    g = min(255, int(g_acc / total))
                    b = min(255, int(b_acc / total))
                    # Boost saturation so blobs always pop
                    h_v, s_v, v_v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
                    r2, g2, b2 = colorsys.hsv_to_rgb(h_v, min(1.0, s_v + 0.3), min(1.0, v_v + 0.2))
                    result[(x, y)] = rgb_to_hex(int(r2 * 255), int(g2 * 255), int(b2 * 255))
                else:
                    result[(x, y)] = "#050512"

        return result


# ---------------------------------------------------------------------------
# Firefly
# ---------------------------------------------------------------------------

class Firefly(Animation):
    """Tiny light points wandering between letter pixel positions."""

    _NUM_FLIES = 10
    _TRAIL = 4

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self._flies: Optional[List[dict]] = None
        self._pixel_list: Optional[List[Tuple[int, int]]] = None
        self._neighbors: Optional[Dict[Tuple[int, int], List[Tuple[int, int]]]] = None

    def _lazy_init(self) -> None:
        if self._flies is not None:
            return
        self._pixel_list = _all_letter_pixels(self.is_big)
        ps = set(self._pixel_list)

        # Build adjacency within Manhattan distance 2
        self._neighbors = {}
        for x, y in self._pixel_list:
            nb = [(x + dx, y + dy) for dx in range(-2, 3) for dy in range(-2, 3)
                  if (dx, dy) != (0, 0) and (x + dx, y + dy) in ps]
            self._neighbors[(x, y)] = nb if nb else self._pixel_list[:5]

        self._flies = []
        for _ in range(self._NUM_FLIES):
            pos = self.rng.choice(self._pixel_list)
            hue = _pick_hue(self.rng)
            self._flies.append({
                "pos": pos,
                "trail": [],
                "color": _hue_to_hex(hue),
                "speed": self.rng.randint(1, 3),
                "countdown": self.rng.randint(1, 3),
            })

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        self._lazy_init()
        result: dict[tuple[int, int], str | int] = {p: "#010106" for p in self._pixel_list}

        for fly in self._flies:
            fly["countdown"] -= 1
            if fly["countdown"] <= 0:
                fly["trail"].append(fly["pos"])
                if len(fly["trail"]) > self._TRAIL:
                    fly["trail"].pop(0)
                nbs = self._neighbors.get(fly["pos"], [])
                if nbs:
                    fly["pos"] = self.rng.choice(nbs)
                fly["countdown"] = fly["speed"]

            r0, g0, b0 = hex_to_rgb(fly["color"])
            for i, tp in enumerate(fly["trail"]):
                fade = (i + 1) / (self._TRAIL + 1) * 0.5
                result[tp] = rgb_to_hex(int(r0 * fade), int(g0 * fade), int(b0 * fade))
            result[fly["pos"]] = fly["color"]

        return result


# ---------------------------------------------------------------------------
# ColorSweep — consolidated directional sweep with hue randomization
# ---------------------------------------------------------------------------

class ColorSweep(Animation):
    """Unified sweep: random direction, random neon hue, adjacent color stops."""

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self._params: Optional[dict] = None

    def _lazy_init(self) -> None:
        if self._params is not None:
            return
        hue = _pick_hue(self.rng)
        main = _hue_to_hex(hue)
        sec = _hue_to_hex((hue + 20) % 360)
        directions = ["lr", "rl", "tb", "bt", "diag_dr", "diag_dl", "radial"]
        self._params = {
            "direction": self.rng.choice(directions),
            "spec": Spectrum([main, "#ffffff", sec]),
            "speed": self.rng.uniform(0.8, 1.6),
        }

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        self._lazy_init()
        p = self._params
        width = BIG_BANNER_WIDTH if self.is_big else LOGO_WIDTH
        height = BIG_BANNER_HEIGHT if self.is_big else LOGO_HEIGHT
        mod = self.get_modulation(frame)
        speed = p["speed"] * mod
        spec = p["spec"]
        direction = p["direction"]

        if direction == "lr":
            active = (frame * speed) % (width + 10) - 5
            def pos(x, y): return x, x / width
        elif direction == "rl":
            active = (width - 1) - ((frame * speed) % (width + 10) - 5)
            def pos(x, y): return x, (width - x) / width
        elif direction == "tb":
            active = (frame * speed * 0.5) % (height + 4) - 2
            def pos(x, y): return y, y / max(1, height - 1)
        elif direction == "bt":
            active = (height - 1) - ((frame * speed * 0.5) % (height + 4) - 2)
            def pos(x, y): return y, (height - 1 - y) / max(1, height - 1)
        elif direction == "diag_dr":
            max_v = width + height
            active = (frame * speed) % (max_v + 10) - 5
            def pos(x, y): return x + y, (x + y) / max_v
        elif direction == "diag_dl":
            max_v = width + height
            active = (width - 1) - ((frame * speed) % (max_v + 10) - 5)
            def pos(x, y): return x - y, (x + y) / max_v
        else:  # radial
            cx, cy = width / 2, height / 2
            max_r = math.sqrt(cx ** 2 + cy ** 2)
            active = (frame * speed * 0.35) % (max_r + 5)
            def pos(x, y):
                return math.sqrt((x - cx) ** 2 + (y - cy) ** 2), \
                       math.sqrt((x - cx) ** 2 + (y - cy) ** 2) / max_r

        result: dict[tuple[int, int], str | int] = {}
        letters = BIG_BANNER_LETTERS if self.is_big else LOGO_LETTERS
        for i in range(len(letters)):
            for x, y in PixelMap.get_letter_pixels(self.is_big, i):
                pos_val, color_frac = pos(x, y)
                surge = self.linear_surge(pos_val, active, 4.0)
                color = self.enforce_vibrancy(spec.get_color(color_frac))
                intensity = 0.45 + surge * 0.55
                r0, g0, b0 = hex_to_rgb(color)
                result[(x, y)] = rgb_to_hex(int(r0 * intensity), int(g0 * intensity), int(b0 * intensity))

        return result


# ---------------------------------------------------------------------------
# LaserScan — the "hitman" beam
# ---------------------------------------------------------------------------

class LaserScan(Animation):
    """Fast precision laser: white-hot core, colored outer glow. High contrast."""

    _LASER_HUE_BANDS = [(0, 15, 3), (355, 360, 3), (295, 330, 2)]

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self._glow: Optional[str] = None

    def _lazy_init(self) -> None:
        if self._glow is not None:
            return
        weights = [b[2] for b in self._LASER_HUE_BANDS]
        band = self.rng.choices(self._LASER_HUE_BANDS, weights=weights)[0]
        hue = self.rng.uniform(band[0], band[1])
        self._glow = _hue_to_hex(hue)

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        self._lazy_init()
        width = BIG_BANNER_WIDTH if self.is_big else LOGO_WIDTH
        active_x = (frame * 2.8) % (width + 8) - 4
        r0, g0, b0 = hex_to_rgb(self._glow)

        result: dict[tuple[int, int], str | int] = {}
        letters = BIG_BANNER_LETTERS if self.is_big else LOGO_LETTERS
        for i in range(len(letters)):
            for x, y in PixelMap.get_letter_pixels(self.is_big, i):
                dist = abs(x - active_x)
                if dist < 0.5:
                    result[(x, y)] = "#ffffff"
                elif dist < 1.5:
                    blend = 1.0 - (dist - 0.5)
                    result[(x, y)] = rgb_to_hex(
                        int(255 * blend + r0 * (1 - blend)),
                        int(255 * blend + g0 * (1 - blend)),
                        int(255 * blend + b0 * (1 - blend)),
                    )
                elif dist < 4.5:
                    fade = 1.0 - (dist - 1.5) / 3.0
                    result[(x, y)] = rgb_to_hex(int(r0 * fade), int(g0 * fade), int(b0 * fade))
                else:
                    result[(x, y)] = rgb_to_hex(int(r0 * 0.12), int(g0 * 0.12), int(b0 * 0.12))

        return result
