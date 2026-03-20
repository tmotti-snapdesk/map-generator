"""
FastAPI entry point for Vercel serverless deployment.
All /api/* routes are handled here.
"""

import base64
import os
import sys

# Ensure sibling modules are importable
sys.path.insert(0, os.path.dirname(__file__))

import anthropic
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from layout_engine import compute_scenarios
from pdf_parser import parse_floor_plan
from renderer import render_floor_plan

app = FastAPI(title="Floor Plan Generator", version="2.0.0")

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
    area_m2: float = Form(..., description="Total surface area in m²"),
):
    if area_m2 < 10 or area_m2 > 10000:
        raise HTTPException(status_code=422, detail="area_m2 must be between 10 and 10000")

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
        scenarios = compute_scenarios(floor_plan, area_m2)
    except Exception as e:
        raise HTTPException(status_code=500,
                            detail=f"Layout computation failed: {e}")

    results = []
    for scenario in scenarios:
        try:
            png_bytes = render_floor_plan(
                floor_plan,
                scenario["zones"],
                scenario["n_people"],
                title=f"{scenario['label']} — {scenario['n_people']} postes",
            )
        except Exception as e:
            raise HTTPException(status_code=500,
                                detail=f"Rendering failed for scenario '{scenario['label']}': {e}")

        results.append({
            "label": scenario["label"],
            "density": scenario["density"],
            "n_people": scenario["n_people"],
            "image": base64.b64encode(png_bytes).decode("utf-8"),
        })

    return JSONResponse({"scenarios": results})


@app.post("/api/generate/json")
async def generate_json(
    file: UploadFile = File(...),
    area_m2: float = Form(...),
):
    """Debug endpoint — returns parsed floor plan + scenario data (no images)."""
    pdf_bytes = await file.read()
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not configured")

    client = anthropic.Anthropic(api_key=api_key)
    floor_plan = parse_floor_plan(pdf_bytes, client)
    scenarios = compute_scenarios(floor_plan, area_m2)

    return JSONResponse({
        "floor_plan": floor_plan,
        "scenarios": [
            {
                "label": s["label"],
                "density": s["density"],
                "n_people": s["n_people"],
                "zones": [
                    {
                        "room_id": z.room_id,
                        "zone_type": z.zone_type,
                        "label": z.label,
                        "capacity": z.capacity,
                        "furniture_count": len(z.furniture),
                    }
                    for z in s["zones"]
                ],
            }
            for s in scenarios
        ],
    })
