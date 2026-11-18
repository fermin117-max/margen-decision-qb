"""Eventos de snap y lanzamiento por jugada, y tiempos derivados.

Reglas metodológicas acordadas:
- Snap: ball_snap; si falta, autoevent_ballsnap; si no hay ninguno, status "missing_snap".
- Lanzamiento: pass_forward; si falta, autoevent_passforward; si no hay ninguno, "missing_pass_forward".
- Si existen ambos eventos, solo cuenta el manual. Siempre se conserva el evento usado
  y su frame/tiempo para poder auditar.
- No se estiman tiempos de jugadas sin evento (quedan nulos).

Frecuencia del tracking: 10 Hz, por lo que segundos = (frame - frame_snap) / 10.
Nada de esto escribe en disco: todo se calcula en memoria a partir de data/.
"""
from __future__ import annotations

import pandas as pd

from backend import data_access as da

FPS = 10.0

SNAP_PRIMARY, SNAP_FALLBACK = "ball_snap", "autoevent_ballsnap"
THROW_PRIMARY, THROW_FALLBACK = "pass_forward", "autoevent_passforward"
SACK_EVENTS = ("qb_sack", "qb_strip_sack")
TRACKED_EVENTS = (SNAP_PRIMARY, SNAP_FALLBACK, THROW_PRIMARY, THROW_FALLBACK, *SACK_EVENTS)

TRACKING_COLS = ["gameId", "playId", "frameId", "time", "event"]

# passResult de plays.csv (valores observados: C, I, S, R, IN)
PASS_RESULT_LABEL = {
    "C": "completion",
    "I": "incompletion",
    "IN": "interception",
    "S": "sack",
    "R": "scramble",
}


def _pick(frames: pd.DataFrame, primary: str, fallback: str, prefix: str,
          missing_label: str) -> pd.DataFrame:
    """Elige el evento manual si existe y, si no, el automático."""
    p, f = frames[f"{primary}_frame"], frames[f"{fallback}_frame"]
    use_primary = p.notna()
    use_fallback = ~use_primary & f.notna()
    out = pd.DataFrame(index=frames.index)
    out[f"{prefix}_event"] = pd.Series(
        pd.NA, index=frames.index, dtype="string").mask(use_primary, primary).mask(use_fallback, fallback)
    out[f"{prefix}_source"] = pd.Series(
        pd.NA, index=frames.index, dtype="string").mask(use_primary, "manual").mask(use_fallback, "auto")
    out[f"{prefix}_frame"] = p.where(use_primary, f).astype("Int32")
    out[f"{prefix}_status"] = "ok"
    out.loc[~(use_primary | use_fallback), f"{prefix}_status"] = missing_label
    out[f"{prefix}_has_manual"] = p.notna()
    out[f"{prefix}_has_auto"] = f.notna()
    return out


def play_event_table(df: pd.DataFrame) -> pd.DataFrame:
    """Tabla de una fila por jugada para un juego (df con TRACKING_COLS)."""
    keys = da.KEYS_PLAY
    frames = df[keys + ["frameId", "time"]].drop_duplicates(keys + ["frameId"]).copy()
    frames["time"] = pd.to_datetime(frames["time"], utc=True, format="ISO8601")
    base = frames.groupby(keys).agg(
        n_frames=("frameId", "size"), first_frame=("frameId", "min"), last_frame=("frameId", "max"))

    ev = df.loc[df["event"].isin(TRACKED_EVENTS), keys + ["frameId", "event"]].copy()
    ev["event"] = ev["event"].astype(str)
    agg = ev.groupby(keys + ["event"]).frameId.agg(["min", "nunique"]).reset_index()
    for name in TRACKED_EVENTS:
        sub = agg[agg["event"] == name].set_index(keys)
        base[f"{name}_frame"] = sub["min"]
        base[f"{name}_nframes"] = sub["nunique"]  # >1 => el evento aparece en varios frames

    snap = _pick(base, SNAP_PRIMARY, SNAP_FALLBACK, "snap", "missing_snap")
    throw = _pick(base, THROW_PRIMARY, THROW_FALLBACK, "throw", "missing_pass_forward")
    out = base.join(snap).join(throw).reset_index()

    # Marca de tiempo (auditoría) en el frame del evento elegido.
    tmap = frames.set_index(keys + ["frameId"])["time"]
    for prefix in ("snap", "throw"):
        idx = pd.MultiIndex.from_frame(
            out[keys].assign(frameId=out[f"{prefix}_frame"].astype("float64")).dropna())
        t = tmap.reindex(idx).to_numpy()
        col = pd.Series(pd.NaT, index=out.index, dtype="datetime64[ns, UTC]")
        col.loc[out[f"{prefix}_frame"].notna()] = t
        out[f"{prefix}_time"] = col

    out["sack_event_frame"] = out[[f"{e}_frame" for e in SACK_EVENTS]].min(axis=1).astype("Int32")
    return out


