"""
Procedural renderer for SYNTHETIC insurance-claim images.

=============================================================================
SYNTHETIC DEVELOPMENT / EVALUATION DATA — NOT REAL CLAIMS, NOT REAL PHOTOGRAPHS
=============================================================================

Draws recognisable cars, laptops and packages with damage applied to a named part, so that
ground truth is known by construction rather than by annotation.

Honest limitation, stated up front: these are **rendered illustrations, not photographs**.
A vision model will recognise the object and locate the damage, but performance on this set
is not a prediction of performance on real claim photos — lighting, occlusion, motion blur,
reflections and the sheer variety of real damage are all absent. This set exists to exercise
and regression-test the pipeline end to end, not to certify accuracy.

Design rule: **no text labels anywhere in the image.** Labelling the damaged part would turn
the benchmark into an OCR test and leak ground truth to the model.
"""
from __future__ import annotations

import math
import random
from typing import Dict, Tuple

from PIL import Image, ImageDraw, ImageFilter

RGB = Tuple[int, int, int]

# Palette chosen so parts are separable without labels.
BODY_COLOURS: list[RGB] = [(158, 162, 168), (72, 84, 104), (140, 46, 44), (44, 74, 56), (222, 224, 228)]
GROUND: RGB = (188, 186, 182)
SKY: RGB = (208, 220, 232)


# ─── Damage primitives ──────────────────────────────────────────────────────

# Ink colour is chosen per-part against the surface underneath, because damage drawn in
# dark grey on a black laptop screen is invisible -- which would mean an image labelled
# "cracked screen" showing no crack, and a benchmark measuring the wrong thing.
_INK = {"dark": (26, 28, 34), "light": (242, 243, 245)}


def _contrast_ink(img: Image.Image, box) -> tuple[RGB, RGB]:
    """Return (primary, secondary) ink that will actually be visible on this surface."""
    x0, y0, x1, y1 = (int(v) for v in box)
    region = img.convert("L").crop((max(0, x0), max(0, y0), max(1, x1), max(1, y1)))
    mean = sum(region.getdata()) / max(1, len(region.getdata()))
    if mean < 110:                       # dark surface -> light damage
        return _INK["light"], (176, 178, 184)
    return _INK["dark"], (238, 238, 240)  # light surface -> dark damage


def _scratch(d: ImageDraw.ImageDraw, box, rng, severity: str, ink=None) -> None:
    """Thin abrasion lines with a highlight edge."""
    primary, secondary = ink or (_INK["dark"], (238, 238, 240))
    x0, y0, x1, y1 = box
    n = {"low": 3, "medium": 6}.get(severity, 3)
    length = (x1 - x0) * (0.45 if severity == "low" else 0.8)
    for _ in range(n):
        sx = rng.uniform(x0 + 5, x1 - length - 5) if x1 - length - 5 > x0 + 5 else x0 + 5
        sy = rng.uniform(y0 + 5, y1 - 5)
        pts, x, y = [], sx, sy
        for _ in range(9):
            x += length / 9
            y += rng.uniform(-3, 3)
            pts.append((x, y))
        d.line(pts, fill=secondary, width=3 if severity == "low" else 5)
        d.line([(px, py + 1.5) for px, py in pts], fill=primary, width=2)


