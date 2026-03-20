"""
Renderer: generates an axonometric (planometric) floor plan image
inspired by HomeByMe's style.

Projection used: planometric at 45°
  - floor plan is rotated 45° and viewed from above-right
  - walls extruded at 45° upward
  - warm wood tones, clean lines, labeled zones
"""

from __future__ import annotations

import math
from io import BytesIO
from typing import Optional

from PIL import Image, ImageDraw, ImageFont, ImageFilter

from layout_engine import Zone, FurnitureItem

# ---------------------------------------------------------------------------
# Color palette (HomeByMe-inspired warm tones)
# ---------------------------------------------------------------------------
COLORS = {
    "background": (18, 20, 26),
    "floor_wood": (42, 52, 48),
    "floor_wood_alt": (36, 44, 42),
    "wall": (22, 24, 30),
    "wall_side": (15, 17, 22),
    "wall_top": (35, 40, 48),
    # zone floors — distinct dark tones
    "openspace": (38, 58, 52),        # dark teal-green
    "meeting_room": (38, 44, 68),     # dark blue-slate
    "kitchen": (58, 50, 36),          # dark amber
    "bathroom": (34, 46, 56),         # dark steel blue
    "entrance": (50, 44, 56),         # dark mauve
    "phonebooth": (48, 38, 52),       # dark purple
    "lounge": (52, 42, 40),           # dark terracotta
    "corridor": (32, 36, 40),         # dark neutral
    "storage": (28, 32, 30),          # very dark
    "other": (36, 38, 44),
    # furniture
    "desk": (62, 78, 70),
    "desk_shadow": (14, 16, 20),
    "chair": (28, 34, 42),
    "chair_seat": (22, 26, 34),
    "meeting_table": (52, 62, 88),
    "kitchen_counter": (72, 62, 44),
    "dining_table": (62, 72, 50),
    "sofa": (72, 52, 48),
    "sofa_cushion": (88, 64, 58),
    "coffee_table": (58, 52, 44),
    "plant_pot": (64, 44, 32),
    "plant_leaves": (42, 88, 56),
    "toilet_body": (44, 52, 58),
    "sink_body": (40, 50, 56),
    "label_line": (120, 140, 160),
    "label_text": (200, 210, 220),
    "title_text": (230, 235, 242),
    "grid": (30, 34, 40),
}

WALL_HEIGHT = 18   # pixels of wall extrusion
WALL_THICKNESS = 6  # pixels

# ---------------------------------------------------------------------------
# Planometric projection helpers
# ---------------------------------------------------------------------------

def to_screen(x: float, y: float, scale: float, ox: float, oy: float):
    """
    Convert floor-plan coords (in pixels, already scaled) to
    planometric screen coords (45° rotation, top-down view).
    """
    # rotate 45° then scale Y slightly
    sx = (x - y) * 0.707 * scale + ox
    sy = (x + y) * 0.354 * scale + oy
    return (sx, sy)


def room_to_screen_poly(rx: float, ry: float, rw: float, rh: float,
                        plan_w: float, plan_h: float,
                        scale: float, ox: float, oy: float):
    """
    Returns the 4 floor corners of a room in screen coordinates.
    Input: normalized room coords (0-1), plan dimensions in px.
    """
    x0 = rx * plan_w
    y0 = ry * plan_h
    x1 = (rx + rw) * plan_w
    y1 = (ry + rh) * plan_h
    return [
        to_screen(x0, y0, scale, ox, oy),
        to_screen(x1, y0, scale, ox, oy),
        to_screen(x1, y1, scale, ox, oy),
        to_screen(x0, y1, scale, ox, oy),
    ]


def extrude_wall_north(poly, wall_h=WALL_HEIGHT):
    """Extrude the north edge (poly[0]-poly[1]) upward."""
    p0, p1 = poly[0], poly[1]
    return [
        p0,
        p1,
        (p1[0], p1[1] - wall_h),
        (p0[0], p0[1] - wall_h),
    ]


def extrude_wall_west(poly, wall_h=WALL_HEIGHT):
    """Extrude the west edge (poly[3]-poly[0]) upward."""
    p3, p0 = poly[3], poly[0]
    return [
        p3,
        p0,
        (p0[0], p0[1] - wall_h),
        (p3[0], p3[1] - wall_h),
    ]


