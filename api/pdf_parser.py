"""
PDF Parser: converts a scanned PDF floor plan into a structured room layout
using PyMuPDF (image extraction) + Claude Vision API.
"""

import base64
import json
import re
from pathlib import Path

import anthropic
import fitz  # PyMuPDF


def pdf_to_image_base64(pdf_bytes: bytes, page_index: int = 0, dpi: int = 150) -> str:
    """Render a PDF page to a PNG and return it as base64."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc[page_index]
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
    img_bytes = pix.tobytes("png")
    doc.close()
    return base64.standard_b64encode(img_bytes).decode("utf-8")


SYSTEM_PROMPT = """You are an expert architectural floor plan analyzer.
Given a scanned floor plan image, extract the spatial layout as structured JSON.
Be precise about dimensions and proportions relative to the total plan size."""

EXTRACTION_PROMPT = """Analyze this scanned floor plan image and extract the room layout.

Return a JSON object with this exact structure:
{
  "total_width_m": <estimated total width in meters as float>,
  "total_height_m": <estimated total height in meters as float>,
  "outline": [
    {"x": <0.0-1.0 normalized>, "y": <0.0-1.0 normalized>},
    ...
  ],
  "rooms": [
    {
      "id": "room_1",
      "label": "<room name if visible, else 'unknown'>",
      "type": "<one of: openspace|meeting_room|kitchen|bathroom|entrance|corridor|storage|other>",
      "x": <left edge, 0.0-1.0 normalized to image width>,
      "y": <top edge, 0.0-1.0 normalized to image height>,
      "w": <width, 0.0-1.0 normalized>,
      "h": <height, 0.0-1.0 normalized>
    }
  ],
  "doors": [
    {
      "room_id": "<id of room this door belongs to>",
      "wall": "<north|south|east|west>",
      "position": <0.0-1.0 along that wall>
    }
  ],
  "windows": [
    {
      "room_id": "<id of room>",
      "wall": "<north|south|east|west>",
      "position": <0.0-1.0 along that wall>
    }
  ],
  "notes": "<any observations about the floor plan shape, special features, etc.>"
}

CRITICAL RULES:
1. OPEN SPACES: A large open area with no floor-to-ceiling walls dividing it MUST be represented as ONE single room, even if it contains multiple furniture groups or clusters. Do NOT split an openspace into multiple rooms based on furniture placement.
2. WALL DETECTION: Only create a new room when there is an actual solid wall (continuous line) fully enclosing a separate space. Low partitions, glass partitions, or furniture rows do NOT create separate rooms.
3. BUILDING FOOTPRINT: The outline polygon must trace the EXACT exterior perimeter of the building. For non-rectangular buildings (L-shape, T-shape, irregular), list every corner vertex precisely.
4. DIMENSIONS: Use scale bars, text annotations (e.g. "5.89m"), or door widths (standard = 0.90m) to estimate real-world dimensions as accurately as possible.
5. ROOM TYPES: Use "openspace" for any large undivided work area, "meeting_room" only for fully enclosed rooms with a door, "corridor" for circulation zones, "other" for ambiguous spaces.
6. COORDINATES: (0,0) = top-left corner of the plan's bounding box. All x/y/w/h are normalized 0.0–1.0 relative to the plan's bounding box (not the full image).
- Return ONLY the JSON, no explanation"""


def parse_floor_plan(pdf_bytes: bytes, client: anthropic.Anthropic) -> dict:
    """
    Convert a PDF floor plan to a structured room layout dict.
    Returns the parsed JSON or raises on failure.
    """
    img_b64 = pdf_to_image_base64(pdf_bytes)

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": img_b64,
                        },
                    },
                    {"type": "text", "text": EXTRACTION_PROMPT},
                ],
            }
        ],
    )

    raw = message.content[0].text.strip()

    # Strip markdown code fences if present
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    return json.loads(raw)