def _dent(d: ImageDraw.ImageDraw, box, rng, severity: str, ink=None) -> None:
    """
    An irregular crumpled depression with crease lines and paint damage.

    Deliberately NOT a smooth ellipse. The first version drew concentric ellipses, which on
    a car bumper read as a fog lamp or badge rather than damage — three honest `match` cases
    came back as "no damage visible" because of it.
    """
    primary, secondary = ink or (_INK["dark"], (238, 238, 240))
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    r = min(x1 - x0, y1 - y0) * (0.34 if severity == "low" else 0.58)

    # Irregular outline: a jagged blob, not a geometric shape.
    def blob(scale: float):
        pts = []
        for i in range(11):
            a = 2 * math.pi * i / 11
            rr = r * scale * rng.uniform(0.62, 1.0)
            pts.append((cx + math.cos(a) * rr, cy + math.sin(a) * rr * 0.74))
        return pts

    for i, scale in enumerate((1.0, 0.72, 0.46)):
        shade = 132 - i * 34
        d.polygon(blob(scale), fill=(shade, shade, shade + 5))

    # Crease lines radiating from the impact point — the visual signature of a dent.
    for _ in range(3 if severity == "low" else 6):
        a = rng.uniform(0, 2 * math.pi)
        d.line(
            [(cx, cy), (cx + math.cos(a) * r * 0.95, cy + math.sin(a) * r * 0.7)],
            fill=primary, width=2,
        )
    # Exposed paint edge along the lower rim.
    d.arc([cx - r, cy - r * 0.74, cx + r, cy + r * 0.74], 200, 340, fill=secondary,
          width=3 if severity == "low" else 5)
    d.arc([cx - r, cy - r * 0.74 + 3, cx + r, cy + r * 0.74 + 3], 200, 340, fill=primary, width=2)


def _crack(d: ImageDraw.ImageDraw, box, rng, severity: str, ink=None) -> None:
    """Branching fracture, for glass and screens."""
    primary, secondary = ink or (_INK["dark"], (238, 238, 240))
    x0, y0, x1, y1 = box
    cx = rng.uniform(x0 + (x1 - x0) * 0.3, x1 - (x1 - x0) * 0.3)
    cy = rng.uniform(y0 + (y1 - y0) * 0.3, y1 - (y1 - y0) * 0.3)
    branches = 5 if severity == "low" else 10
    span = min(x1 - x0, y1 - y0) * (0.32 if severity == "low" else 0.62)
    for i in range(branches):
        ang = (2 * math.pi * i / branches) + rng.uniform(-0.3, 0.3)
        pts, x, y = [(cx, cy)], cx, cy
        for _ in range(5):
            x += math.cos(ang) * span / 5 + rng.uniform(-4, 4)
            y += math.sin(ang) * span / 5 + rng.uniform(-4, 4)
            pts.append((x, y))
        d.line(pts, fill=primary, width=3)
        d.line([(px + 1, py + 1) for px, py in pts], fill=secondary, width=1)
    d.ellipse([cx - 9, cy - 9, cx + 9, cy + 9], fill=primary)


def _shatter(d, box, rng, severity, ink=None):
    _crack(d, box, rng, "medium", ink)
    _crack(d, box, rng, "medium", ink)


def _crush(d: ImageDraw.ImageDraw, box, rng, severity: str, ink=None) -> None:
    """Buckled/compressed region, for packaging."""
    primary, _ = ink or (_INK["dark"], None)
    x0, y0, x1, y1 = box
    steps = 7 if severity == "low" else 14
    amp = (x1 - x0) * (0.08 if severity == "low" else 0.18)
    for i in range(steps):
        t = i / steps
        yy = y0 + (y1 - y0) * t
        off = math.sin(t * math.pi * 3) * amp
        d.line([(x0 + off, yy), (x1 - off, yy)], fill=(120, 106, 88), width=3)
    d.polygon([(x0, y1), (x0 + (x1 - x0) * 0.5, y1 - (y1 - y0) * 0.42), (x1, y1)],
              fill=(132, 116, 96))
    d.line([(x0, y1), (x0 + (x1 - x0) * 0.5, y1 - (y1 - y0) * 0.42), (x1, y1)],
           fill=primary, width=4)


def _tear(d: ImageDraw.ImageDraw, box, rng, severity: str, ink=None) -> None:
    """Ragged torn edge with a dark gap behind it."""
    primary, _ = ink or (_INK["dark"], None)
    x0, y0, x1, y1 = box
    depth = (y1 - y0) * (0.35 if severity == "low" else 0.75)
    pts = [(x0, y0)]
    x = x0
    while x < x1:
        x += rng.uniform(8, 20)
        pts.append((min(x, x1), y0 + rng.uniform(depth * 0.3, depth)))
    pts += [(x1, y0), (x0, y0)]
    d.polygon(pts, fill=(78, 68, 56))
    d.line(pts[:-2], fill=primary, width=3)