# ---------------------------------------------------------------------------
# Main render function
# ---------------------------------------------------------------------------

def render_floor_plan(
    floor_plan: dict,
    zones: list[Zone],
    n_people: int,
    output_size: tuple[int, int] = (1400, 900),
    title: Optional[str] = None,
) -> bytes:
    """
    Render the floor plan with zones and furniture.
    Returns PNG bytes.
    """
    W, H = output_size
    img = Image.new("RGBA", (W, H), COLORS["background"] + (255,))
    draw = ImageDraw.Draw(img)

    # --- Compute scale and origin ---
    rooms = floor_plan.get("rooms", [])
    plan_px_w = 800.0
    plan_px_h = 600.0

    # Fit the plan into the canvas with margins
    margin = 120
    scale = 1.0
    # Origin: center the rotated plan
    ox = W * 0.5
    oy = H * 0.18  # push toward top so labels fit below

    # Build room_id → room dict
    room_map = {r["id"]: r for r in rooms}

    # --- Draw floors (back to front, bottom rooms first) ---
    # Sort zones so we paint floors in depth order
    def depth_key(z: Zone):
        r = room_map.get(z.room_id)
        if not r:
            return 0
        return r.get("x", 0) + r.get("y", 0)

    zones_sorted = sorted(zones, key=depth_key)

    for zone in zones_sorted:
        r = room_map.get(zone.room_id)
        if not r:
            continue
        poly = room_to_screen_poly(
            r["x"], r["y"], r["w"], r["h"],
            plan_px_w, plan_px_h, scale, ox, oy
        )
        # Floor fill with wood grain effect
        floor_color = COLORS.get(zone.color_key, COLORS["floor_wood"])
        draw.polygon(poly, fill=floor_color, outline=COLORS["wall"])

        # Wood grain lines (horizontal stripes)
        _draw_wood_grain(draw, poly, floor_color)

    # --- Draw walls ---
    for zone in zones_sorted:
        r = room_map.get(zone.room_id)
        if not r:
            continue
        poly = room_to_screen_poly(
            r["x"], r["y"], r["w"], r["h"],
            plan_px_w, plan_px_h, scale, ox, oy
        )
        # North wall (top edge in planometric view)
        wall_n = extrude_wall_north(poly, WALL_HEIGHT)
        draw.polygon(wall_n, fill=COLORS["wall_top"], outline=COLORS["wall"])
        # West wall
        wall_w = extrude_wall_west(poly, WALL_HEIGHT)
        draw.polygon(wall_w, fill=COLORS["wall_side"], outline=COLORS["wall"])

    # --- Draw furniture ---
    for zone in zones_sorted:
        r = room_map.get(zone.room_id)
        if not r:
            continue
        for item in zone.furniture:
            _draw_furniture(draw, item, r, plan_px_w, plan_px_h, scale, ox, oy)

    # --- Draw zone labels ---
    label_positions = []
    for zone in zones:
        r = room_map.get(zone.room_id)
        if not r:
            continue
        # Center of room in screen coords
        cx = (r["x"] + r["w"] / 2) * plan_px_w
        cy = (r["y"] + r["h"] / 2) * plan_px_h
        scx, scy = to_screen(cx, cy, scale, ox, oy)
        label_positions.append((zone.label, scx, scy))

    _draw_labels(draw, img, label_positions, W, H, oy)

    # --- Title ---
    _draw_title(draw, title or f"Plan d'aménagement {n_people}p", W)

    # --- Legend ---
    _draw_legend(draw, zones, W, H)

    # Slight blur for antialiasing effect
    img_rgb = img.convert("RGB")

    buf = BytesIO()
    img_rgb.save(buf, format="PNG", dpi=(150, 150))
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------

def _draw_wood_grain(draw: ImageDraw.ImageDraw, poly: list, base_color: tuple):
    """Draw subtle horizontal lines inside a polygon for wood effect."""
    if len(poly) < 3:
        return
    ys = [p[1] for p in poly]
    y_min, y_max = min(ys), max(ys)
    grain_color = tuple(max(0, c - 8) for c in base_color[:3])
    step = 6
    y = y_min + step
    while y < y_max:
        # Find x intersections at this y (simplified: use bbox)
        xs = [p[0] for p in poly]
        x_min, x_max = min(xs), max(xs)
        draw.line([(x_min + 2, y), (x_max - 2, y)],
                  fill=grain_color + (60,), width=1)
        y += step


