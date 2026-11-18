"""Métricas por jugada: tiempo al lanzamiento, tiempo a la presión (definición operacional propia)
y margen de decisión del QB. Funciones puras, sin FastAPI y sin escritura en disco.

decision_margin_s = pressure_time_s - throw_time_s (ambos desde el snap), solo si es exacto.
El tracking termina poco después del lanzamiento: si no se observa presión, el margen está
censurado y solo se conserva observed_margin_lower_bound_s. Ver `margin_category`.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from backend import data_access as da
from backend import play_events as pe
from backend import pressure as pr

KEYS = da.KEYS_PLAY
GAME_COLS = ["gameId", "playId", "nflId", "frameId", "time", "event", "x", "y"]


def pff_play_flags(pff: pd.DataFrame, cfg: pr.PressureConfig = pr.DEFAULT) -> pd.DataFrame:
    """Marcas PFF de los pass rushers por jugada (solo para comparar; NO fijan instantes)."""
    r = pff[pff["pff_role"] == cfg.rusher_role]
    g = r.groupby(KEYS).agg(pff_hit=("pff_hit", "sum"), pff_hurry=("pff_hurry", "sum"),
                            pff_sack=("pff_sack", "sum"))
    g = g.fillna(0).astype(int).reset_index()
    g["pff_pressure_any"] = (g[["pff_hit", "pff_hurry", "pff_sack"]] > 0).any(axis=1)
    return g


def process_game(df: pd.DataFrame, pff_game: pd.DataFrame, qb_game: pd.DataFrame,
                 cfg: pr.PressureConfig = pr.DEFAULT):
    """Eventos + presión de un juego. df debe contener GAME_COLS."""
    ev = pe.play_event_table(df[["gameId", "playId", "frameId", "time", "event"]])
    pres, by_def = pr.pressure_for_game(
        df[["gameId", "playId", "nflId", "frameId", "x", "y"]], pff_game, qb_game,
        ev[KEYS + ["snap_frame"]], cfg)
    return ev, pres, by_def


MARGIN_EXACT = ("pressure_before_throw", "pressure_after_throw", "simultaneous_pressure_and_throw")
MARGIN_CENSORED = "pressure_not_observed_censored"


def _margin_columns(t: pd.DataFrame, fps: float = pr.DEFAULT.fps) -> pd.DataFrame:
    """Clasifica el margen. Se calcula en frames enteros para evitar errores de redondeo.

    margin_category:
      pressure_before_throw            presión antes del lanzamiento (margen exacto < 0)
      simultaneous_pressure_and_throw  mismo frame (margen exacto = 0, categoría propia)
      pressure_after_throw             presión tras el lanzamiento y antes del fin del tracking (> 0)
      pressure_not_observed_censored   sin presión antes del fin del tracking: dato censurado;
                                       solo se conoce observed_margin_lower_bound_s
      not_applicable_*                 falta snap, lanzamiento o QB/rushers
    """
    ok_snap = t["snap_status"] == "ok"
    ok_throw = t["valid_throw_time"].astype(bool)
    pressed = t["pressure_status"] == "pressure_observed"
    not_obs = t["pressure_status"] == "pressure_not_observed"
    pf = t["pressure_frame"].astype("float64")
    tf = t["throw_frame"].astype("float64")
    lf = t["last_frame"].astype("float64")
    exact = ok_snap & ok_throw & pressed
    censored = ok_snap & ok_throw & not_obs
    mf = (pf - tf).where(exact)
    t["decision_margin_frames"] = mf.astype("Int32")
    t["decision_margin_s"] = mf / fps
    t["observed_after_throw_s"] = ((lf - tf) / fps).where(ok_snap & ok_throw)
    t["observed_margin_lower_bound_s"] = ((lf - tf) / fps).where(censored)
    t["margin_category"] = np.select(
        [~ok_snap, t["throw_status"] != "ok", t["throw_before_snap"].astype(bool),
         t["pressure_status"].isin(["no_qb", "no_rushers", "no_qb_tracking"]),
         censored, exact & (mf < 0), exact & (mf == 0), exact & (mf > 0)],
        ["not_applicable_no_snap", "not_applicable_no_throw", "not_applicable_throw_before_snap",
         "not_applicable_no_qb_or_rushers", MARGIN_CENSORED, "pressure_before_throw",
         "simultaneous_pressure_and_throw", "pressure_after_throw"],
        default="unclassified")
    t["margin_is_exact"] = t["margin_category"].isin(MARGIN_EXACT)
    return t


def _review_flags(t: pd.DataFrame, pff_flags: pd.DataFrame) -> pd.DataFrame:
    """Marca (sin eliminar) jugadas con etiquetas posiblemente inconsistentes."""
    t = t.merge(pff_flags, on=KEYS, how="left")
    for c in ("pff_hit", "pff_hurry", "pff_sack"):
        t[c] = t[c].fillna(0).astype(int)
    t["pff_pressure_any"] = t["pff_pressure_any"].astype("boolean").fillna(False).astype(bool)
    has_throw = t["throw_frame"].notna()
    f = {
        "sack_with_throw_event": (t["outcome"] == "sack") & has_throw,
        "scramble_with_throw_event": (t["outcome"] == "scramble") & has_throw,
        "dropback_without_throw_event": t["no_throw_reason"] == "dropback_without_throw_event",
        "qb_sack_event_but_not_sack": t["qb_sack_event_present"] & (t["outcome"] != "sack"),
        "sack_without_qb_sack_event": (t["outcome"] == "sack") & ~t["qb_sack_event_present"],
        "pff_sack_but_not_sack": (t["pff_sack"] > 0) & (t["outcome"] != "sack"),
        "sack_without_pff_sack": (t["outcome"] == "sack") & (t["pff_sack"] == 0),
        "throw_without_snap": has_throw & (t["snap_status"] != "ok"),
        "snap_manual_auto_conflict": t["snap_manual_auto_conflict"].astype("boolean").fillna(False).astype(bool),
        "snap_event_in_several_frames": (t["ball_snap_nframes"].fillna(0) > 1)
        | ((t["snap_event"] == pe.SNAP_FALLBACK) & (t["autoevent_ballsnap_nframes"].fillna(0) > 1)),
        "throw_event_in_several_frames": (t["pass_forward_nframes"].fillna(0) > 1)
        | (t["autoevent_passforward_nframes"].fillna(0) > 1),
        "qb_non_qb_position": t["qb_status"] == "ok_non_qb_position",
        "qb_missing_or_ambiguous": t["qb_status"].isin(["no_qb", "ambiguous_qb"]),
        "pressure_tie": t["pressure_tie"],
        "pressure_time_zero_or_less": t["pressure_time_s"] <= 0,  # debe ser 0 con la versión 2
        "preexisting_proximity_at_snap": t["preexisting_proximity_at_snap"],
        "pressure_by_reentry": t["pressure_by_reentry"],
    }
    for k, v in f.items():
        t[f"flag_{k}"] = v.astype("boolean").fillna(False).astype(bool)
    cols = [f"flag_{k}" for k in f]
    t["review_flags"] = t[cols].apply(lambda r: ";".join(c[5:] for c in cols if r[c]), axis=1)
    return t


def build_metrics(game_ids=None):
    """Procesa el tracking juego por juego. Devuelve (tabla_por_jugada, tabla_por_defensor)."""
    plays, players, pff = da.load_plays(), da.load_players(), da.load_pff()
    qb_all = pr.identify_qb(pff, players, plays)
    pff_by_game = {g: d for g, d in pff.groupby("gameId")}
    qb_by_game = {g: d for g, d in qb_all.groupby("gameId")}
    evs, press, defs = [], [], []
    for gid, df in da.iter_tracking(GAME_COLS, game_ids):
        ev, pres, by_def = process_game(df, pff_by_game[gid], qb_by_game[gid])
        evs.append(ev)
        press.append(pres.drop(columns=["qb_nflId", "qb_status"]))
        defs.append(by_def)
    t = pe.add_timings(pd.concat(evs, ignore_index=True))
    t = pe.classify_outcome(t, plays)
    t = t.merge(qb_all, on=KEYS, how="left", validate="one_to_one")
    t = t.merge(pd.concat(press, ignore_index=True), on=KEYS, how="left", validate="one_to_one")
    t = _margin_columns(t)
    t = _review_flags(t, pff_play_flags(pff))
    t = t.rename(columns={"snap_to_throw_s": "throw_time_s"})
    v = t["throw_time_s"].dropna()
    if len(v):
        q1, q3 = v.quantile(0.25), v.quantile(0.75)
        t["flag_extreme_throw_time"] = t["throw_time_s"] > q3 + 3 * (q3 - q1)  # solo señal; no filtra
    return t, pd.concat(defs, ignore_index=True)
