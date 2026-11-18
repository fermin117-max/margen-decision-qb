"""Capa de servicio: carga una vez las métricas validadas y responde consultas en memoria.

- Reutiliza `metrics.build_metrics()` (eventos, presión v2, censura). No recalcula nada propio.
- El tracking se procesa juego por juego dentro de build_metrics; aquí solo se guardan las tablas
  resultantes (≈8.5 mil jugadas y ≈36 mil filas rusher-jugada).
- Carga en un hilo al arrancar la app: /health responde de inmediato aunque el cálculo siga.
- No escribe en disco. No depende de FastAPI.
"""
from __future__ import annotations

import math
import threading
import time
from datetime import datetime, timezone
from typing import Any, Iterable

import numpy as np
import pandas as pd

from backend import data_access as da
from backend import metrics as mt
from backend import pressure as pr

KEYS = da.KEYS_PLAY
FPS = pr.DEFAULT.fps

# Umbrales de tamaño de muestra (convención de presentación, ajustables por parámetro).
MIN_EXACT_MARGINS_QB = 30       # márgenes exactos mínimos para ordenar/comparar QBs
MIN_RUSH_SNAPS_DEFENDER = 50    # jugadas como pass rusher mínimas para ordenar defensores
MIN_EXACT_MARGINS_GROUP = 10    # márgenes exactos mínimos para reportar mediana en un desglose

MARGIN_CATEGORIES = {
    "pressure_before_throw": "Presión detectada antes del lanzamiento (margen exacto < 0).",
    "simultaneous_pressure_and_throw": "Presión y lanzamiento en el mismo frame (margen exacto = 0).",
    "pressure_after_throw": ("Presión detectada después del lanzamiento y antes del fin del tracking "
                             "(margen exacto > 0, limitado a ~0.4 s por el tracking disponible)."),
    "pressure_not_observed_censored": ("No se detectó presión antes del fin del tracking. Dato censurado: "
                                       "NO significa ausencia de presión; solo se conoce una cota inferior."),
    "not_applicable_no_throw": "Sin evento de lanzamiento (sacks, scrambles y otros). Sin margen.",
    "not_applicable_no_snap": "Sin evento de snap válido. Sin tiempos relativos al snap.",
    "not_applicable_no_qb_or_rushers": "Sin QB único o sin pass rushers identificados.",
    "not_applicable_throw_before_snap": "Lanzamiento antes del snap (inconsistencia).",
}
EXACT = list(mt.MARGIN_EXACT)
CENSORED = mt.MARGIN_CENSORED

OUTCOME_LABELS = {"completion": "Pase completo", "incompletion": "Pase incompleto",
                  "interception": "Intercepción", "sack": "Sack (passResult = S)",
                  "scramble": "Scramble (passResult = R)"}

YTG_BINS = [(1, 3, "1-3"), (4, 6, "4-6"), (7, 10, "7-10"), (11, 99, "11+")]

METHOD_NOTE = ("Presión = definición operacional propia del equipo (rusher a <= 2.0 yd del QB durante "
               "2 frames consecutivos, entrada posterior al snap), no oficial de la NFL. Las jugadas "
               "censuradas no entran en medias ni medianas de márgenes exactos. Las asociaciones "
               "no implican causalidad.")


# ---------------------------------------------------------------- utilidades
def py(v: Any) -> Any:
    """Convierte valores numpy/pandas a tipos JSON nativos; NaN/NA -> None."""
    if v is None or v is pd.NA or v is pd.NaT:
        return None
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        f = float(v)
        return None if math.isnan(f) else round(f, 4)
    if isinstance(v, pd.Timestamp):
        return v.isoformat()
    return v


def records(df: pd.DataFrame) -> list[dict]:
    cols = list(df.columns)
    return [{c: py(v) for c, v in zip(cols, row)} for row in df.itertuples(index=False, name=None)]


def stat(s: pd.Series) -> dict:
    s = pd.to_numeric(s, errors="coerce").dropna()
    if s.empty:
        return {"n": 0, "mediana": None, "media": None, "min": None, "max": None}
    return {"n": int(len(s)), "mediana": py(s.median()), "media": py(s.mean()),
            "min": py(s.min()), "max": py(s.max())}


def pct(n: int, total: int) -> float | None:
    return None if total == 0 else round(100.0 * n / total, 2)


def ytg_bucket(v: Any) -> str | None:
    if pd.isna(v):
        return None
    for lo, hi, lab in YTG_BINS:
        if lo <= int(v) <= hi:
            return lab
    return None


