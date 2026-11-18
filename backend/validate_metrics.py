"""Informe de validación de snap, lanzamiento y tiempos (stdout; no escribe en disco).

Uso: .venv\\Scripts\\python.exe -m backend.validate_metrics
"""
from __future__ import annotations

import json
import time

import pandas as pd

from backend import data_access as da
from backend import play_events as pe


def vc(s: pd.Series) -> dict:
    return {str(k): int(v) for k, v in s.value_counts(dropna=False).items()}


def main() -> None:
    t0 = time.time()
    t = pe.build_play_table()
    n = len(t)
    rep: dict = {}
    rep["jugadas_procesadas"] = n
    rep["jugadas_en_plays_csv"] = int(len(da.load_plays()))
    rep["llaves_duplicadas"] = int(t.duplicated(da.KEYS_PLAY).sum())

    # Origen de los eventos
    def origin(prefix: str) -> dict:
        m, a = t[f"{prefix}_has_manual"], t[f"{prefix}_has_auto"]
        return {
            "solo_manual": int((m & ~a).sum()),
            "solo_auto": int((~m & a).sum()),
            "ambos(se usa manual)": int((m & a).sum()),
            "ninguno": int((~m & ~a).sum()),
            "evento_usado": vc(t[f"{prefix}_event"]),
            "status": vc(t[f"{prefix}_status"]),
        }

    rep["snap"] = origin("snap")
    rep["lanzamiento"] = origin("throw")
    rep["jugadas_con_eventos_manuales_y_automaticos"] = {
        "snap_con_algun_manual": int(t["snap_has_manual"].sum()),
        "snap_con_algun_auto": int(t["snap_has_auto"].sum()),
        "lanzamiento_con_algun_manual": int(t["throw_has_manual"].sum()),
        "lanzamiento_con_algun_auto": int(t["throw_has_auto"].sum()),
    }

    # Jugadas sin snap
    ms = t[t["snap_status"] == "missing_snap"]
    rep["jugadas_sin_snap"] = {
        "n": int(len(ms)),
        "con_lanzamiento": int(ms["throw_frame"].notna().sum()),
        "por_outcome": vc(ms["outcome"]),
        "tiempos_calculados_para_ellas(debe ser 0)": int(ms["snap_to_throw_s"].notna().sum()),
    }

    # Lanzamientos
    rep["jugadas_validas_tiempo_lanzamiento"] = int(t["valid_throw_time"].sum())
    rep["jugadas_con_lanzamiento_pero_sin_snap"] = int(
        (t["throw_frame"].notna() & t["snap_frame"].isna()).sum())
    nt = t[t["throw_frame"].isna()]
    rep["jugadas_sin_lanzamiento"] = {
        "n": int(len(nt)),
        "por_outcome(passResult)": vc(nt["outcome"]),
        "por_motivo": vc(nt["no_throw_reason"]),
        "con_evento_qb_sack_o_strip_sack": int(nt["qb_sack_event_present"].sum()),
    }
    rep["sacks"] = {
        "passResult_S_total": int((t["outcome"] == "sack").sum()),
        "S_sin_lanzamiento": int(((t["outcome"] == "sack") & t["throw_frame"].isna()).sum()),
        "S_con_evento_de_lanzamiento": int(((t["outcome"] == "sack") & t["throw_frame"].notna()).sum()),
        "S_con_evento_qb_sack_o_strip": int(((t["outcome"] == "sack") & t["qb_sack_event_present"]).sum()),
        "con_evento_qb_sack_pero_passResult_distinto_de_S": vc(
            t.loc[t["qb_sack_event_present"] & (t["outcome"] != "sack"), "outcome"]),
    }
    rep["outcome_x_tiene_lanzamiento"] = {
        str(k): vc(g["throw_frame"].notna()) for k, g in t.groupby("outcome", dropna=False)}

    # Consistencia de tiempos
    v = t[t["valid_throw_time"]]
    s = v["snap_to_throw_s"]
    ts = v["snap_to_throw_s_timestamp"]
    rep["consistencia"] = {
        "lanzamiento_antes_del_snap": int(t["throw_before_snap"].sum()),
        "lanzamiento_en_el_mismo_frame_del_snap": int((v["snap_to_throw_frames"] == 0).sum()),
        "snap_to_throw_s_describe": {k: round(float(x), 2) for k, x in s.describe().items()},
        "snap_to_throw_s_percentiles": {str(q): round(float(s.quantile(q)), 2)
                                        for q in (0.01, 0.05, 0.5, 0.95, 0.99)},
        "lanzamientos_>8s": int((s > 8).sum()),
        "lanzamientos_<0.5s": int((s < 0.5).sum()),
        "frames_vs_timestamp_dif_abs_max_s": round(float((s - ts).abs().max()), 3),
        "frames_vs_timestamp_dif>1s": int(((s - ts).abs() > 1).sum()),
        "eventos_en_varios_frames(snap)": {
            e: int((t[f"{e}_nframes"] > 1).sum()) for e in (pe.SNAP_PRIMARY, pe.SNAP_FALLBACK)},
        "eventos_en_varios_frames(lanzamiento)": {
            e: int((t[f"{e}_nframes"] > 1).sum()) for e in (pe.THROW_PRIMARY, pe.THROW_FALLBACK)},
        "snap_frame_describe": {k: round(float(x), 1) for k, x in t["snap_frame"].astype(float).describe().items()},
        "snap_primer_frame_de_la_jugada": int((t["snap_frame"] == t["first_frame"]).sum()),
        "lanzamiento_ultimo_frame_de_la_jugada": int((t["throw_frame"] == t["last_frame"]).sum()),
        "frames_jugada_describe": {k: round(float(x), 1) for k, x in t["n_frames"].astype(float).describe().items()},
        "primer_frame_distinto_de_1": int((t["first_frame"] != 1).sum()),
    }

    # Diferencia manual vs auto cuando existen ambos
    for prefix, a, b in (("snap", pe.SNAP_PRIMARY, pe.SNAP_FALLBACK),
                         ("lanzamiento", pe.THROW_PRIMARY, pe.THROW_FALLBACK)):
        both = t[t[f"{a}_frame"].notna() & t[f"{b}_frame"].notna()]
        d = (both[f"{b}_frame"] - both[f"{a}_frame"]).astype(float)
        rep.setdefault("manual_vs_auto_cuando_existen_ambos(frames auto-manual)", {})[prefix] = {
            "n": int(len(both)),
            "iguales": int((d == 0).sum()),
            "describe": {k: round(float(x), 2) for k, x in d.describe().items()} if len(d) else {},
        }

    rep["presion_defensiva"] = ("NO calculada: el proyecto (reglas, INSTALACION, steering, setup) "
                                "no define distancia ni umbral. Pendiente de definición del equipo.")
    rep["segundos"] = round(time.time() - t0, 1)
    print(json.dumps(rep, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