def add_timings(t: pd.DataFrame) -> pd.DataFrame:
    """Añade tiempos desde el snap. Quedan nulos si falta snap o lanzamiento."""
    t = t.copy()
    both = t["snap_frame"].notna() & t["throw_frame"].notna()
    dframes = (t["throw_frame"].astype("float64") - t["snap_frame"].astype("float64"))
    t["throw_before_snap"] = both & (dframes < 0)
    t["snap_to_throw_frames"] = dframes.where(both)
    t["snap_to_throw_s"] = (t["snap_to_throw_frames"] / FPS).where(~t["throw_before_snap"])
    t["valid_throw_time"] = both & ~t["throw_before_snap"]
    # Conflicto manual vs auto (auto - manual, en frames). No cambia la prioridad; solo se señala.
    t["snap_manual_auto_diff_frames"] = (
        t[f"{SNAP_FALLBACK}_frame"].astype("float64") - t[f"{SNAP_PRIMARY}_frame"].astype("float64"))
    t["snap_manual_auto_conflict"] = t["snap_manual_auto_diff_frames"].abs() > 10
    t["snap_to_throw_s_timestamp"] = (t["throw_time"] - t["snap_time"]).dt.total_seconds().where(both)
    return t


def classify_outcome(t: pd.DataFrame, plays: pd.DataFrame) -> pd.DataFrame:
    """Une passResult/dropBackType de plays.csv y etiqueta el tipo de jugada.

    outcome: completion, incompletion, interception, sack, scramble (según passResult).
    no_throw_reason (solo si no hay evento de lanzamiento utilizable):
      sack, scramble, dropback_without_throw_event (C/I/IN sin evento), missing_snap_only.
    """
    cols = ["gameId", "playId", "passResult", "dropBackType", "quarter", "down", "yardsToGo",
            "possessionTeam", "defensiveTeam", "playDescription"]
    m = t.merge(plays[cols], on=da.KEYS_PLAY, how="left", validate="one_to_one")
    m["outcome"] = m["passResult"].map(PASS_RESULT_LABEL)
    has_throw = m["throw_frame"].notna()
    m["no_throw_reason"] = pd.Series(pd.NA, index=m.index, dtype="string")
    nt = ~has_throw
    m.loc[nt & (m["outcome"] == "sack"), "no_throw_reason"] = "sack"
    m.loc[nt & (m["outcome"] == "scramble"), "no_throw_reason"] = "scramble"
    m.loc[nt & m["outcome"].isin(["completion", "incompletion", "interception"]),
          "no_throw_reason"] = "dropback_without_throw_event"
    m["qb_sack_event_present"] = m["sack_event_frame"].notna()
    return m


def build_play_table(game_ids=None) -> pd.DataFrame:
    """Procesa los juegos uno por uno y devuelve la tabla por jugada (≈8.5 mil filas)."""
    parts = [play_event_table(df) for _, df in da.iter_tracking(TRACKING_COLS, game_ids)]
    t = add_timings(pd.concat(parts, ignore_index=True))
    return classify_outcome(t, da.load_plays())