def category_counts(g: pd.DataFrame) -> dict:
    vc = g["margin_category"].value_counts()
    return {c: int(vc.get(c, 0)) for c in MARGIN_CATEGORIES}


def margin_block(g: pd.DataFrame, min_exact: int) -> dict:
    """Estadísticos de márgenes de un grupo. Solo márgenes exactos en media/mediana."""
    ex = g.loc[g["margin_is_exact"], "decision_margin_s"]
    cen = g.loc[g["margin_category"] == CENSORED]
    counts = category_counts(g)
    eligible = sum(counts[c] for c in EXACT) + counts[CENSORED]
    st = stat(ex)
    enough = st["n"] >= min_exact
    return {
        "jugadas": int(len(g)),
        "categorias": counts,
        "margenes_exactos": st["n"],
        "jugadas_censuradas": counts[CENSORED],
        "pct_censuradas_sobre_elegibles": pct(counts[CENSORED], eligible),
        "margen_exacto_mediana_s": st["mediana"] if enough else None,
        "margen_exacto_media_s": st["media"] if enough else None,
        "cota_inferior_censuradas_mediana_s": stat(cen["observed_margin_lower_bound_s"])["mediana"],
        "muestra_suficiente": enough,
    }


# ---------------------------------------------------------------- almacén
class DataStore:
    """Tablas en memoria calculadas una sola vez."""

    def __init__(self) -> None:
        self.state = "idle"
        self.error: str | None = None
        self.started_at: str | None = None
        self.seconds: float | None = None
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.plays: pd.DataFrame | None = None
        self.rush: pd.DataFrame | None = None
        self.names: dict[int, str] = {}

    # carga ------------------------------------------------------------
    def start(self) -> None:
        with self._lock:
            if self.state in ("loading", "ready"):
                return
            self.state = "loading"
            self.started_at = datetime.now(timezone.utc).isoformat()
            self._thread = threading.Thread(target=self._load, name="metrics-loader", daemon=True)
            self._thread.start()

    def wait(self, timeout: float | None = None) -> bool:
        if self._thread is not None:
            self._thread.join(timeout)
        return self.state == "ready"

    def _load(self) -> None:
        t0 = time.time()
        try:
            plays, rush, names = build_tables()
            self.plays, self.rush, self.names = plays, rush, names
            self.seconds = round(time.time() - t0, 1)
            self.state = "ready"
        except Exception as e:  # se reporta en /api/status
            self.error = f"{type(e).__name__}: {e}"
            self.state = "error"

    def status(self) -> dict:
        return {"state": self.state, "started_at": self.started_at, "load_seconds": self.seconds,
                "error": self.error,
                "plays": None if self.plays is None else int(len(self.plays))}

    # consultas ---------------------------------------------------------
    def summary(self) -> dict:
        t = self.plays
        n = len(t)
        counts = category_counts(t)
        ex = t.loc[t["margin_is_exact"], "decision_margin_s"]
        pres = t.loc[t["pressure_status"] == "pressure_observed", "pressure_time_s"]
        cen = t.loc[t["margin_category"] == CENSORED]
        cats = [{"categoria": c, "descripcion": d, "jugadas": counts[c], "porcentaje": pct(counts[c], n)}
                for c, d in MARGIN_CATEGORIES.items()]
        pstat = t["pressure_status"].value_counts()
        return {
            "total_jugadas": n,
            "presion_antes_del_lanzamiento": counts["pressure_before_throw"],
            "presion_despues_del_lanzamiento": counts["pressure_after_throw"],
            "simultaneas": counts["simultaneous_pressure_and_throw"],
            "censuradas": counts[CENSORED],
            "sin_lanzamiento": counts["not_applicable_no_throw"],
            "sin_snap": counts["not_applicable_no_snap"],
            "sin_pass_rushers": int((t["n_rushers_pff"] == 0).sum()),
            "categorias": cats,
            "suma_categorias": int(sum(counts.values())),
            "margen_exacto": {**stat(ex), "excluye_censuradas": True,
                              "nota": "Margen positivo exacto limitado por el tracking posterior al lanzamiento."},
            "tiempo_hasta_presion_s": stat(pres),
            "censuradas_cota_inferior_s": stat(cen["observed_margin_lower_bound_s"]),
            "tracking_tras_lanzamiento_s": stat(t["observed_after_throw_s"]),
            "estado_presion": {str(k): int(v) for k, v in pstat.items()},
            "proximidad_en_snap": int(t["preexisting_proximity_at_snap"].sum()),
            "histograma_margen_exacto": self.margin_histogram(),
            "nota_metodologica": METHOD_NOTE,
        }

    def margin_histogram(self) -> list[dict]:
        """Conteo de márgenes exactos por valor (resolución 0.1 s = 1 frame). Márgenes < -3 s se agrupan."""
        t = self.plays[self.plays["margin_is_exact"]]
        f = t["decision_margin_frames"].astype("int64").clip(lower=-30)
        vc = f.value_counts().sort_index()
        return [{"margen_s": round(int(k) / FPS, 1), "agrupado_menor_igual": int(k) == -30,
                 "jugadas": int(v)} for k, v in vc.items()]

    def breakdowns(self, min_exact: int = MIN_EXACT_MARGINS_GROUP) -> dict:
        """Márgenes por formación, cobertura y combinación formación x cobertura (asociación, no causalidad)."""
        t = self.plays
        def by(cols: list[str]) -> list[dict]:
            out = []
            for k, g in t.groupby(cols, dropna=True):
                k = k if isinstance(k, tuple) else (k,)
                out.append({**{c: py(v) for c, v in zip(cols, k)}, **margin_block(g, min_exact)})
            return sorted(out, key=lambda r: -r["jugadas"])
        return {"min_margenes_exactos": min_exact,
                "formacion": by(["offenseFormation"]), "cobertura": by(["pff_passCoverage"]),
                "formacion_cobertura": by(["offenseFormation", "pff_passCoverage"]),
                "nota": "Asociaciones descriptivas; no implican causalidad. " + METHOD_NOTE}

    def quarterbacks(self, min_exact: int = MIN_EXACT_MARGINS_QB, sort_by: str = "jugadas",
                     include_insufficient: bool = True) -> dict:
        t = self.plays[self.plays["qb_nflId"].notna()]
        rows = []
        for qid, g in t.groupby("qb_nflId"):
            b = margin_block(g, min_exact)
            rows.append({"nfl_id": int(qid), "nombre": self.names.get(int(qid)),
                         "equipos": sorted(g["possessionTeam"].dropna().unique().tolist()),
                         "jugadas_analizadas": b["jugadas"],
                         "margenes_exactos": b["margenes_exactos"],
                         "presion_antes_del_lanzamiento": b["categorias"]["pressure_before_throw"],
                         "presion_despues_del_lanzamiento": b["categorias"]["pressure_after_throw"],
                         "simultaneas": b["categorias"]["simultaneous_pressure_and_throw"],
                         "censuradas": b["jugadas_censuradas"],
                         "sin_lanzamiento": b["categorias"]["not_applicable_no_throw"],
                         "pct_censuradas_sobre_elegibles": b["pct_censuradas_sobre_elegibles"],
                         "margen_exacto_mediana_s": b["margen_exacto_mediana_s"],
                         "margen_exacto_media_s": b["margen_exacto_media_s"],
                         "tiempo_lanzamiento_mediana_s": stat(g["throw_time_s"])["mediana"],
                         "muestra_suficiente": b["muestra_suficiente"]})
        rows = _sort(rows, sort_by, {"jugadas": "jugadas_analizadas", "margenes_exactos": "margenes_exactos",
                                     "mediana": "margen_exacto_mediana_s", "media": "margen_exacto_media_s",
                                     "nombre": "nombre"})
        if not include_insufficient:
            rows = [r for r in rows if r["muestra_suficiente"]]
        return {"min_margenes_exactos": min_exact, "orden": sort_by,
                "total_quarterbacks": len(rows),
                "con_muestra_suficiente": sum(r["muestra_suficiente"] for r in rows),
                "nota": ("Mediana/media solo con muestra suficiente. Al ordenar por estadístico, los QBs con "
                         "muestra insuficiente van al final y sin valor. Las medianas excluyen jugadas "
                         "censuradas, que suelen ser lanzamientos rápidos sin presión observada: compárese "
                         "junto con pct_censuradas_sobre_elegibles. " + METHOD_NOTE),
                "quarterbacks": rows}

    def quarterback_detail(self, nfl_id: int, min_exact: int = MIN_EXACT_MARGINS_GROUP) -> dict | None:
        g = self.plays[self.plays["qb_nflId"] == nfl_id]
        if g.empty:
            return None
        def by(col: str) -> list[dict]:
            out = []
            for k, sub in g.groupby(col, dropna=False):
                out.append({"valor": py(k), **margin_block(sub, min_exact)})
            return sorted(out, key=lambda r: -r["jugadas"])
        b = margin_block(g, MIN_EXACT_MARGINS_QB)
        return {"nfl_id": int(nfl_id), "nombre": self.names.get(int(nfl_id)),
                "equipos": sorted(g["possessionTeam"].dropna().unique().tolist()),
                "resumen": {**b, "tiempo_lanzamiento_s": stat(g["throw_time_s"]),
                            "tiempo_hasta_presion_s": stat(g.loc[g["pressure_status"] == "pressure_observed",
                                                                 "pressure_time_s"]),
                            "min_margenes_exactos": MIN_EXACT_MARGINS_QB},
                "min_margenes_exactos_desglose": min_exact,
                "desgloses": {"formacion": by("offenseFormation"), "cobertura": by("pff_passCoverage"),
                              "down": by("down"), "distancia_por_avanzar": by("ytg_bucket"),
                              "resultado": by("outcome")},
                "nota": METHOD_NOTE}

    def defenders(self, min_rush: int = MIN_RUSH_SNAPS_DEFENDER, sort_by: str = "presiones",
                  include_insufficient: bool = True) -> dict:
        r = self.rush
        rows = []
        for did, g in r.groupby("nflId"):
            elig = g[g["play_eligible"]]
            arr = elig[elig["arrived"]]
            st = stat(arr["arrival_time_s"])
            enough = len(elig) >= min_rush
            rows.append({"nfl_id": int(did), "nombre": self.names.get(int(did)),
                         "posicion_oficial": g["officialPosition"].iloc[0],
                         "jugadas_como_pass_rusher": int(len(g)),
                         "jugadas_con_snap": int(len(elig)),
                         "presiones_detectadas_tracking": int(len(arr)),
                         "primero_en_llegar": int(elig["first_to_arrive"].sum()),
                         "tasa_presion_tracking": None if len(elig) == 0 else round(len(arr) / len(elig), 4),
                         "tiempo_hasta_presion_mediana_s": st["mediana"] if enough else None,
                         "tiempo_hasta_presion_media_s": st["media"] if enough else None,
                         "proximidad_en_snap": int(elig["within_at_snap"].sum()),
                         "pff_sacks": int(g["pff_sack"].sum()), "pff_hits": int(g["pff_hit"].sum()),
                         "pff_hurries": int(g["pff_hurry"].sum()),
                         "muestra_suficiente": enough})
        rows = _sort(rows, sort_by, {"presiones": "presiones_detectadas_tracking",
                                     "jugadas": "jugadas_como_pass_rusher",
                                     "tasa": "tasa_presion_tracking",
                                     "mediana": "tiempo_hasta_presion_mediana_s",
                                     "pff_sacks": "pff_sacks", "pff_hurries": "pff_hurries",
                                     "pff_hits": "pff_hits", "nombre": "nombre"},
                     ascending={"mediana", "nombre"})
        if not include_insufficient:
            rows = [x for x in rows if x["muestra_suficiente"]]
        return {"min_jugadas_como_pass_rusher": min_rush, "orden": sort_by,
                "total_defensores": len(rows),
                "con_muestra_suficiente": sum(x["muestra_suficiente"] for x in rows),
                "nota": ("Solo jugadores con pff_role = 'Pass Rush' en la jugada (no se atribuyen "
                         "intercepciones). presiones_detectadas_tracking usa la definición operacional; "
                         "pff_sacks / pff_hits / pff_hurries son etiquetas de PFF y se cuentan por separado. "
                         "El tiempo hasta la presión solo existe cuando el defensor llegó (no incluye "
                         "jugadas sin llegada). " + METHOD_NOTE),
                "defensores": rows}

    def filter_plays(self, qb_id: int | None = None, defender_id: int | None = None,
                     formation: str | None = None, coverage: str | None = None, down: int | None = None,
                     margin_category: str | None = None, outcome: str | None = None,
                     game_id: int | None = None, limit: int = 100, offset: int = 0) -> dict:
        t = self.plays
        m = pd.Series(True, index=t.index)
        if qb_id is not None:
            m &= t["qb_nflId"] == qb_id
        if defender_id is not None:
            keys = self.rush.loc[self.rush["nflId"] == defender_id, KEYS]
            idx = pd.MultiIndex.from_frame(keys)
            m &= pd.MultiIndex.from_frame(t[KEYS]).isin(idx)
        if formation is not None:
            m &= t["offenseFormation"] == formation
        if coverage is not None:
            m &= t["pff_passCoverage"] == coverage
        if down is not None:
            m &= t["down"] == down
        if margin_category is not None:
            m &= t["margin_category"] == margin_category
        if outcome is not None:
            m &= t["outcome"] == outcome
        if game_id is not None:
            m &= t["gameId"] == game_id
        sel = t[m].sort_values(KEYS)
        page = sel.iloc[offset: offset + limit]
        items = [self._play_item(r) for r in records(page[PLAY_COLS])]
        if defender_id is not None:
            rr = self.rush[self.rush["nflId"] == defender_id].set_index(KEYS)
            for it in items:
                k = (it["gameId"], it["playId"])
                it["defensor_filtrado"] = {"nfl_id": defender_id,
                                           "llego": bool(rr.at[k, "arrived"]) if k in rr.index else None,
                                           "primero_en_llegar": bool(rr.at[k, "first_to_arrive"]) if k in rr.index else None}
        ex = sel.loc[sel["margin_is_exact"], "decision_margin_s"]
        return {"total": int(len(sel)), "limit": limit, "offset": offset, "devueltas": len(items),
                "categorias": category_counts(sel), "margen_exacto": stat(ex),
                "jugadas": items}

    def play_detail(self, game_id: int, play_id: int) -> dict | None:
        t = self.plays
        row = t[(t["gameId"] == game_id) & (t["playId"] == play_id)]
        if row.empty:
            return None
        item = self._play_item(records(row[PLAY_DETAIL_COLS])[0])
        rr = self.rush[(self.rush["gameId"] == game_id) & (self.rush["playId"] == play_id)]
        rushers = records(rr[["nflId", "pff_positionLinedUp", "officialPosition", "within_at_snap", "arrived",
                              "arrival_frame", "arrival_time_s", "dist_at_arrival_yd", "first_to_arrive",
                              "pff_hit", "pff_hurry", "pff_sack"]])
        for x in rushers:
            x["nombre"] = self.names.get(x["nflId"])
        item["pass_rushers"] = rushers
        item["nota"] = METHOD_NOTE
        return item

    def filters(self) -> dict:
        t, r = self.plays, self.rush
        qb = t.groupby("qb_nflId").size()
        de = r.groupby("nflId").size()
        def opts(col: str) -> list[dict]:
            vc = t[col].value_counts(dropna=True)
            return [{"valor": py(k), "jugadas": int(v)} for k, v in sorted(vc.items(), key=lambda kv: str(kv[0]))]
        return {
            "quarterbacks": sorted([{"nfl_id": int(k), "nombre": self.names.get(int(k)), "jugadas": int(v)}
                                    for k, v in qb.items()], key=lambda x: x["nombre"] or ""),
            "defensores": sorted([{"nfl_id": int(k), "nombre": self.names.get(int(k)), "jugadas_como_pass_rusher": int(v)}
                                  for k, v in de.items()], key=lambda x: x["nombre"] or ""),
            "formaciones": opts("offenseFormation"),
            "coberturas": opts("pff_passCoverage"),
            "downs": opts("down"),
            "distancias_por_avanzar": [{"valor": lab, "jugadas": int((t["ytg_bucket"] == lab).sum())}
                                       for _, _, lab in YTG_BINS],
            "resultados": [{"valor": k, "descripcion": OUTCOME_LABELS.get(k), "jugadas": int((t["outcome"] == k).sum())}
                           for k in OUTCOME_LABELS],
            "categorias_margen": [{"valor": k, "descripcion": d, "jugadas": int((t["margin_category"] == k).sum())}
                                  for k, d in MARGIN_CATEGORIES.items()],
        }

    def _play_item(self, r: dict) -> dict:
        r["qb_nombre"] = self.names.get(r.get("qb_nflId")) if r.get("qb_nflId") is not None else None
        ids = [int(x) for x in str(r.get("pressure_defenders") or "").split(";") if x]
        r["pressure_defenders"] = [{"nfl_id": i, "nombre": self.names.get(i)} for i in ids]
        flags = r.get("review_flags") or ""
        r["review_flags"] = [f for f in flags.split(";") if f]
        return r


