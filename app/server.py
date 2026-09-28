"""CellForge lab — FastAPI backend.

Bind 0.0.0.0.  The browser talks to relative /api/* URLs so the live
preview proxy works (never hard-code localhost in the frontend).
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dic_mlopt import config as C  # noqa: E402
from dic_mlopt.service import (  # noqa: E402
    characterize_point,
    fo4_ps,
    industry_map,
    iv_curves,
    load_library,
    load_metrics,
    load_sta,
    product_manifest,
    subthreshold,
    sweep,
)

WEB = Path(__file__).resolve().parent / "web"

app = FastAPI(
    title="CellForge",
    description="PVT-robust standard-cell characterization, ML sizing, Liberty and STA.",
    version="2.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class CharIn(BaseModel):
    cell: str = "INV"
    wn_um: float = Field(0.84, ge=0.2, le=8.0)
    wp_um: float = Field(1.68, ge=0.2, le=8.0)
    l_um: float = Field(0.15, ge=0.10, le=0.40)
    vdd: float = Field(1.8, ge=1.2, le=2.2)
    temp_c: float = Field(25.0, ge=-55.0, le=150.0)
    cload_ff: float = Field(8.0, ge=0.4, le=80.0)
    slew_ps: float = Field(30.0, ge=1.0, le=400.0)
    corner: str = "tt"


@app.get("/api/health")
def health():
    return {"ok": True, "product": "CellForge"}


@app.get("/api/manifest")
def manifest():
    return product_manifest()


@app.get("/api/industry")
def industry():
    return industry_map()


@app.get("/api/metrics")
def metrics():
    return load_metrics()


@app.get("/api/library")
def library():
    return {"rows": load_library()}


@app.get("/api/sta")
def sta():
    return {"rows": load_sta()}


@app.get("/api/fo4")
def fo4(vdd: float = 1.8, temp_c: float = 25.0, corner: str = "tt"):
    try:
        return {"fo4_ps": fo4_ps(vdd, temp_c, corner), "vdd": vdd, "temp_c": temp_c, "corner": corner}
    except KeyError as e:
        raise HTTPException(400, str(e)) from e


@app.post("/api/characterize")
def characterize(body: CharIn):
    try:
        return characterize_point(**body.model_dump())
    except KeyError as e:
        raise HTTPException(400, str(e)) from e


@app.get("/api/sweep")
def api_sweep(
    cell: str = "INV",
    axis: str = "vdd",
    wn_um: float = 0.84,
    wp_um: float = 1.68,
    corner: str = "tt",
    n: int = Query(28, ge=8, le=80),
):
    try:
        return sweep(cell=cell, axis=axis, wn_um=wn_um, wp_um=wp_um, corner=corner, n=n)
    except KeyError as e:
        raise HTTPException(400, str(e)) from e


@app.get("/api/iv")
def api_iv(device: str = "nmos", temp_c: float = 25.0):
    if device not in ("nmos", "pmos"):
        raise HTTPException(400, "device must be nmos or pmos")
    return iv_curves(device, temp_c)


@app.get("/api/subthreshold")
def api_sub(device: str = "nmos"):
    if device not in ("nmos", "pmos"):
        raise HTTPException(400, "device must be nmos or pmos")
    return subthreshold(device)


@app.get("/api/liberty/{corner}")
def liberty_file(corner: str):
    path = C.LIB_DIR / f"dic_mlopt_sky130_{corner}.lib"
    if not path.exists():
        raise HTTPException(404, f"no liberty for corner {corner}")
    return FileResponse(path, media_type="text/plain", filename=path.name)


if C.FIG_DIR.exists():
    app.mount("/figures", StaticFiles(directory=str(C.FIG_DIR)), name="figures")
if C.LIB_DIR.exists():
    app.mount("/liberty", StaticFiles(directory=str(C.LIB_DIR)), name="liberty")

app.mount("/", StaticFiles(directory=str(WEB), html=True), name="web")
