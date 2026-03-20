"""
FastAPI entry point for Vercel serverless deployment.
All /api/* routes are handled here.
"""

import os
import sys

# Ensure sibling modules are importable
sys.path.insert(0, os.path.dirname(__file__))

import anthropic
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, JSONResponse

from layout_engine import compute_layout
from pdf_parser import parse_floor_plan
from renderer import render_floor_plan

app = FastAPI(title="Floor Plan Generator", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/generate")
async def generate(
    file: UploadFile = File(..., description="PDF floor plan (scanned)"),
    people: int = Form(..., description="Number of collaborators"),
):
    if people < 1 or people > 500:
        raise HTTPException(status_code=422, detail="people must be between 1 and 500")

    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=422, detail="Only PDF files are accepted")

    pdf_bytes = await file.read()
    if len(pdf_bytes) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 20 MB)")

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not configured")

    client = anthropic.Anthropic(api_key=api_key)

    try:
        floor_plan = parse_floor_plan(pdf_bytes, client)
    except Exception as e:
        raise HTTPException(status_code=422,
                            detail=f"Could not parse floor plan: {e}")

    try:
        zones = compute_layout(floor_plan, people)
    except Exception as e:
        raise HTTPException(status_code=500,
                            detail=f"Layout computation failed: {e}")

    try:
        png_bytes = render_floor_plan(floor_plan, zones, people)
    except Exception as e:
        raise HTTPException(status_code=500,
                            detail=f"Rendering failed: {e}")

    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={
            "Content-Disposition": f'inline; filename="plan_{people}p.png"'
        },
    )


@app.post("/api/generate/json")
async def generate_json(
    file: UploadFile = File(...),
    people: int = Form(...),
):
    """Debug endpoint — returns parsed floor plan JSON."""
    pdf_bytes = await file.read()
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not configured")

    client = anthropic.Anthropic(api_key=api_key)
    floor_plan = parse_floor_plan(pdf_bytes, client)
    zones = compute_layout(floor_plan, people)
    return JSONResponse({
        "floor_plan": floor_plan,
        "zones": [
            {
                "room_id": z.room_id,
                "zone_type": z.zone_type,
                "label": z.label,
                "capacity": z.capacity,
                "furniture_count": len(z.furniture),
            }
            for z in zones
        ],
    })