PLAY_COLS = ["gameId", "playId", "qb_nflId", "possessionTeam", "defensiveTeam", "quarter", "down", "yardsToGo",
             "ytg_bucket", "offenseFormation", "pff_passCoverage", "pff_passCoverageType", "dropBackType",
             "passResult", "outcome", "snap_frame", "snap_event", "throw_frame", "throw_event", "last_frame",
             "throw_time_s", "pressure_status", "pressure_frame", "pressure_time_s", "pressure_defenders",
             "pressure_tie", "margin_category", "margin_is_exact", "decision_margin_s",
             "observed_margin_lower_bound_s", "observed_after_throw_s", "preexisting_proximity_at_snap",
             "pressure_by_reentry", "pff_hit", "pff_hurry", "pff_sack", "review_flags"]
PLAY_DETAIL_COLS = PLAY_COLS + ["playDescription", "snap_source", "throw_source", "snap_time", "throw_time",
                                "n_rushers_pff", "n_rushers_within_at_snap", "min_rusher_dist_postsnap_yd",
                                "sack_event_frame", "no_throw_reason", "personnelO", "defendersInBox",
                                "pff_playAction"]


def _sort(rows: list[dict], sort_by: str, keymap: dict[str, str], ascending: Iterable[str] = ("nombre",)) -> list[dict]:
    """Orden con muestras insuficientes al final cuando se ordena por un estadístico."""
    if sort_by not in keymap:
        raise ValueError(f"sort_by debe ser uno de {sorted(keymap)}")
    k = keymap[sort_by]
    asc = sort_by in set(ascending)
    stat_sort = sort_by not in ("jugadas", "nombre", "margenes_exactos")
    def key(r: dict):
        v = r.get(k)
        if sort_by == "nombre":
            return (False, v is None, 0.0, v or "")
        num = 0.0 if v is None else float(v)
        return ((not r["muestra_suficiente"]) if stat_sort else False, v is None, num if asc else -num, "")
    return sorted(rows, key=key)


