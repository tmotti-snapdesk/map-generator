"""
Layout Engine: assigns zones and furniture to rooms based on:
- the parsed floor plan (rooms + dimensions)
- the number of collaborators (derived from area + density scenario)
- business rules
"""

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class FurnitureItem:
    type: str          # desk|chair|meeting_table|kitchen_counter|sofa|plant|etc.
    x: float           # normalized 0-1 within the room
    y: float
    w: float
    h: float
    rotation: int = 0  # degrees (0, 90, 180, 270)
    label: Optional[str] = None


@dataclass
class Zone:
    room_id: str
    zone_type: str      # openspace|meeting_room|kitchen|bathroom|entrance|phonebooth|lounge
    label: str
    capacity: int = 0   # number of people (for openspace / meeting rooms)
    furniture: list[FurnitureItem] = field(default_factory=list)
    color_key: str = "openspace"  # used by renderer


# ---------------------------------------------------------------------------
# Business rules
# ---------------------------------------------------------------------------

def _meeting_rooms_needed(n_people: int) -> list[int]:
    """
    Returns a list of meeting room capacities to create.
    Rules (inferred from references):
      ≤10p  → 1×4p
      11-20p → 1×6p + 1×4p
      21-30p → 1×8p + 1×6p + 1×4p
      31-40p → 2×8p + 1×6p + 1×4p
      +10p   → +1×8p per bracket
    """
    rooms = []
    bracket = n_people
    while bracket > 0:
        if bracket >= 21:
            rooms.append(8)
        elif bracket >= 11:
            rooms.append(6)
        else:
            rooms.append(4)
        bracket -= 10
    return sorted(rooms, reverse=True)


def _has_phonebooth(n_people: int, total_area_m2: float) -> bool:
    return n_people >= 15 and total_area_m2 >= 150


def _has_lounge(n_people: int, total_area_m2: float) -> bool:
    return n_people >= 20 and total_area_m2 >= 200


# ---------------------------------------------------------------------------
# Scenario generation (replaces manual people count)
# ---------------------------------------------------------------------------

# (label, m² per person, density_key)
DENSITY_SCENARIOS = [
    ("Scénario compact",  6.5, "compact"),
    ("Scénario aéré",     8.0, "airy"),
]


def compute_scenarios(floor_plan: dict, area_m2: float) -> list[dict]:
    """
    Given the parsed floor plan and total surface (m²), compute 2 layout
    scenarios at different densities (6.5 m²/poste and 8 m²/poste).
    Returns a list of dicts: {label, density, n_people, zones}
    """
    results = []
    for label, m2_per_person, density in DENSITY_SCENARIOS:
        n_people = max(1, round(area_m2 / m2_per_person))
        zones = compute_layout(floor_plan, n_people, m2_per_person)
        results.append({
            "label": label,
            "density": density,
            "n_people": n_people,
            "zones": zones,
        })
    return results


# ---------------------------------------------------------------------------
# Furniture templates (positions normalized within the room bbox)
# ---------------------------------------------------------------------------

def _desk_cluster(n: int) -> list[FurnitureItem]:
    """
    Generate n desk + chair pairs arranged in rows.
    Desks face the same direction (toward 'north' wall).
    """
    items = []
    cols = max(1, min(n, 3))
    rows = (n + cols - 1) // cols
    desk_w, desk_h = 0.28, 0.14
    chair_w, chair_h = 0.10, 0.10
    pad_x = (1.0 - cols * (desk_w + 0.04)) / 2
    pad_y = 0.08

    for i in range(n):
        col = i % cols
        row = i // cols
        dx = pad_x + col * (desk_w + 0.04)
        dy = pad_y + row * (desk_h + chair_h + 0.06)
        items.append(FurnitureItem(type="desk", x=dx, y=dy, w=desk_w, h=desk_h))
        items.append(FurnitureItem(
            type="chair",
            x=dx + desk_w / 2 - chair_w / 2,
            y=dy + desk_h + 0.01,
            w=chair_w, h=chair_h,
        ))
    return items


def _meeting_table(capacity: int) -> list[FurnitureItem]:
    """Central table + chairs around it."""
    items = []
    # Table proportions: 4p=rect small, 6p=rect medium, 8p=rect large
    tw = 0.55
    th = 0.30 if capacity <= 4 else (0.35 if capacity <= 6 else 0.40)
    tx = (1.0 - tw) / 2
    ty = (1.0 - th) / 2
    items.append(FurnitureItem(type="meeting_table", x=tx, y=ty, w=tw, h=th,
                               label=f"Table {capacity}p"))
    cw, ch = 0.09, 0.09
    # chairs on long sides
    sides = capacity // 2
    for i in range(sides):
        xpos = tx + (i + 0.5) * tw / sides - cw / 2
        # top side
        items.append(FurnitureItem(type="chair", x=xpos, y=ty - ch - 0.02, w=cw, h=ch))
        # bottom side
        items.append(FurnitureItem(type="chair", x=xpos, y=ty + th + 0.02, w=cw, h=ch))
    return items


