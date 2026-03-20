"""
Renderer: generates a planometric (45° axonometric) floor plan image
inspired by HomeByMe's style.

Key changes vs original:
- Light warm color palette matching HomeByMe references
- Scale derived from real-world dimensions (total_width_m × total_height_m)
- Label text placed ABOVE the horizontal leader line
- Capacity shown for openspace and meeting rooms
"""

from __future__ import annotations

import math
from io import BytesIO
from typing import Optional

from PIL import Image, ImageDraw, ImageFont, ImageFilter

from layout_engine import Zone, FurnitureItem

# ---------------------------------------------------------------------------
# Color palette (HomeByMe warm tones — light floors, dark charcoal walls)
# ---------------------------------------------------------------------------
COLORS = {
    "background": (228, 225, 218),      # light warm gray page
    "floor_wood": (218, 190, 138),      # warm honey blonde wood
    "floor_wood_alt": (208, 180, 125),  # slightly darker alternate grain
    "wall": (38, 32, 26),               # dark charcoal brown
    "wall_side": (28, 22, 16),          # darker wall side face
    "wall_top": (65, 58, 50),           # medium charcoal wall top
    # zone floors — subtle tonal differences
    "openspace": (218, 190, 138),
    "meeting_room": (208, 182, 145),
    "kitchen": (178, 152, 110),
    "bathroom": (162, 165, 170),
    "entrance": (212, 202, 178),
    "phonebooth": (188, 170, 148),
    "lounge": (218, 195, 165),
    "corridor": (200, 190, 170),
    "storage": (170, 165, 155),
    "other": (208, 200, 182),
    # furniture
    "desk": (200, 172, 118),
    "desk_shadow": (48, 40, 28),
    "chair": (52, 50, 56),
    "chair_seat": (44, 42, 48),
    "meeting_table": (118, 80, 42),
    "kitchen_counter": (168, 142, 98),
    "dining_table": (155, 130, 85),
    "sofa": (78, 155, 145),
    "sofa_cushion": (95, 175, 165),
    "coffee_table": (155, 128, 80),
    "plant_pot": (138, 90, 52),
    "plant_leaves": (75, 142, 78),
    "toilet_body": (215, 212, 205),
    "sink_body": (212, 208, 200),
    "label_line": (82, 75, 68),
    "label_text": (22, 18, 14),
    "title_text": (22, 18, 14),
    "grid": (215, 208, 198),
}

WALL_HEIGHT = 20    # px of wall extrusion (height of visible wall face)
WALL_THICKNESS = 7  # px outline on floor polygon

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = FONT_BOLD_PATH if bold else FONT_PATH
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


# ---------------------------------------------------------------------------
# Planometric projection helpers
# ---------------------------------------------------------------------------

def to_screen(x: float, y: float, scale: float, ox: float, oy: float):
    """
    Convert floor-plan coords (in pixels) to planometric screen coords.
    45° rotation viewed from above-right.
    """
    sx = (x - y) * 0.707 * scale + ox
    sy = (x + y) * 0.354 * scale + oy
    return (sx, sy)


def room_to_screen_poly(rx, ry, rw, rh, plan_px_w, plan_px_h, scale, ox, oy):
    """4 floor corners of a room in screen coordinates."""
    x0, y0 = rx * plan_px_w, ry * plan_px_h
    x1, y1 = (rx + rw) * plan_px_w, (ry + rh) * plan_px_h
    return [
        to_screen(x0, y0, scale, ox, oy),
        to_screen(x1, y0, scale, ox, oy),
        to_screen(x1, y1, scale, ox, oy),
        to_screen(x0, y1, scale, ox, oy),
    ]


def extrude_wall_north(poly, wall_h=WALL_HEIGHT):
    p0, p1 = poly[0], poly[1]
    return [p0, p1, (p1[0], p1[1] - wall_h), (p0[0], p0[1] - wall_h)]


def extrude_wall_west(poly, wall_h=WALL_HEIGHT):
    p3, p0 = poly[3], poly[0]
    return [p3, p0, (p0[0], p0[1] - wall_h), (p3[0], p3[1] - wall_h)]


# ---------------------------------------------------------------------------
# Scale computation
# ---------------------------------------------------------------------------

