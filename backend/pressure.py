"""Llegada de presión: DEFINICIÓN OPERACIONAL PROPIA del equipo (no es una definición oficial de la NFL).

Versión 2:
- Posibles pass rushers: pff_role == "Pass Rush". QB: el único registro pff_role == "Pass".
- d = sqrt((x_def - x_QB)^2 + (y_def - y_QB)^2), solo entre filas del mismo gameId, playId, frameId.
- "Dentro del radio": d <= 2.0 yardas.
- Llegada de un defensor: primer frame f > snap_frame tal que
    * el defensor está dentro del radio en f y en los (min_consecutive_frames - 1) frames siguientes, y
    * NO estaba dentro del radio en f - 1 (es una entrada real al radio).
  Consecuencias:
    * Si el defensor ya estaba dentro del radio en el frame del snap se marca
      `preexisting_proximity_at_snap`; esa racha inicial no cuenta como llegada (no hay tiempo 0).
    * Si después sale del radio y vuelve a entrar (con persistencia), esa nueva entrada sí cuenta.
    * Si estaba fuera en el snap y entra después, cuenta normalmente.
    * No se agrega ningún retraso arbitrario tras el snap.
- Presión de la jugada = primera llegada entre los pass rushers; empates en el mismo frame se registran.
- Tiempos: (frame - snap_frame) / fps, fps = 10.

pff_hit / pff_hurry / pff_sack NO fijan instantes; solo se usan para comparar.
Funciones puras sobre DataFrames: no dependen de FastAPI ni escriben en disco.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from backend import data_access as da

KEYS = da.KEYS_PLAY
DEF_KEYS = KEYS + ["nflId"]
EPS = 1e-9


@dataclass(frozen=True)
class PressureConfig:
    max_distance_yd: float = 2.0
    min_consecutive_frames: int = 2
    fps: float = 10.0
    rusher_role: str = "Pass Rush"
    qb_role: str = "Pass"


DEFAULT = PressureConfig()


def _ids_text(s: pd.Series) -> str:
    """IDs como texto normalizado 'id1;id2' (orden ascendente)."""
    return ";".join(str(int(v)) for v in sorted(s))


def identify_qb(pff: pd.DataFrame, players: pd.DataFrame, plays: pd.DataFrame,
                cfg: PressureConfig = DEFAULT) -> pd.DataFrame:
    """Una fila por jugada con el QB (pff_role == 'Pass') y su estado de identificación."""
    q = pff[pff["pff_role"] == cfg.qb_role]
    g = q.groupby(KEYS).agg(n_qb_rows=("nflId", "size"), n_qb_ids=("nflId", "nunique"),
                            qb_nflId=("nflId", "first"), qb_pff_position=("pff_positionLinedUp", "first"))
    out = plays[KEYS].merge(g.reset_index(), on=KEYS, how="left")
    out["n_qb_rows"] = out["n_qb_rows"].fillna(0).astype("int16")
    out["n_qb_ids"] = out["n_qb_ids"].fillna(0).astype("int16")
    unique = (out["n_qb_rows"] == 1) & (out["n_qb_ids"] == 1)
    out["qb_nflId"] = out["qb_nflId"].where(unique).astype("Int32")
    pos = players.set_index("nflId")["officialPosition"]
    out["qb_official_position"] = out["qb_nflId"].map(pos)
    out["qb_status"] = np.select(
        [out["n_qb_rows"] == 0, ~unique, out["qb_official_position"] != "QB"],
        ["no_qb", "ambiguous_qb", "ok_non_qb_position"], default="ok")
    return out


def rusher_distances(df: pd.DataFrame, pff_game: pd.DataFrame, qb: pd.DataFrame,
                     cfg: PressureConfig = DEFAULT) -> tuple[pd.DataFrame, dict]:
    """Distancia rusher-QB por frame (una fila por gameId, playId, nflId, frameId)."""
    t = df[df["nflId"].notna()]
    rush = pff_game.loc[pff_game["pff_role"] == cfg.rusher_role, DEF_KEYS].drop_duplicates()
    qbx = qb[KEYS + ["qb_nflId"]].dropna().rename(columns={"qb_nflId": "nflId"})
    qpos = t.merge(qbx, on=DEF_KEYS)[KEYS + ["frameId", "x", "y"]].rename(columns={"x": "qx", "y": "qy"})
    if qpos.duplicated(KEYS + ["frameId"]).any():
        raise ValueError("QB con más de una posición por (gameId, playId, frameId)")
    rp = t.merge(rush, on=DEF_KEYS)
    # Join por gameId, playId y frameId: QB y defensor siempre del mismo frame.
    d = rp[DEF_KEYS + ["frameId", "x", "y"]].merge(qpos, on=KEYS + ["frameId"], how="inner",
                                                   validate="many_to_one")
    dx = d["x"].astype("float64").round(2) - d["qx"].astype("float64").round(2)
    dy = d["y"].astype("float64").round(2) - d["qy"].astype("float64").round(2)
    d["dist"] = np.hypot(dx, dy)
    d = d.sort_values(DEF_KEYS + ["frameId"]).reset_index(drop=True)
    info = {
        "n_rush": rush.groupby(KEYS).size().rename("n_rushers_pff"),
        "n_tracked": rp.groupby(KEYS)["nflId"].nunique().rename("n_rushers_tracked"),
        "qb_frames": qpos.groupby(KEYS).size().rename("qb_tracking_frames"),
        "rows_without_qb": int(len(rp) - len(d)),
    }
    return d, info


def mark_arrivals(d: pd.DataFrame, snap_frames: pd.DataFrame, cfg: PressureConfig = DEFAULT) -> pd.DataFrame:
    """Añade within, at_snap_within y arrival (llegada válida tras el snap) por frame."""
    d = d.merge(snap_frames[KEYS + ["snap_frame"]], on=KEYS, how="left")
    snap = d["snap_frame"].astype("float64")
    d["within"] = d["dist"] <= cfg.max_distance_yd + EPS
    g = d.groupby(DEF_KEYS, sort=False)
    prev_w = g["within"].shift(1, fill_value=False)
    prev_f = g["frameId"].shift(1)
    entered = d["within"] & ~(prev_w & (prev_f == d["frameId"] - 1))  # inicio de racha
    persistent = d["within"].copy()
    for k in range(1, cfg.min_consecutive_frames):
        persistent &= (g["frameId"].shift(-k) == d["frameId"] + k) & g["within"].shift(-k, fill_value=False)
    d["entry_persistent"] = entered & persistent
    d["arrival"] = d["entry_persistent"] & snap.notna() & (d["frameId"] > snap)
    d["at_snap_within"] = d["within"] & (d["frameId"] == snap)
    return d


def pressure_for_game(df: pd.DataFrame, pff_game: pd.DataFrame, qb: pd.DataFrame,
                      snap_frames: pd.DataFrame, cfg: PressureConfig = DEFAULT):
    """Detecta llegadas de presión en un juego. Devuelve (por_jugada, por_defensor)."""
    d, info = rusher_distances(df, pff_game, qb, cfg)
    d = mark_arrivals(d, snap_frames, cfg)

    # Por defensor
    arr = d[d["arrival"]].groupby(DEF_KEYS).agg(arrival_frame=("frameId", "min")).reset_index()
    arr = arr.merge(d[DEF_KEYS + ["frameId", "dist"]], left_on=DEF_KEYS + ["arrival_frame"],
                    right_on=DEF_KEYS + ["frameId"]).drop(columns="frameId").rename(
        columns={"dist": "dist_at_arrival_yd"})
    at_snap = d[d["at_snap_within"]][DEF_KEYS].assign(within_at_snap=True)
    by_def = d[DEF_KEYS].drop_duplicates().merge(arr, on=DEF_KEYS, how="left").merge(
        at_snap, on=DEF_KEYS, how="left")
    by_def["within_at_snap"] = by_def["within_at_snap"].astype("boolean").fillna(False).astype(bool)
    by_def["arrived"] = by_def["arrival_frame"].notna()

    # Por jugada: primera llegada y empates
    pmin = arr.groupby(KEYS)["arrival_frame"].min().rename("pressure_frame")
    first = arr.merge(pmin.reset_index(), on=KEYS)
    first = first[first["arrival_frame"] == first["pressure_frame"]]
    ties = first.groupby(KEYS).agg(pressure_n_first=("nflId", "size"),
                                   pressure_dist_yd=("dist_at_arrival_yd", "min"))
    ties["pressure_defenders"] = first.groupby(KEYS)["nflId"].apply(_ids_text).astype(str)

    pre = by_def[by_def["within_at_snap"]]
    pre_g = pre.groupby(KEYS).agg(n_rushers_within_at_snap=("nflId", "size"),
                                  n_preexisting_reentered=("arrived", "sum"))
    pre_g["preexisting_defenders"] = pre.groupby(KEYS)["nflId"].apply(_ids_text).astype(str)
    post_rows = d[d["frameId"].astype("float64") >= d["snap_frame"].astype("float64")]
    mind = post_rows.groupby(KEYS)["dist"].min().rename("min_rusher_dist_postsnap_yd")

    plays = qb[KEYS + ["qb_nflId", "qb_status"]].merge(snap_frames[KEYS + ["snap_frame"]], on=KEYS, how="left")
    out = plays
    for part in (info["n_rush"], info["n_tracked"], info["qb_frames"], pmin, ties, pre_g, mind):
        out = out.merge(part.reset_index(), on=KEYS, how="left")
    for c in ("n_rushers_pff", "n_rushers_tracked", "qb_tracking_frames",
              "n_rushers_within_at_snap", "n_preexisting_reentered"):
        out[c] = out[c].fillna(0).astype("int32")
    out["rusher_rows_without_qb_frame_game"] = info["rows_without_qb"]
    out["preexisting_proximity_at_snap"] = out["n_rushers_within_at_snap"] > 0
    ok_inputs = out["qb_status"].isin(["ok", "ok_non_qb_position"])
    out["pressure_status"] = np.select(
        [~ok_inputs, out["n_rushers_pff"] == 0, out["qb_tracking_frames"] == 0, out["snap_frame"].isna(),
         out["pressure_frame"].notna()],
        ["no_qb", "no_rushers", "no_qb_tracking", "no_snap", "pressure_observed"],
        default="pressure_not_observed")
    out["pressure_frame"] = out["pressure_frame"].astype("Int32")
    out["pressure_time_s"] = (out["pressure_frame"].astype("float64") - out["snap_frame"].astype("float64")) / cfg.fps
    out["pressure_tie"] = out["pressure_n_first"].fillna(0) > 1
    out["pressure_first_defender"] = pd.Series(pd.NA, index=out.index, dtype="Int32")
    single = out["pressure_n_first"] == 1
    out.loc[single, "pressure_first_defender"] = pd.to_numeric(out.loc[single, "pressure_defenders"]).astype("Int32")
    # ¿La presión la produjo un defensor que ya estaba cerca en el snap (re-entrada)?
    pd_sets = out["pressure_defenders"].fillna("").str.split(";")
    pre_sets = out["preexisting_defenders"].fillna("").str.split(";")
    out["pressure_by_reentry"] = [bool(set(a) & set(b) - {""}) for a, b in zip(pd_sets, pre_sets)]
    return out.drop(columns="snap_frame"), by_def