# ---------------------------------------------------------------- construcción
def build_tables() -> tuple[pd.DataFrame, pd.DataFrame, dict[int, str]]:
    """Tablas para la API a partir de las métricas validadas (sin recalcular la lógica)."""
    t, by_def = mt.build_metrics()
    plays_csv = da.load_plays()
    extra = plays_csv[KEYS + ["offenseFormation", "pff_passCoverage", "pff_passCoverageType", "personnelO",
                              "defendersInBox", "pff_playAction"]]
    t = t.merge(extra, on=KEYS, how="left", validate="one_to_one")
    t["ytg_bucket"] = t["yardsToGo"].map(ytg_bucket)
    t["down"] = t["down"].astype("int64")

    players = da.load_players()
    names = dict(zip(players["nflId"].astype(int), players["displayName"]))
    pos = dict(zip(players["nflId"].astype(int), players["officialPosition"]))

    pff = da.load_pff()
    rush = pff.loc[pff["pff_role"] == pr.DEFAULT.rusher_role,
                   KEYS + ["nflId", "pff_positionLinedUp", "pff_hit", "pff_hurry", "pff_sack"]].copy()
    for c in ("pff_hit", "pff_hurry", "pff_sack"):
        rush[c] = rush[c].fillna(0).astype(int)
    rush["nflId"] = rush["nflId"].astype("int64")
    bd = by_def.copy()
    bd["nflId"] = bd["nflId"].astype("int64")
    rush = rush.merge(bd[KEYS + ["nflId", "arrival_frame", "dist_at_arrival_yd", "within_at_snap", "arrived"]],
                      on=KEYS + ["nflId"], how="left", validate="one_to_one")
    rush["arrived"] = rush["arrived"].astype("boolean").fillna(False).astype(bool)
    rush["within_at_snap"] = rush["within_at_snap"].astype("boolean").fillna(False).astype(bool)
    rush = rush.merge(t[KEYS + ["snap_frame", "snap_status", "pressure_defenders"]], on=KEYS, how="left")
    rush["play_eligible"] = rush["snap_status"] == "ok"
    rush["arrival_time_s"] = (rush["arrival_frame"].astype("float64") - rush["snap_frame"].astype("float64")) / FPS
    rush["first_to_arrive"] = [str(i) in str(p or "").split(";") for i, p in zip(rush["nflId"], rush["pressure_defenders"])]
    rush["officialPosition"] = rush["nflId"].map(pos)
    rush = rush.drop(columns=["pressure_defenders", "snap_status"])
    return t, rush, names


STORE = DataStore()
