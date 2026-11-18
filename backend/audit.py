"""Auditorías independientes: recalculan desde los CSV crudos (float64, sin tipos compactos)
y no reutilizan la lógica de pressure.py, para contrastar los resultados.

Solo lectura. Uso desde validate_pressure.py.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from backend import data_access as da

KEYS = da.KEYS_PLAY


def _raw(gid: int) -> pd.DataFrame:
    p = da.TRACKING_DIR / f"tracking_{gid}.csv"
    return pd.read_csv(p, usecols=["gameId", "playId", "nflId", "frameId", "x", "y", "s", "event"])


def independent_pressure(t: pd.DataFrame, max_d: float = 2.0, n_frames: int = 2) -> pd.DataFrame:
    """Recalcula pressure_frame y defensores con bucles simples sobre datos float64."""
    pff = pd.read_csv(da.DATA_DIR / "pffScoutingData.csv", usecols=["gameId", "playId", "nflId", "pff_role"])
    out = []
    snap = t.set_index(KEYS)["snap_frame"]
    for gid, gt in t.groupby("gameId"):
        raw = _raw(int(gid))
        raw = raw[raw["nflId"].notna()]
        pg = pff[pff["gameId"] == gid]
        for pid in gt["playId"]:
            sf = snap.get((gid, pid))
            sub = raw[raw["playId"] == pid]
            ppff = pg[pg["playId"] == pid]
            qbs = ppff.loc[ppff["pff_role"] == "Pass", "nflId"].unique()
            rus = ppff.loc[ppff["pff_role"] == "Pass Rush", "nflId"].unique()
            best, who, pre = None, [], []
            if len(qbs) == 1 and pd.notna(sf):
                q = sub[sub["nflId"] == qbs[0]].set_index("frameId")[["x", "y"]]
                for r in rus:
                    s = sub[sub["nflId"] == r].set_index("frameId")[["x", "y"]]
                    fr = s.index.intersection(q.index)
                    if len(fr) == 0:
                        continue
                    dx = s.loc[fr, "x"].to_numpy() - q.loc[fr, "x"].to_numpy()
                    dy = s.loc[fr, "y"].to_numpy() - q.loc[fr, "y"].to_numpy()
                    inside = dict(zip(fr.to_numpy(), np.sqrt(dx * dx + dy * dy) <= max_d + 1e-9))
                    if inside.get(sf, False):
                        pre.append(int(r))
                    first = None
                    for f in sorted(inside):
                        # v2: entrada real al radio (fuera en f-1), estrictamente después del snap
                        if (f > sf and not inside.get(f - 1, False)
                                and all(inside.get(f + k, False) for k in range(n_frames))):
                            first = f
                            break
                    if first is not None:
                        if best is None or first < best:
                            best, who = first, [int(r)]
                        elif first == best:
                            who.append(int(r))
            out.append({"gameId": gid, "playId": pid, "ind_pressure_frame": best,
                        "ind_defenders": ";".join(map(str, sorted(who))),
                        "ind_preexisting": ";".join(map(str, sorted(pre)))})
    return pd.DataFrame(out)


def compare_with_module(t: pd.DataFrame, ind: pd.DataFrame | None = None) -> dict:
    ind = independent_pressure(t) if ind is None else ind
    m = t[KEYS + ["pressure_frame", "pressure_defenders", "preexisting_defenders",
                  "pressure_status"]].merge(ind, on=KEYS)
    mf = m["pressure_frame"].astype("float64")
    inf = m["ind_pressure_frame"].astype("float64")
    same_frame = (mf == inf) | (mf.isna() & inf.isna())

    def norm(s: pd.Series) -> pd.Series:
        # nflId normalizado como texto: "44829", "44829.0" o 44829 -> "44829"
        return s.fillna("").astype(str).map(
            lambda v: ";".join(sorted(str(int(float(x))) for x in v.split(";") if x)))

    raw_def_diff = m["pressure_defenders"].fillna("").astype(str) != m["ind_defenders"]

    same_def = norm(m["pressure_defenders"]) == norm(m["ind_defenders"])
    same_pre = norm(m["preexisting_defenders"]) == norm(m["ind_preexisting"])
    bad = m[~(same_frame & same_def & same_pre)]
    return {"jugadas_comparadas": int(len(m)), "frame_distinto": int((~same_frame).sum()),
            "defensores_distintos_texto_sin_normalizar": int(raw_def_diff.sum()),
            "defensores_distintos_nflId_normalizado": int((~same_def).sum()),
            "proximidad_en_snap_distinta": int((~same_pre).sum()),
            "ejemplos_discrepancia": bad.head(10).to_dict("records")}


def reproduce_old_id_bug(by_def: pd.DataFrame, ind: pd.DataFrame | None = None) -> dict:
    """Reproduce la agregación de la versión anterior (lambda join sobre nflId Int32, por juego)
    y cuenta cuántas jugadas devolvía como número en vez de texto, y si coinciden al normalizar."""
    a = by_def[by_def["arrival_frame"].notna()].copy()
    a["nflId"] = a["nflId"].astype("Int32")
    rows = []
    for _, g in a.groupby("gameId"):
        pmin = g.groupby(KEYS)["arrival_frame"].transform("min")
        first = g[g["arrival_frame"] == pmin]
        agg = first.groupby(KEYS).agg(
            old=("nflId", lambda s: ";".join(str(int(v)) for v in sorted(s))))
        rows.append(agg.reset_index())
    old = pd.concat(rows, ignore_index=True)
    is_text = old["old"].map(lambda v: isinstance(v, str))
    res = {"jugadas_con_presion": int(len(old)),
           "valor_devuelto_como_numero": int((~is_text).sum()),
           "valor_devuelto_como_texto": int(is_text.sum())}
    if ind is not None:
        m = old.merge(ind, on=KEYS)
        raw = pd.Series([a_ != b_ for a_, b_ in zip(m["old"], m["ind_defenders"])])
        normed = m["old"].astype(str) != m["ind_defenders"]
        res["diferencias_sin_normalizar"] = int(raw.sum())
        res["diferencias_tras_normalizar_texto"] = int(normed.sum())
    return res


def coordinate_table(gid: int, pid: int, qb_id: int, def_id: int, center: int, before=2, after=2) -> list[dict]:
    """Coordenadas crudas de QB y defensor en frames alrededor de `center`."""
    raw = _raw(gid)
    sub = raw[(raw["playId"] == pid) & raw["nflId"].isin([qb_id, def_id])]
    q = sub[sub["nflId"] == qb_id].set_index("frameId")
    d = sub[sub["nflId"] == def_id].set_index("frameId")
    rows = []
    for f in range(center - before, center + after + 1):
        if f in q.index and f in d.index:
            dist = float(np.hypot(d.at[f, "x"] - q.at[f, "x"], d.at[f, "y"] - q.at[f, "y"]))
            rows.append({"frame": f, "qb_x": q.at[f, "x"], "qb_y": q.at[f, "y"],
                         "def_x": d.at[f, "x"], "def_y": d.at[f, "y"], "dist": round(dist, 3),
                         "<=2.0": dist <= 2.0 + 1e-9})
    return rows


def snap_conflict_review(t: pd.DataFrame) -> list[dict]:
    """Jugadas con |auto - manual| > 10 frames: ¿dónde se mueve realmente el balón?

    Si el balón sigue quieto entre el frame automático y el manual, y empieza a moverse en el
    manual, el evento manual es consistente. No cambia ninguna prioridad.
    """
    c = t[t["snap_manual_auto_conflict"]]
    res = []
    for gid, g in c.groupby("gameId"):
        raw = _raw(int(gid))
        ball = raw[raw["nflId"].isna()]
        for _, r in g.iterrows():
            b = ball[ball["playId"] == r["playId"]].set_index("frameId")
            man, aut = int(r["ball_snap_frame"]), int(r["autoevent_ballsnap_frame"])

            def pos(f):
                return (b.at[f, "x"], b.at[f, "y"]) if f in b.index else (np.nan, np.nan)

            def dist(f1, f2):
                (x1, y1), (x2, y2) = pos(f1), pos(f2)
                return float(np.hypot(x2 - x1, y2 - y1))

            speed_after = float(b.loc[man + 1:man + 5, "s"].mean()) if len(b.loc[man + 1:man + 5]) else np.nan
            res.append({
                "gameId": int(gid), "playId": int(r["playId"]), "manual": man, "auto": aut,
                "diff": aut - man,
                "balon_movido_entre_auto_y_manual_yd": round(dist(aut, man), 2),
                "balon_movido_manual_a_manual+5_yd": round(dist(man, min(man + 5, int(b.index.max()))), 2),
                "vel_balon_prom_manual+1..+5": round(speed_after, 2),
                "throw_frame": None if pd.isna(r["throw_frame"]) else int(r["throw_frame"]),
                "t_lanz_con_manual_s": None if pd.isna(r["throw_frame"]) else round((r["throw_frame"] - man) / 10, 1),
                "t_lanz_con_auto_s": None if pd.isna(r["throw_frame"]) else round((r["throw_frame"] - aut) / 10, 1),
                "autoevent_en_n_frames": int(r["autoevent_ballsnap_nframes"]),
            })
    return res