def _draw_furniture(draw: ImageDraw.ImageDraw, item: FurnitureItem,
                    room: dict, plan_px_w: float, plan_px_h: float,
                    scale: float, ox: float, oy: float):
    """Draw a single furniture item in the room."""
    rx, ry, rw, rh = room["x"], room["y"], room["w"], room["h"]

    # Absolute plan coords of furniture
    fx = (rx + item.x * rw) * plan_px_w
    fy = (ry + item.y * rh) * plan_px_h
    fw = item.w * rw * plan_px_w
    fh = item.h * rh * plan_px_h

    # 4 corners in screen space
    poly = [
        to_screen(fx,      fy,      scale, ox, oy),
        to_screen(fx + fw, fy,      scale, ox, oy),
        to_screen(fx + fw, fy + fh, scale, ox, oy),
        to_screen(fx,      fy + fh, scale, ox, oy),
    ]

    t = item.type

    if t == "desk":
        # Shadow first
        shadow = [(p[0] + 2, p[1] + 2) for p in poly]
        draw.polygon(shadow, fill=(160, 140, 100, 100))
        draw.polygon(poly, fill=COLORS["desk"], outline=COLORS["desk_shadow"])
        # Monitor hint (small rectangle on back of desk)
        mon = [
            to_screen(fx + fw * 0.2, fy + fh * 0.05, scale, ox, oy),
            to_screen(fx + fw * 0.8, fy + fh * 0.05, scale, ox, oy),
            to_screen(fx + fw * 0.8, fy + fh * 0.30, scale, ox, oy),
            to_screen(fx + fw * 0.2, fy + fh * 0.30, scale, ox, oy),
        ]
        draw.polygon(mon, fill=(60, 60, 70), outline=(40, 40, 50))

    elif t == "chair":
        draw.polygon(poly, fill=COLORS["chair"], outline=COLORS["chair_seat"])
        # Seat circle
        cx = sum(p[0] for p in poly) / 4
        cy = sum(p[1] for p in poly) / 4
        r = min(fw, fh) * 0.3
        draw.ellipse([cx - r, cy - r, cx + r, cy + r],
                     fill=COLORS["chair_seat"])

    elif t in ("meeting_table", "dining_table"):
        shadow = [(p[0] + 3, p[1] + 3) for p in poly]
        draw.polygon(shadow, fill=(150, 128, 90, 80))
        draw.polygon(poly, fill=COLORS["meeting_table"], outline=COLORS["desk_shadow"])

    elif t == "kitchen_counter":
        draw.polygon(poly, fill=COLORS["kitchen_counter"],
                     outline=(130, 112, 90))
        # Counter top line
        inner = [
            to_screen(fx + fw * 0.05, fy + fh * 0.1, scale, ox, oy),
            to_screen(fx + fw * 0.95, fy + fh * 0.1, scale, ox, oy),
            to_screen(fx + fw * 0.95, fy + fh * 0.9, scale, ox, oy),
            to_screen(fx + fw * 0.05, fy + fh * 0.9, scale, ox, oy),
        ]
        draw.polygon(inner, outline=(160, 138, 108), fill=None)

    elif t == "sofa":
        draw.polygon(poly, fill=COLORS["sofa"], outline=(100, 85, 72))
        # Cushions
        n_cushions = max(2, int(fw / 25))
        for i in range(n_cushions):
            cx0 = fx + i * fw / n_cushions + fw * 0.02 / n_cushions
            cx1 = fx + (i + 1) * fw / n_cushions - fw * 0.02 / n_cushions
            cp = [
                to_screen(cx0, fy + fh * 0.15, scale, ox, oy),
                to_screen(cx1, fy + fh * 0.15, scale, ox, oy),
                to_screen(cx1, fy + fh * 0.85, scale, ox, oy),
                to_screen(cx0, fy + fh * 0.85, scale, ox, oy),
            ]
            draw.polygon(cp, fill=COLORS["sofa_cushion"],
                         outline=(110, 95, 82))

    elif t == "coffee_table":
        draw.polygon(poly, fill=COLORS["coffee_table"], outline=(150, 128, 95))

    elif t == "plant":
        # Pot
        pot = [
            to_screen(fx + fw * 0.25, fy + fh * 0.6, scale, ox, oy),
            to_screen(fx + fw * 0.75, fy + fh * 0.6, scale, ox, oy),
            to_screen(fx + fw * 0.75, fy + fh * 1.0, scale, ox, oy),
            to_screen(fx + fw * 0.25, fy + fh * 1.0, scale, ox, oy),
        ]
        draw.polygon(pot, fill=COLORS["plant_pot"])
        # Leaves circle
        lcx = sum(p[0] for p in poly) / 4
        lcy = sum(p[1] for p in poly) / 4 - fh * 0.1
        lr = min(fw, fh) * 0.42
        draw.ellipse([lcx - lr, lcy - lr, lcx + lr, lcy + lr],
                     fill=COLORS["plant_leaves"],
                     outline=(65, 98, 55))
        # Inner circle
        draw.ellipse([lcx - lr * 0.5, lcy - lr * 0.5,
                      lcx + lr * 0.5, lcy + lr * 0.5],
                     fill=(95, 132, 82))

    elif t == "toilet":
        draw.polygon(poly, fill=COLORS["toilet_body"], outline=(180, 178, 172))
        # Bowl ellipse
        cx = sum(p[0] for p in poly) / 4
        cy = sum(p[1] for p in poly) / 4 + fh * 0.1
        draw.ellipse([cx - fw * 0.4, cy - fh * 0.3,
                      cx + fw * 0.4, cy + fh * 0.3],
                     fill=(215, 213, 208), outline=(180, 178, 172))

    elif t == "sink":
        draw.polygon(poly, fill=COLORS["sink_body"], outline=(180, 178, 172))
        cx = sum(p[0] for p in poly) / 4
        cy = sum(p[1] for p in poly) / 4
        draw.ellipse([cx - fw * 0.35, cy - fh * 0.35,
                      cx + fw * 0.35, cy + fh * 0.35],
                     fill=(200, 198, 194), outline=(170, 168, 164))


