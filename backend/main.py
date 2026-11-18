"""API del proyecto Margen de Decisión del QB (NFL Big Data Bowl, UNAM).

Ejecuta (desde la raíz del proyecto):  .venv\\Scripts\\uvicorn backend.main:app --reload
Documentación interactiva: /docs

Las métricas se calculan una vez al arrancar, en segundo plano (≈30-60 s), a partir de data/
(solo lectura). Mientras tanto /health responde y los endpoints /api/... devuelven 503.
La lógica vive en backend/service.py; aquí solo están las rutas HTTP.
"""
from contextlib import asynccontextmanager
from pathlib import Path as Path_
from typing import Literal, Optional

from fastapi.staticfiles import StaticFiles

from fastapi import Depends, FastAPI, HTTPException, Path, Query
from pydantic import BaseModel

from backend import service as sv

MarginCategory = Literal["pressure_before_throw", "simultaneous_pressure_and_throw", "pressure_after_throw",
                         "pressure_not_observed_censored", "not_applicable_no_throw", "not_applicable_no_snap",
                         "not_applicable_no_qb_or_rushers", "not_applicable_throw_before_snap"]
Outcome = Literal["completion", "incompletion", "interception", "sack", "scramble"]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    sv.STORE.start()  # hilo en segundo plano; no bloquea el arranque
    yield


app = FastAPI(
    title="Margen de Decisión del QB",
    description=("API de análisis del margen de decisión del quarterback. " + sv.METHOD_NOTE),
    version="1.0.0",
    lifespan=lifespan,
)


class Health(BaseModel):
    status: str


class Status(BaseModel):
    state: str
    started_at: Optional[str] = None
    load_seconds: Optional[float] = None
    error: Optional[str] = None
    plays: Optional[int] = None


def ready_store() -> sv.DataStore:
    s = sv.STORE
    if s.state != "ready":
        raise HTTPException(status_code=503, detail={"state": s.state, "error": s.error,
                                                     "mensaje": "Las métricas se están calculando; reintenta."})
    return s


@app.get("/health", response_model=Health, tags=["sistema"])
def health() -> dict:
    """Estado del servidor. Responde aunque las métricas sigan cargando."""
    return {"status": "ok"}


@app.get("/api/status", response_model=Status, tags=["sistema"])
def status() -> dict:
    """Estado de la carga de métricas: idle, loading, ready o error."""
    return sv.STORE.status()


@app.get("/api/summary", tags=["resumen"])
def summary(s: sv.DataStore = Depends(ready_store)) -> dict:
    """Totales por categoría de margen (con porcentaje sobre todas las jugadas), estadísticos del margen
    exacto (excluye censuradas) y del tiempo hasta la presión."""
    return s.summary()


@app.get("/api/quarterbacks", tags=["quarterbacks"])
def quarterbacks(
    min_exact_margins: int = Query(sv.MIN_EXACT_MARGINS_QB, ge=1, le=1000,
                                   description="Márgenes exactos mínimos para reportar mediana/media y ordenar."),
    sort_by: Literal["jugadas", "margenes_exactos", "mediana", "media", "nombre"] = Query("jugadas"),
    include_insufficient: bool = Query(True, description="Incluir QBs con muestra insuficiente (sin estadísticos)."),
    s: sv.DataStore = Depends(ready_store),
) -> dict:
    """QBs con conteos por categoría y márgenes exactos. Sin ranking para muestras pequeñas."""
    return s.quarterbacks(min_exact_margins, sort_by, include_insufficient)


@app.get("/api/quarterbacks/{nfl_id}", tags=["quarterbacks"])
def quarterback_detail(
    nfl_id: int = Path(..., description="nflId del QB"),
    min_exact_margins: int = Query(sv.MIN_EXACT_MARGINS_GROUP, ge=1, le=1000,
                                   description="Márgenes exactos mínimos para reportar mediana/media por subgrupo."),
    s: sv.DataStore = Depends(ready_store),
) -> dict:
    """Estadísticas de un QB y desgloses por formación, cobertura, down, distancia y resultado."""
    d = s.quarterback_detail(nfl_id, min_exact_margins)
    if d is None:
        raise HTTPException(status_code=404, detail=f"No hay jugadas con QB nflId={nfl_id}")
    return d


@app.get("/api/defenders", tags=["defensores"])
def defenders(
    min_rush_snaps: int = Query(sv.MIN_RUSH_SNAPS_DEFENDER, ge=1, le=5000,
                                description="Jugadas mínimas como pass rusher para reportar tiempos y ordenar."),
    sort_by: Literal["presiones", "jugadas", "tasa", "mediana", "pff_sacks", "pff_hurries", "pff_hits",
                     "nombre"] = Query("presiones"),
    include_insufficient: bool = Query(True),
    s: sv.DataStore = Depends(ready_store),
) -> dict:
    """Pass rushers: presión detectada por tracking (definición propia) y etiquetas PFF por separado."""
    return s.defenders(min_rush_snaps, sort_by, include_insufficient)


@app.get("/api/plays", tags=["jugadas"])
def plays(
    qb_id: Optional[int] = Query(None, description="nflId del QB"),
    defender_id: Optional[int] = Query(None, description="nflId de un pass rusher que participó en la jugada"),
    formation: Optional[str] = Query(None, description="offenseFormation (ver /api/filters)"),
    coverage: Optional[str] = Query(None, description="pff_passCoverage (ver /api/filters)"),
    down: Optional[int] = Query(None, ge=0, le=4,
                                description="Down 1-4. El dataset trae 35 jugadas con down = 0 (se conservan)."),
    margin_category: Optional[MarginCategory] = Query(None),
    outcome: Optional[Outcome] = Query(None),
    game_id: Optional[int] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    s: sv.DataStore = Depends(ready_store),
) -> dict:
    """Jugadas filtradas (paginadas), con conteos por categoría del subconjunto completo."""
    return s.filter_plays(qb_id, defender_id, formation, coverage, down, margin_category, outcome,
                          game_id, limit, offset)


@app.get("/api/plays/{game_id}/{play_id}", tags=["jugadas"])
def play_detail(game_id: int, play_id: int, s: sv.DataStore = Depends(ready_store)) -> dict:
    """Detalle de una jugada, con eventos usados, presión, margen y cada pass rusher."""
    d = s.play_detail(game_id, play_id)
    if d is None:
        raise HTTPException(status_code=404, detail=f"No existe la jugada {game_id}/{play_id}")
    return d


@app.get("/api/breakdowns", tags=["resumen"])
def breakdowns(
    min_exact_margins: int = Query(sv.MIN_EXACT_MARGINS_GROUP, ge=1, le=1000),
    s: sv.DataStore = Depends(ready_store),
) -> dict:
    """Márgenes por formación, cobertura y formación x cobertura, con tamaño de muestra."""
    return s.breakdowns(min_exact_margins)


@app.get("/api/filters", tags=["filtros"])
def filters(s: sv.DataStore = Depends(ready_store)) -> dict:
    """Opciones disponibles (con número de jugadas) para los filtros de la interfaz."""
    return s.filters()


# Dashboard compilado (dashboard/dist). Se monta al final para no interferir con /api, /health ni /docs.
# Si no existe (desarrollo), la API arranca igual.
_DIST = Path_(__file__).resolve().parent.parent / "dashboard" / "dist"
if (_DIST / "index.html").is_file():
    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="dashboard")
