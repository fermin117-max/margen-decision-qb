"""Informe de validación de presión y margen de decisión (stdout; sin escritura en disco).

Uso: .venv\\Scripts\\python.exe -m backend.validate_pressure [--skip-audit]
"""
from __future__ import annotations

import argparse
import json
import time

import pandas as pd

from backend import audit
from backend import data_access as da
from backend import metrics as mt
from backend import pressure as pr

KEYS = da.KEYS_PLAY


def vc(s: pd.Series) -> dict:
    return {str(k): int(v) for k, v in s.value_counts(dropna=False).items()}


def hist(s: pd.Series, edges: list[float]) -> dict:
    c = pd.cut(s.dropna(), bins=edges, right=False)
    return {str(k): int(v) for k, v in c.value_counts(sort=False).items()}


def desc(s: pd.Series) -> dict:
    s = s.dropna().astype(float)
    if s.empty:
        return {"count": 0}
    d = {k: round(float(v), 2) for k, v in s.describe().items()}
    d.update({f"p{int(q * 100)}": round(float(s.quantile(q)), 2) for q in (0.01, 0.05, 0.95, 0.99)})
    return d


def checks(t: pd.DataFrame) -> dict:
    """Comprobaciones de consistencia. Cada valor debe ser 0."""
    cat = t["margin_category"]
    m = t["decision_margin_frames"].astype("float64")
    obs_f = (t["last_frame"].astype(float) - t["throw_frame"].astype(float))
    return {
        "margen_positivo_mayor_que_tracking_observado": int(((m > obs_f) & (m > 0)).sum()),
        "pressure_after_throw_con_margen_<=0": int(((cat == "pressure_after_throw") & ~(m > 0)).sum()),
        "pressure_before_throw_con_margen_>=0": int(((cat == "pressure_before_throw") & ~(m < 0)).sum()),
        "simultaneous_con_margen_distinto_de_0": int(((cat == "simultaneous_pressure_and_throw") & (m != 0)).sum()),
        "censurados_con_margen_exacto": int(((cat == mt.MARGIN_CENSORED) & t["decision_margin_s"].notna()).sum()),
        "censurados_sin_cota_inferior": int(((cat == mt.MARGIN_CENSORED)
                                             & t["observed_margin_lower_bound_s"].isna()).sum()),
        "exactos_con_cota_inferior": int((t["margin_is_exact"] & t["observed_margin_lower_bound_s"].notna()).sum()),
        "margen_sin_snap_o_sin_lanzamiento": int((t["decision_margin_s"].notna()
                                                  & ~(t["snap_status"].eq("ok") & t["valid_throw_time"])).sum()),
        "pressure_time_s_<=0": int((t["pressure_time_s"] <= 0).sum()),
        "presion_despues_del_ultimo_frame": int((t["pressure_frame"].astype(float) > t["last_frame"].astype(float)).sum()),
        "margen_frames_vs_segundos_inconsistente": int(
            ((t["decision_margin_s"] - (t["pressure_time_s"] - t["throw_time_s"])).abs() > 1e-6).sum()),
        "jugadas_sin_categoria": int((cat == "unclassified").sum()),
        "categorias_suman_total": int(cat.value_counts().sum() != len(t)),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-audit", action="store_true")
    args = ap.parse_args()
    t0 = time.time()
    t, by_def = mt.build_metrics()
    cfg = pr.DEFAULT
    rep: dict = {"definicion_operacional": {
        "nota": "Definición propia del equipo, NO oficial de la NFL (versión 2)",
        "distancia_max_yd": cfg.max_distance_yd, "frames_consecutivos": cfg.min_consecutive_frames,
        "fps": cfg.fps, "llegada": "entrada al radio en f > snap (fuera en f-1) y persistente"}}
    rep["jugadas"] = {"procesadas": len(t), "llaves_duplicadas": int(t.duplicated(KEYS).sum()),
                      "qb_estado": vc(t["qb_status"]),
                      "con_pass_rushers": int((t["n_rushers_pff"] > 0).sum())}

    # Presión
    pobs = t["pressure_status"] == "pressure_observed"
    rep["presion"] = {
        "estado": vc(t["pressure_status"]),
        "empates_en_primer_frame": int(t["pressure_tie"].sum()),
        "distribucion_pressure_time_s": desc(t["pressure_time_s"]),
        "histograma_pressure_time_s": hist(t["pressure_time_s"], [0, 0.5, 1, 1.5, 2, 2.5, 3, 4, 5, 7, 10, 100]),
        "distancia_al_llegar_yd": desc(t["pressure_dist_yd"]),
    }
    pre = t["preexisting_proximity_at_snap"]
    rep["proximidad_en_el_snap"] = {
        "jugadas_preexisting_proximity_at_snap": int(pre.sum()),
        "rushers_dentro_del_radio_en_el_snap": int(t["n_rushers_within_at_snap"].sum()),
        "de_esas_jugadas_con_llegada_posterior": int((pre & pobs).sum()),
        "de_esas_jugadas_sin_llegada_posterior": int((pre & ~pobs).sum()),
        "llegada_posterior_por_reentrada_del_mismo_defensor": int((pre & t["pressure_by_reentry"]).sum()),
        "llegada_posterior_de_otro_defensor": int((pre & pobs & ~t["pressure_by_reentry"]).sum()),
        "defensores_cerca_en_snap_que_reentraron": int(t["n_preexisting_reentered"].sum()),
        "pressure_time_s_en_esas_jugadas": desc(t.loc[pre, "pressure_time_s"]),
        "por_outcome": vc(t.loc[pre, "outcome"]),
    }

    # Margen
    cat = t["margin_category"]
    ex = t[t["margin_is_exact"]]
    cen = t[cat == mt.MARGIN_CENSORED]
    rep["margen"] = {
        "categorias": vc(cat),
        "exactos": {
            "n": int(len(ex)),
            "distribucion_decision_margin_s": desc(ex["decision_margin_s"]),
            "histograma": hist(ex["decision_margin_s"], [-100, -3, -2, -1, -0.5, -0.1, 0, 0.1, 0.2, 0.3, 0.4, 0.5, 1, 100]),
            "pressure_before_throw": desc(ex.loc[ex["margin_category"] == "pressure_before_throw", "decision_margin_s"]),
            "pressure_after_throw": desc(ex.loc[ex["margin_category"] == "pressure_after_throw", "decision_margin_s"]),
            "simultaneous_pressure_and_throw": int((ex["margin_category"] == "simultaneous_pressure_and_throw").sum()),
        },
        "censurados": {
            "n": int(len(cen)),
            "observed_margin_lower_bound_s": desc(cen["observed_margin_lower_bound_s"]),
            "histograma_cota_inferior": hist(cen["observed_margin_lower_bound_s"], [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 1, 2, 100]),
            "nota": "Cota inferior observada, NO margen exacto. Excluidos del promedio y la mediana.",
        },
        "tracking_tras_el_lanzamiento_s(todas_con_lanzamiento_valido)": desc(t["observed_after_throw_s"]),
        "tiempo_lanzamiento_s": desc(t["throw_time_s"]),
        "lanzamientos_extremos(Q3+3*IQR)": int(t["flag_extreme_throw_time"].sum()),
        "por_outcome": {str(k): vc(g["margin_category"]) for k, g in t.groupby("outcome", dropna=False)},
        "mediana_margen_exacto_por_outcome": {
            str(k): (None if g["decision_margin_s"].dropna().empty else round(float(g["decision_margin_s"].median()), 2))
            for k, g in t.groupby("outcome", dropna=False)},
    }
    rep["comprobaciones(deben_ser_0)"] = checks(t)

    # PFF (solo comparación)
    base = t[t["pressure_status"].isin(["pressure_observed", "pressure_not_observed"])]
    det = base["pressure_status"] == "pressure_observed"
    cmp = {"jugadas_comparables": int(len(base)),
           "det_y_pff": int((det & base["pff_pressure_any"]).sum()),
           "det_sin_pff": int((det & ~base["pff_pressure_any"]).sum()),
           "no_det_con_pff": int((~det & base["pff_pressure_any"]).sum()),
           "no_det_sin_pff": int((~det & ~base["pff_pressure_any"]).sum())}
    for c in ("pff_hit", "pff_hurry", "pff_sack"):
        f = base[c] > 0
        cmp[c] = {"jugadas_con_marca": int(f.sum()), "detectadas": int((f & det).sum()),
                  "tasa_con_marca": round(float((f & det).sum() / max(f.sum(), 1)), 3),
                  "tasa_sin_marca": round(float((~f & det).sum() / max((~f).sum(), 1)), 3)}
    r = pd.read_csv(da.DATA_DIR / "pffScoutingData.csv")
    r = r[r["pff_role"] == "Pass Rush"][KEYS + ["nflId", "pff_hit", "pff_hurry", "pff_sack"]]
    rr = by_def.merge(r, on=KEYS + ["nflId"], how="inner")
    rr["any_flag"] = rr[["pff_hit", "pff_hurry", "pff_sack"]].fillna(0).sum(axis=1) > 0
    cmp["nivel_defensor"] = {
        "rushers": int(len(rr)),
        "tasa_llegada_con_marca": round(float(rr.loc[rr["any_flag"], "arrived"].mean()), 3),
        "tasa_llegada_sin_marca": round(float(rr.loc[~rr["any_flag"], "arrived"].mean()), 3)}
    s = t[t["qb_sack_event_present"] & pobs]
    cmp["sacks_evento_qb_sack_con_presion"] = {
        "n": int(len(s)),
        "presion_en_o_antes_del_evento": int((s["pressure_frame"] <= s["sack_event_frame"]).sum())}
    ss = t[t["outcome"] == "sack"]
    cmp["sacks_passResult_S"] = {"n": int(len(ss)), "con_presion": int((ss["pressure_status"] == "pressure_observed").sum())}
    rep["comparacion_pff"] = cmp

    flag_cols = [c for c in t.columns if c.startswith("flag_")]
    rep["anomalias"] = {"jugadas_con_alguna_marca": int((t["review_flags"] != "").sum()),
                        "conteo_por_marca": {c[5:]: int(t[c].sum()) for c in flag_cols},
                        "duplicados_defensor_por_jugada": int(by_def.duplicated(KEYS + ["nflId"]).sum())}

    if not args.skip_audit:
        ind = audit.independent_pressure(t)
        a = audit.compare_with_module(t, ind)
        a["ejemplos_discrepancia"] = a["ejemplos_discrepancia"][:5]
        rep["auditoria_independiente"] = a
        rep["fallo_anterior_ids_reproducido"] = audit.reproduce_old_id_bug(by_def, ind)
        samples = []
        want = {
            "pressure_before_throw": t[cat == "pressure_before_throw"],
            "pressure_after_throw": t[cat == "pressure_after_throw"],
            "simultaneous": t[cat == "simultaneous_pressure_and_throw"],
            "proximidad_en_snap_con_reentrada": t[pre & t["pressure_by_reentry"]],
        }
        for label, g in want.items():
            g = g.sort_values(KEYS)
            for _, r_ in (g.iloc[[0, len(g) // 2]] if len(g) > 1 else g).iterrows():
                d_id = int(str(r_["pressure_defenders"]).split(";")[0])
                center = int(r_["pressure_frame"])
                samples.append({
                    "caso": label, "gameId": int(r_["gameId"]), "playId": int(r_["playId"]),
                    "qb": int(r_["qb_nflId"]), "defensor": d_id, "snap": int(r_["snap_frame"]),
                    "throw": None if pd.isna(r_["throw_frame"]) else int(r_["throw_frame"]),
                    "last_frame": int(r_["last_frame"]), "pressure_frame": center,
                    "margin_s": r_["decision_margin_s"],
                    "coords_en_snap": audit.coordinate_table(int(r_["gameId"]), int(r_["playId"]),
                                                             int(r_["qb_nflId"]), d_id, int(r_["snap_frame"]), 0, 0)
                    if label.startswith("proximidad") else None,
                    "coords": audit.coordinate_table(int(r_["gameId"]), int(r_["playId"]),
                                                     int(r_["qb_nflId"]), d_id, center, 2, 1)})
        rep["revision_manual_coordenadas"] = samples
    rep["segundos"] = round(time.time() - t0, 1)
    print(json.dumps(rep, indent=1, ensure_ascii=False, default=lambda o: None if pd.isna(o) else str(o)))


if __name__ == "__main__":
    main()