def _draw_labels(draw: ImageDraw.ImageDraw, img: Image.Image,
                 label_positions: list, W: int, H: int, plan_top: float):
    """
    Draw zone labels with leader lines, spread around the plan.
    Labels alternate left/right of the plan.
    """
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
        font_small = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
    except Exception:
        font = ImageFont.load_default()
        font_small = font

    margin_x = 30
    left_x = margin_x
    right_x = W - margin_x

    # Assign alternating sides
    sorted_labels = sorted(label_positions, key=lambda lp: lp[2])  # by screen y
    n = len(sorted_labels)

    for i, (label, scx, scy) in enumerate(sorted_labels):
        side = "left" if i % 2 == 0 else "right"
        # Leader line endpoint
        if side == "left":
            lx = left_x
        else:
            bbox = draw.textbbox((0, 0), label, font=font)
            tw = bbox[2] - bbox[0]
            lx = right_x - tw

        ly = scy
        ly = max(plan_top + 10, min(H - 30, ly))

        # Draw leader line
        mid_x = (scx + lx) / 2
        draw.line([(scx, scy), (mid_x, ly), (lx, ly)],
                  fill=COLORS["label_line"], width=1)
        draw.ellipse([scx - 3, scy - 3, scx + 3, scy + 3],
                     fill=COLORS["label_line"])

        # Draw text
        draw.text((lx, ly - 8), label, fill=COLORS["label_text"], font=font)


def _draw_title(draw: ImageDraw.ImageDraw, title: str, W: int):
    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 32)
    except Exception:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), title, font=font)
    tw = bbox[2] - bbox[0]
    draw.text(((W - tw) / 2, 28), title, fill=COLORS["title_text"], font=font)


def _draw_legend(draw: ImageDraw.ImageDraw, zones: list[Zone], W: int, H: int):
    """Small color legend at the bottom."""
    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11)
    except Exception:
        font = ImageFont.load_default()

    seen = {}
    for z in zones:
        if z.color_key not in seen:
            seen[z.color_key] = z.label

    x = 20
    y = H - 30
    for key, label in seen.items():
        color = COLORS.get(key, COLORS["other"])
        draw.rectangle([x, y, x + 14, y + 14], fill=color, outline=(120, 110, 95))
        draw.text((x + 18, y), label[:30], fill=COLORS["label_text"], font=font)
        x += max(150, len(label) * 7 + 22)
        if x > W - 150:
            break