def _compute_scale(total_w_m: float, total_h_m: float,
                   avail_w: float, avail_h: float):
    """
    Compute px-per-meter scale so the planometric projection fits the canvas.
    Planometric bounding box (with scale_px px/m):
      screen_width  = (total_w_m + total_h_m) * 0.707 * scale_px
      screen_height = (total_w_m + total_h_m) * 0.354 * scale_px
    """
    factor = (total_w_m + total_h_m)
    scale_px = min(
        avail_w / (factor * 0.707),
        avail_h / (factor * 0.354),
    )
    return max(scale_px, 1.0)


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
    W, H = output_size
    img = Image.new("RGBA", (W, H), COLORS["background"] + (255,))
    draw = ImageDraw.Draw(img)

    rooms = floor_plan.get("rooms", [])
    total_w_m = max(floor_plan.get("total_width_m", 20.0), 1.0)
    total_h_m = max(floor_plan.get("total_height_m", 15.0), 1.0)

    # --- Canvas layout ---
    ML, MR, MT, MB = 195, 195, 85, 65
    avail_w = W - ML - MR   # 1010
    avail_h = H - MT - MB   # 750

    # Scale (px per meter) preserving actual building proportions
    scale_px = _compute_scale(total_w_m, total_h_m, avail_w * 0.92, avail_h * 0.88)
    plan_px_w = total_w_m * scale_px
    plan_px_h = total_h_m * scale_px
    scale = 1.0  # to_screen multiplier (scale already baked into plan_px coords)

    # Projected screen bounding box
    screen_w = (plan_px_w + plan_px_h) * 0.707
    screen_h = (plan_px_w + plan_px_h) * 0.354

    # Origin: leftmost projected point is plan(0, plan_px_h)
    # to_screen(0, plan_px_h) → sx = -plan_px_h*0.707 + ox
    # We want this to align with ML + horizontal centering offset
    ox = ML + (avail_w - screen_w) / 2 + plan_px_h * 0.707
    oy = MT + (avail_h - screen_h) / 2

    room_map = {r["id"]: r for r in rooms}

    # Depth sort (back → front)
    def depth_key(z: Zone):
        r = room_map.get(z.room_id)
        return (r.get("x", 0) + r.get("y", 0)) if r else 0

    zones_sorted = sorted(zones, key=depth_key)

    # --- Draw floors ---
    for zone in zones_sorted:
        r = room_map.get(zone.room_id)
        if not r:
            continue
        poly = room_to_screen_poly(
            r["x"], r["y"], r["w"], r["h"],
            plan_px_w, plan_px_h, scale, ox, oy
        )
        floor_color = COLORS.get(zone.color_key, COLORS["floor_wood"])
        draw.polygon(poly, fill=floor_color, outline=COLORS["wall"])
        _draw_wood_grain(draw, poly, floor_color)

    # --- Draw walls (north + west faces for 3D depth) ---
    for zone in zones_sorted:
        r = room_map.get(zone.room_id)
        if not r:
            continue
        poly = room_to_screen_poly(
            r["x"], r["y"], r["w"], r["h"],
            plan_px_w, plan_px_h, scale, ox, oy
        )
        wall_n = extrude_wall_north(poly, WALL_HEIGHT)
        draw.polygon(wall_n, fill=COLORS["wall_top"], outline=COLORS["wall"])
        wall_w = extrude_wall_west(poly, WALL_HEIGHT)
        draw.polygon(wall_w, fill=COLORS["wall_side"], outline=COLORS["wall"])

    # --- Draw furniture ---
    for zone in zones_sorted:
        r = room_map.get(zone.room_id)
        if not r:
            continue
        for item in zone.furniture:
            _draw_furniture(draw, item, r, plan_px_w, plan_px_h, scale, ox, oy)

    # --- Draw labels ---
    label_items = []
    for zone in zones:
        r = room_map.get(zone.room_id)
        if not r:
            continue
        cx = (r["x"] + r["w"] / 2) * plan_px_w
        cy = (r["y"] + r["h"] / 2) * plan_px_h
        scx, scy = to_screen(cx, cy, scale, ox, oy)
        label_items.append((zone.label, scx, scy, zone.zone_type, zone.capacity))

    _draw_labels(draw, label_items, W, H, oy, screen_h)

    # --- Title ---
    _draw_title(draw, title or f"Plan d'aménagement — {n_people} postes", W)

    img_rgb = img.convert("RGB")
    buf = BytesIO()
    img_rgb.save(buf, format="PNG", dpi=(150, 150))
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------

def _polygon_x_at_y(poly: list, y: float):
    """Return (x_min, x_max) of polygon boundary at scanline y, or None."""
    xs = []
    n = len(poly)
    for i in range(n):
        p1, p2 = poly[i], poly[(i + 1) % n]
        y1, y2 = p1[1], p2[1]
        if y1 == y2:
            continue
        if min(y1, y2) <= y <= max(y1, y2):
            t = (y - y1) / (y2 - y1)
            xs.append(p1[0] + t * (p2[0] - p1[0]))
    if len(xs) >= 2:
        return min(xs), max(xs)
    return None