DAMAGE_RENDERERS = {
    "scratch": _scratch, "dent": _dent, "crack": _crack,
    "broken_part": _shatter, "crushed_packaging": _crush,
    "torn_packaging": _tear, "water_damage": _dent, "stain": _dent,
}


# ─── Objects ────────────────────────────────────────────────────────────────

def render_car(rng: random.Random, view: str = "front_three_quarter") -> tuple[Image.Image, Dict[str, tuple]]:
    """Returns the image and a map of part name -> bounding box."""
    W, H = 900, 620
    img = Image.new("RGB", (W, H), SKY)
    d = ImageDraw.Draw(img)
    d.rectangle([0, H * 0.62, W, H], fill=GROUND)
    body = rng.choice(BODY_COLOURS)
    dark = tuple(max(0, c - 42) for c in body)

    parts: Dict[str, tuple] = {}

    if view == "rear":
        d.rounded_rectangle([150, 200, 750, 470], 26, fill=body, outline=dark, width=3)
        d.rounded_rectangle([200, 215, 700, 320], 16, fill=(96, 108, 122), outline=dark, width=3)  # rear glass
        parts["trunk"] = (200, 330, 700, 400)
        d.rounded_rectangle([200, 330, 700, 400], 8, fill=body, outline=dark, width=2)
        parts["rear_bumper"] = (160, 405, 740, 468)
        d.rounded_rectangle([160, 405, 740, 468], 12, fill=dark, outline=(50, 50, 54), width=2)
        parts["taillight"] = (190, 335, 290, 392)
        d.rounded_rectangle([190, 335, 290, 392], 8, fill=(178, 54, 48), outline=dark, width=2)
        d.rounded_rectangle([610, 335, 710, 392], 8, fill=(178, 54, 48), outline=dark, width=2)
        d.ellipse([210, 440, 310, 540], fill=(38, 38, 42))
        d.ellipse([590, 440, 690, 540], fill=(38, 38, 42))
    else:
        # front three-quarter
        d.polygon([(120, 470), (170, 300), (400, 250), (640, 262), (760, 330), (790, 470)],
                  fill=body, outline=dark, width=3)
        d.polygon([(215, 300), (405, 268), (600, 276), (660, 320)], fill=(120, 150, 176))  # windshield
        parts["windshield"] = (215, 268, 660, 320)
        parts["hood"] = (150, 320, 430, 400)
        d.polygon([(150, 400), (175, 322), (430, 300), (440, 396)], fill=body, outline=dark, width=2)
        parts["front_bumper"] = (110, 400, 430, 470)
        d.rounded_rectangle([110, 400, 430, 470], 14, fill=dark, outline=(48, 48, 52), width=2)
        parts["grille"] = (150, 408, 330, 452)
        d.rounded_rectangle([150, 408, 330, 452], 6, fill=(52, 54, 60))
        for gx in range(158, 326, 22):
            d.line([(gx, 412), (gx, 448)], fill=(96, 98, 104), width=3)
        parts["headlight"] = (330, 372, 428, 420)
        d.rounded_rectangle([330, 372, 428, 420], 10, fill=(232, 234, 226), outline=dark, width=2)
        parts["door"] = (600, 300, 760, 440)
        d.polygon([(600, 300), (760, 330), (770, 440), (605, 435)], fill=body, outline=dark, width=2)
        parts["side_mirror"] = (612, 296, 668, 328)
        d.ellipse([612, 296, 668, 328], fill=dark)
        parts["fender"] = (430, 330, 600, 440)
        d.ellipse([440, 400, 570, 530], fill=(38, 38, 42))
        d.ellipse([468, 428, 542, 502], fill=(148, 150, 154))
        d.ellipse([700, 420, 800, 520], fill=(38, 38, 42))
        parts["wheel"] = (440, 400, 570, 530)

    return img, parts


