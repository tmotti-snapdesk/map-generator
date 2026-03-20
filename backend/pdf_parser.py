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

Rules:
- Coordinates are normalized: (0,0) = top-left corner of the bounding box of the whole plan
- The outline lists the polygon vertices of the floor plan perimeter (for non-rectangular plans)
- For a simple rectangle, outline = 4 corners
- Estimate real-world dimensions from context clues (scale bar, text annotations, typical room sizes)
- If no scale is visible, estimate based on typical office spaces (standard desk = 1.4x0.7m, door = 0.9m wide)
- Identify ALL distinct enclosed spaces as rooms
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