def _kitchen_furniture() -> list[FurnitureItem]:
    return [
        FurnitureItem(type="kitchen_counter", x=0.05, y=0.05, w=0.70, h=0.18),
        FurnitureItem(type="kitchen_counter", x=0.05, y=0.27, w=0.20, h=0.18),
        FurnitureItem(type="dining_table", x=0.30, y=0.45, w=0.40, h=0.25),
        FurnitureItem(type="chair", x=0.30, y=0.40, w=0.09, h=0.09),
        FurnitureItem(type="chair", x=0.45, y=0.40, w=0.09, h=0.09),
        FurnitureItem(type="chair", x=0.60, y=0.40, w=0.09, h=0.09),
        FurnitureItem(type="chair", x=0.30, y=0.72, w=0.09, h=0.09),
        FurnitureItem(type="chair", x=0.45, y=0.72, w=0.09, h=0.09),
        FurnitureItem(type="chair", x=0.60, y=0.72, w=0.09, h=0.09),
        FurnitureItem(type="plant", x=0.82, y=0.10, w=0.10, h=0.10),
    ]


def _bathroom_furniture() -> list[FurnitureItem]:
    return [
        FurnitureItem(type="toilet", x=0.10, y=0.10, w=0.20, h=0.25),
        FurnitureItem(type="toilet", x=0.40, y=0.10, w=0.20, h=0.25),
        FurnitureItem(type="sink", x=0.10, y=0.65, w=0.20, h=0.15),
        FurnitureItem(type="sink", x=0.40, y=0.65, w=0.20, h=0.15),
    ]


def _phonebooth_furniture() -> list[FurnitureItem]:
    return [
        FurnitureItem(type="desk", x=0.15, y=0.20, w=0.70, h=0.20),
        FurnitureItem(type="chair", x=0.35, y=0.45, w=0.30, h=0.25),
    ]


def _lounge_furniture() -> list[FurnitureItem]:
    return [
        FurnitureItem(type="sofa", x=0.05, y=0.10, w=0.55, h=0.20),
        FurnitureItem(type="sofa", x=0.05, y=0.55, w=0.30, h=0.20),
        FurnitureItem(type="coffee_table", x=0.20, y=0.35, w=0.30, h=0.18),
        FurnitureItem(type="plant", x=0.75, y=0.10, w=0.15, h=0.15),
        FurnitureItem(type="plant", x=0.75, y=0.70, w=0.15, h=0.15),
    ]


# ---------------------------------------------------------------------------
# Main layout function
# ---------------------------------------------------------------------------