def render_laptop(rng: random.Random) -> tuple[Image.Image, Dict[str, tuple]]:
    W, H = 900, 620
    img = Image.new("RGB", (W, H), (226, 226, 230))
    d = ImageDraw.Draw(img)
    shell = rng.choice([(112, 116, 124), (196, 198, 204), (58, 60, 66)])
    dark = tuple(max(0, c - 40) for c in shell)
    parts: Dict[str, tuple] = {}

    d.polygon([(180, 90), (720, 90), (760, 380), (140, 380)], fill=shell, outline=dark, width=3)
    parts["screen"] = (205, 112, 700, 358)
    d.polygon([(205, 112), (698, 112), (730, 358), (172, 358)], fill=(26, 30, 40))
    parts["lid"] = (180, 90, 760, 380)
    parts["hinge"] = (140, 372, 760, 398)
    d.rectangle([140, 372, 760, 398], fill=dark)
    d.polygon([(140, 398), (760, 398), (830, 520), (70, 520)], fill=shell, outline=dark, width=3)
    parts["body"] = (70, 398, 830, 520)
    parts["keyboard"] = (150, 408, 750, 480)
    for r in range(5):
        for c in range(15):
            x = 165 + c * 39 + r * 5
            y = 414 + r * 13
            d.rounded_rectangle([x, y, x + 30, y + 10], 2, fill=(44, 46, 52))
    parts["trackpad"] = (390, 486, 520, 514)
    d.rounded_rectangle([390, 486, 520, 514], 4, fill=dark, outline=(90, 92, 98), width=1)
    parts["corner"] = (70, 470, 180, 520)
    parts["port"] = (760, 400, 830, 440)
    return img, parts


def render_package(rng: random.Random) -> tuple[Image.Image, Dict[str, tuple]]:
    W, H = 900, 620
    img = Image.new("RGB", (W, H), (214, 214, 218))
    d = ImageDraw.Draw(img)
    card = rng.choice([(196, 158, 108), (176, 140, 96), (208, 174, 126)])
    dark = tuple(max(0, c - 46) for c in card)
    parts: Dict[str, tuple] = {}

    d.polygon([(220, 200), (620, 200), (620, 500), (220, 500)], fill=card, outline=dark, width=3)
    d.polygon([(620, 200), (740, 140), (740, 440), (620, 500)], fill=tuple(max(0, c - 24) for c in card),
              outline=dark, width=3)
    d.polygon([(220, 200), (340, 140), (740, 140), (620, 200)], fill=tuple(min(255, c + 18) for c in card),
              outline=dark, width=3)
    parts["box"] = (220, 140, 740, 500)
    parts["package_side"] = (620, 200, 740, 460)
    parts["seal"] = (400, 140, 452, 500)
    d.polygon([(400, 200), (452, 200), (452, 500), (400, 500)], fill=(226, 222, 210))
    d.polygon([(400, 200), (452, 200), (520, 158), (468, 158)], fill=(214, 210, 200))
    parts["label"] = (470, 250, 596, 350)
    d.rectangle([470, 250, 596, 350], fill=(244, 244, 240), outline=(150, 148, 144), width=2)
    for i in range(9):   # barcode-ish bars, no readable text
        d.line([(482 + i * 13, 262), (482 + i * 13, 306)], fill=(40, 40, 44), width=rng.choice([2, 4]))
    parts["package_corner"] = (220, 430, 330, 500)
    parts["contents"] = (240, 220, 390, 480)
    return img, parts


RENDERERS = {"car": render_car, "laptop": render_laptop, "package": render_package}


# ─── Quality degradation ────────────────────────────────────────────────────