def _draw_wood_grain(draw: ImageDraw.ImageDraw, poly: list, base_color: tuple):
    """Draw subtle horizontal lines clipped to the polygon interior."""
    if len(poly) < 3:
        return
    ys = [p[1] for p in poly]
    y_min, y_max = min(ys), max(ys)
    grain_color = tuple(max(0, c - 14) for c in base_color[:3])
    step = 6
    y = y_min + step
    while y < y_max:
        seg = _polygon_x_at_y(poly, y)
        if seg:
            draw.line([(seg[0] + 1, y), (seg[1] - 1, y)],
                      fill=grain_color, width=1)
        y += step


def _draw_furniture(draw: ImageDraw.ImageDraw, item: FurnitureItem,
                    room: dict, plan_px_w: float, plan_px_h: float,
                    scale: float, ox: float, oy: float):
    rx, ry, rw, rh = room["x"], room["y"], room["w"], room["h"]
    fx = (rx + item.x * rw) * plan_px_w
    fy = (ry + item.y * rh) * plan_px_h
    fw = item.w * rw * plan_px_w
    fh = item.h * rh * plan_px_h

    poly = [
        to_screen(fx,      fy,      scale, ox, oy),
        to_screen(fx + fw, fy,      scale, ox, oy),
        to_screen(fx + fw, fy + fh, scale, ox, oy),
        to_screen(fx,      fy + fh, scale, ox, oy),
    ]

    t = item.type

    if t == "desk":
        shadow = [(p[0] + 3, p[1] + 3) for p in poly]
        draw.polygon(shadow, fill=(165, 148, 110, 90))
        draw.polygon(poly, fill=COLORS["desk"], outline=COLORS["desk_shadow"])
        # Monitor hint
        mon = [
            to_screen(fx + fw * 0.15, fy + fh * 0.05, scale, ox, oy),
            to_screen(fx + fw * 0.85, fy + fh * 0.05, scale, ox, oy),
            to_screen(fx + fw * 0.85, fy + fh * 0.30, scale, ox, oy),
            to_screen(fx + fw * 0.15, fy + fh * 0.30, scale, ox, oy),
        ]
        draw.polygon(mon, fill=(68, 65, 72), outline=(52, 50, 55))

    elif t == "chair":
        draw.polygon(poly, fill=COLORS["chair"], outline=COLORS["chair_seat"])
        cx = sum(p[0] for p in poly) / 4
        cy = sum(p[1] for p in poly) / 4
        r = min(fw, fh) * 0.28
        draw.ellipse([cx - r, cy - r, cx + r, cy + r],
                     fill=COLORS["chair_seat"])

    elif t in ("meeting_table", "dining_table"):
        shadow = [(p[0] + 3, p[1] + 3) for p in poly]
        draw.polygon(shadow, fill=(148, 115, 75, 80))
        draw.polygon(poly, fill=COLORS["meeting_table"], outline=COLORS["desk_shadow"])
        # Inner highlight line
        inner = [
            to_screen(fx + fw * 0.05, fy + fh * 0.1, scale, ox, oy),
            to_screen(fx + fw * 0.95, fy + fh * 0.1, scale, ox, oy),
            to_screen(fx + fw * 0.95, fy + fh * 0.9, scale, ox, oy),
            to_screen(fx + fw * 0.05, fy + fh * 0.9, scale, ox, oy),
        ]
        draw.polygon(inner, outline=(145, 105, 60), fill=None)

    elif t == "kitchen_counter":
        draw.polygon(poly, fill=COLORS["kitchen_counter"], outline=(138, 110, 75))
        inner = [
            to_screen(fx + fw * 0.05, fy + fh * 0.1, scale, ox, oy),
            to_screen(fx + fw * 0.95, fy + fh * 0.1, scale, ox, oy),
            to_screen(fx + fw * 0.95, fy + fh * 0.9, scale, ox, oy),
            to_screen(fx + fw * 0.05, fy + fh * 0.9, scale, ox, oy),
        ]
        draw.polygon(inner, outline=(158, 130, 88), fill=None)

    elif t == "sofa":
        draw.polygon(poly, fill=COLORS["sofa"], outline=(55, 125, 118))
        n_cushions = max(2, int(fw / 22))
        for i in range(n_cushions):
            cx0 = fx + i * fw / n_cushions + fw * 0.02 / n_cushions
            cx1 = fx + (i + 1) * fw / n_cushions - fw * 0.02 / n_cushions
            cp = [
                to_screen(cx0, fy + fh * 0.12, scale, ox, oy),
                to_screen(cx1, fy + fh * 0.12, scale, ox, oy),
                to_screen(cx1, fy + fh * 0.88, scale, ox, oy),
                to_screen(cx0, fy + fh * 0.88, scale, ox, oy),
            ]
            draw.polygon(cp, fill=COLORS["sofa_cushion"], outline=(62, 138, 128))

    elif t == "coffee_table":
        draw.polygon(poly, fill=COLORS["coffee_table"], outline=(128, 100, 60))

    elif t == "plant":
        pot = [
            to_screen(fx + fw * 0.28, fy + fh * 0.58, scale, ox, oy),
            to_screen(fx + fw * 0.72, fy + fh * 0.58, scale, ox, oy),
            to_screen(fx + fw * 0.72, fy + fh * 1.0,  scale, ox, oy),
            to_screen(fx + fw * 0.28, fy + fh * 1.0,  scale, ox, oy),
        ]
        draw.polygon(pot, fill=COLORS["plant_pot"])
        lcx = sum(p[0] for p in poly) / 4
        lcy = sum(p[1] for p in poly) / 4 - fh * 0.08
        lr = min(fw, fh) * 0.40
        draw.ellipse([lcx - lr, lcy - lr, lcx + lr, lcy + lr],
                     fill=COLORS["plant_leaves"], outline=(55, 112, 58))
        draw.ellipse([lcx - lr * 0.45, lcy - lr * 0.45,
                      lcx + lr * 0.45, lcy + lr * 0.45],
                     fill=(52, 108, 55))

    elif t == "toilet":
        draw.polygon(poly, fill=COLORS["toilet_body"], outline=(175, 172, 165))
        cx = sum(p[0] for p in poly) / 4
        cy = sum(p[1] for p in poly) / 4 + fh * 0.08
        draw.ellipse([cx - fw * 0.38, cy - fh * 0.28,
                      cx + fw * 0.38, cy + fh * 0.28],
                     fill=(225, 222, 215), outline=(175, 172, 165))

    elif t == "sink":
        draw.polygon(poly, fill=COLORS["sink_body"], outline=(175, 172, 165))
        cx = sum(p[0] for p in poly) / 4
        cy = sum(p[1] for p in poly) / 4
        draw.ellipse([cx - fw * 0.32, cy - fh * 0.32,
                      cx + fw * 0.32, cy + fh * 0.32],
                     fill=(205, 202, 196), outline=(165, 162, 156))