def compute_layout(floor_plan: dict, n_people: int, m2_per_person: float = 8.0) -> list[Zone]:
    """
    Given the parsed floor plan and number of collaborators,
    return a list of Zone objects with furniture assigned.
    """
    rooms = floor_plan.get("rooms", [])
    total_w = floor_plan.get("total_width_m", 20.0)
    total_h = floor_plan.get("total_height_m", 15.0)
    total_area = total_w * total_h

    # Sort rooms by area descending (normalized coords × real area)
    def room_area(r):
        return r.get("w", 0.1) * r.get("h", 0.1) * total_area

    rooms_sorted = sorted(rooms, key=room_area, reverse=True)

    meeting_caps = _meeting_rooms_needed(n_people)
    need_kitchen = True
    need_bathroom = True
    need_phonebooth = _has_phonebooth(n_people, total_area)
    need_lounge = _has_lounge(n_people, total_area)

    zones: list[Zone] = []
    remaining_openspace = n_people

    # --- Priority: assign pre-labeled rooms first ---
    type_map = {
        "kitchen": "kitchen",
        "bathroom": "bathroom",
        "entrance": "entrance",
        "corridor": "corridor",
        "storage": "storage",
    }

    assigned_ids = set()

    for room in rooms_sorted:
        rid = room["id"]
        rtype = room.get("type", "other")
        if rtype in type_map:
            zone_type = type_map[rtype]
            label = _zone_label(zone_type, 0)
            furniture = _furniture_for_type(zone_type, 0)
            zones.append(Zone(
                room_id=rid,
                zone_type=zone_type,
                label=label,
                furniture=furniture,
                color_key=zone_type,
            ))
            assigned_ids.add(rid)
            if zone_type == "kitchen":
                need_kitchen = False
            if zone_type == "bathroom":
                need_bathroom = False

        elif rtype == "meeting_room" and meeting_caps:
            cap = meeting_caps.pop(0)
            zones.append(Zone(
                room_id=rid,
                zone_type="meeting_room",
                label=f"Salle de réunion {cap}p",
                capacity=cap,
                furniture=_meeting_table(cap),
                color_key="meeting_room",
            ))
            assigned_ids.add(rid)

    # --- Assign remaining unassigned rooms ---
    unassigned = [r for r in rooms_sorted if r["id"] not in assigned_ids]

    for room in unassigned:
        rid = room["id"]
        rtype = room.get("type", "other")
        area = room_area(room)

        # Never reassign a room already identified as openspace by the parser
        if rtype == "openspace":
            continue

        if need_kitchen and area >= 12:
            zones.append(Zone(
                room_id=rid,
                zone_type="kitchen",
                label="Espace déjeuner / Cuisine",
                furniture=_kitchen_furniture(),
                color_key="kitchen",
            ))
            need_kitchen = False
            assigned_ids.add(rid)

        elif need_bathroom and area < 20:
            zones.append(Zone(
                room_id=rid,
                zone_type="bathroom",
                label="Sanitaires",
                furniture=_bathroom_furniture(),
                color_key="bathroom",
            ))
            need_bathroom = False
            assigned_ids.add(rid)

        elif meeting_caps and area >= 10:
            cap = meeting_caps.pop(0)
            zones.append(Zone(
                room_id=rid,
                zone_type="meeting_room",
                label=f"Salle de réunion {cap}p",
                capacity=cap,
                furniture=_meeting_table(cap),
                color_key="meeting_room",
            ))
            assigned_ids.add(rid)

        elif need_phonebooth and area < 8:
            zones.append(Zone(
                room_id=rid,
                zone_type="phonebooth",
                label="Phonebooth",
                furniture=_phonebooth_furniture(),
                color_key="phonebooth",
            ))
            need_phonebooth = False
            assigned_ids.add(rid)

        elif need_lounge and 15 <= area <= 40:
            zones.append(Zone(
                room_id=rid,
                zone_type="lounge",
                label="Espace détente",
                furniture=_lounge_furniture(),
                color_key="lounge",
            ))
            need_lounge = False
            assigned_ids.add(rid)

    # --- Fill remaining large rooms with openspace ---
    still_unassigned = [r for r in rooms_sorted if r["id"] not in assigned_ids]
    openspace_rooms = sorted(still_unassigned, key=room_area, reverse=True)

    for room in openspace_rooms:
        rid = room["id"]
        area = room_area(room)
        # estimate desks that fit based on scenario density
        desks = min(remaining_openspace, max(1, int(area / m2_per_person)))
        remaining_openspace -= desks
        zones.append(Zone(
            room_id=rid,
            zone_type="openspace",
            label=f"Openspace {desks}p",
            capacity=desks,
            furniture=_desk_cluster(desks),
            color_key="openspace",
        ))

    # --- Fallback: if mandatory zones not placed, append virtual zones ---
    if need_kitchen:
        zones.append(_virtual_zone("kitchen", "Espace déjeuner / Cuisine",
                                   _kitchen_furniture()))
    if need_bathroom:
        zones.append(_virtual_zone("bathroom", "Sanitaires",
                                   _bathroom_furniture()))
    for cap in meeting_caps:
        zones.append(_virtual_zone("meeting_room", f"Salle de réunion {cap}p",
                                   _meeting_table(cap), capacity=cap))

    return zones


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _zone_label(zone_type: str, capacity: int) -> str:
    labels = {
        "kitchen": "Espace déjeuner / Cuisine",
        "bathroom": "Sanitaires",
        "entrance": "Entrée",
        "corridor": "Couloir",
        "storage": "Rangement",
    }
    return labels.get(zone_type, zone_type.replace("_", " ").title())


def _furniture_for_type(zone_type: str, capacity: int) -> list[FurnitureItem]:
    if zone_type == "kitchen":
        return _kitchen_furniture()
    if zone_type == "bathroom":
        return _bathroom_furniture()
    return []


def _virtual_zone(zone_type: str, label: str, furniture: list[FurnitureItem],
                  capacity: int = 0) -> Zone:
    """Zone without a real room_id — renderer will skip drawing it."""
    return Zone(
        room_id="__virtual__",
        zone_type=zone_type,
        label=label,
        capacity=capacity,
        furniture=furniture,
        color_key=zone_type,
    )