def degrade(img: Image.Image, mode: str, rng: random.Random) -> Image.Image:
    """Apply a realistic capture defect."""
    if mode == "blurry":
        return img.filter(ImageFilter.GaussianBlur(radius=6.5))
    if mode == "very_blurry":
        return img.filter(ImageFilter.GaussianBlur(radius=13))
    if mode == "dark":
        return Image.eval(img, lambda p: int(p * 0.22))
    if mode == "overexposed":
        return Image.eval(img, lambda p: min(255, int(p * 1.05 + 140)))
    if mode == "cropped":
        w, h = img.size
        return img.crop((int(w * 0.62), int(h * 0.58), w, h)).resize((w, h), Image.LANCZOS)
    if mode == "low_res":
        w, h = img.size
        return img.resize((w // 11, h // 11), Image.NEAREST).resize((w, h), Image.NEAREST)
    if mode == "obstructed":
        out = img.copy()
        d = ImageDraw.Draw(out)
        w, h = out.size
        d.rectangle([0, int(h * 0.34), w, int(h * 0.78)], fill=(38, 38, 42))
        return out
    return img


def render_case(
    object_category: str,
    damaged_part: str | None,
    issue_type: str | None,
    severity: str,
    quality: str = "good",
    seed: int = 0,
    view: str = "front_three_quarter",
) -> Image.Image:
    """Render one claim image with damage at a known part. Ground truth by construction."""
    rng = random.Random(seed)
    renderer = RENDERERS[object_category]
    img, parts = (renderer(rng, view=view) if object_category == "car" else renderer(rng))

    if damaged_part and issue_type and severity != "none":
        box = parts.get(damaged_part)
        if box:
            img = _apply_clipped_damage(img, box, issue_type, severity, rng)

    return degrade(img, quality, rng)


def _apply_clipped_damage(
    img: Image.Image, box: tuple, issue_type: str, severity: str, rng: random.Random
) -> Image.Image:
    """
    Draw damage on a transparent layer and composite it through a mask of the part's box.

    Clipping matters for ground-truth integrity: an unclipped crack drawn near the edge of a
    laptop screen spilled onto the background, which would have meant the "damaged part" label
    no longer described where the damage actually appeared.
    """
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ink = _contrast_ink(img, box)
    DAMAGE_RENDERERS.get(issue_type, _scratch)(ImageDraw.Draw(layer), box, rng, severity, ink)

    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rectangle(list(box), fill=255)
    layer.putalpha(Image.composite(layer.getchannel("A"), Image.new("L", img.size, 0), mask))

    out = img.convert("RGBA")
    out.alpha_composite(layer)
    return out.convert("RGB")


def render_animal(seed: int = 0) -> Image.Image:
    """A non-vehicle subject, for the wrong-object cases."""
    rng = random.Random(seed)
    img = Image.new("RGB", (900, 620), (198, 208, 186))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 430, 900, 620], fill=(126, 146, 104))
    fur = rng.choice([(196, 152, 96), (86, 82, 78), (228, 224, 216)])
    d.ellipse([300, 300, 640, 500], fill=fur)                    # body
    d.ellipse([560, 230, 720, 390], fill=fur)                    # head
    d.polygon([(578, 250), (600, 178), (632, 254)], fill=fur)    # ears
    d.polygon([(660, 254), (692, 178), (706, 256)], fill=fur)
    d.ellipse([604, 292, 624, 316], fill=(30, 30, 34))           # eyes
    d.ellipse([662, 292, 682, 316], fill=(30, 30, 34))
    d.polygon([(632, 330), (656, 330), (644, 346)], fill=(214, 138, 142))
    for i in (-1, 1):                                            # whiskers
        d.line([(644, 344), (744 * i if i > 0 else 548, 322)], fill=(240, 240, 236), width=2)
    d.arc([250, 330, 340, 470], 60, 300, fill=fur, width=18)     # tail
    for x in (330, 420, 500, 580):                               # legs
        d.rounded_rectangle([x, 470, x + 34, 520], 8, fill=fur)
    return img


def render_document(seed: int = 0) -> Image.Image:
    """A receipt-like non-damage subject."""
    rng = random.Random(seed)
    img = Image.new("RGB", (900, 620), (170, 170, 174))
    d = ImageDraw.Draw(img)
    d.rectangle([260, 60, 640, 580], fill=(250, 250, 246), outline=(180, 178, 174), width=2)
    y = 110
    while y < 540:
        w = rng.randint(120, 330)
        d.line([(292, y), (292 + w, y)], fill=(88, 88, 92), width=rng.choice([3, 4]))
        y += rng.randint(20, 34)
    return img