def _draw_labels(draw: ImageDraw.ImageDraw,
                 label_items: list,
                 W: int, H: int, plan_top: float, plan_screen_h: float):
    """
    Draw zone labels with leader lines.
    Text is placed ABOVE the horizontal end of the leader line.
    """
    fn = _font(13)
    fn_bold = _font(13, bold=True)
    margin_x = 22

    # Sort by screen y for non-overlapping placement
    sorted_items = sorted(label_items, key=lambda it: it[2])

    # Split left/right based on screen x position (relative to canvas center)
    cx_canvas = W / 2
    left_items  = [it for it in sorted_items if it[1] <= cx_canvas]
    right_items = [it for it in sorted_items if it[1] > cx_canvas]

    plan_bottom = plan_top + plan_screen_h

    def place_side(items, is_left):
        last_ly = plan_top - 999
        min_spacing = 26

        for label, scx, scy, zone_type, capacity in items:
            ly = max(plan_top + 8, min(plan_bottom - 8, scy))
            if ly - last_ly < min_spacing:
                ly = last_ly + min_spacing
            last_ly = ly

            tb = draw.textbbox((0, 0), label, font=fn_bold)
            tw = tb[2] - tb[0]
            th = tb[3] - tb[1]

            if is_left:
                text_x = margin_x
                line_end_x = margin_x + tw
            else:
                text_x = W - margin_x - tw
                line_end_x = W - margin_x

            # Leader: dot → diagonal → horizontal
            draw.ellipse([scx - 3, scy - 3, scx + 3, scy + 3],
                         fill=COLORS["label_line"])
            draw.line([(scx, scy), (line_end_x if is_left else text_x, ly)],
                      fill=COLORS["label_line"], width=1)
            draw.line([(margin_x, ly), (margin_x + tw, ly)] if is_left
                      else [(W - margin_x - tw, ly), (W - margin_x, ly)],
                      fill=COLORS["label_line"], width=1)

            # Text ABOVE the horizontal line
            draw.text((text_x, ly - th - 4), label,
                      fill=COLORS["label_text"], font=fn_bold)

    place_side(left_items,  is_left=True)
    place_side(right_items, is_left=False)


def _draw_title(draw: ImageDraw.ImageDraw, title: str, W: int):
    fn = _font(28, bold=True)
    tb = draw.textbbox((0, 0), title, font=fn)
    tw = tb[2] - tb[0]
    draw.text(((W - tw) / 2, 24), title, fill=COLORS["title_text"], font=fn)
