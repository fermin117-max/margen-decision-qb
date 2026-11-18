"""Inspección del banco de datos (solo lectura, un archivo de tracking a la vez).

Uso, desde la raíz del proyecto:
    .venv\\Scripts\\python.exe -m backend.inspect_dataset [--json ruta.json]
"""
from __future__ import annotations

import argparse
import json
import os
import time
from collections import Counter, defaultdict

import pandas as pd

from backend import data_access as da

REQUIRED_EVENTS = [*da.EVENTS_SNAP, *da.EVENTS_THROW]


def rss_mb() -> float | None:
    """Memoria residente del proceso (Windows, sin dependencias extra)."""
    try:
        import ctypes
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (n, ctypes.c_size_t) for n in (
                    "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                    "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                    "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]

        pmc = PMC()
        pmc.cb = ctypes.sizeof(PMC)
        k32, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
        psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
        return pmc.PeakWorkingSetSize / 1024**2
    except Exception:
        return None


def describe(df: pd.DataFrame) -> dict:
    return {
        "filas": int(len(df)),
        "columnas": {c: {"dtype": str(df[c].dtype), "nulos": int(df[c].isna().sum())} for c in df.columns},
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="Ruta opcional donde guardar el informe en JSON")
    args = ap.parse_args()
    t0 = time.time()
    rep: dict = {}

    # 1-2. Acceso y archivos
    files = sorted(p for p in da.DATA_DIR.rglob("*") if p.is_file())
    rep["archivos"] = {
        "data_dir": str(da.DATA_DIR),
        "total": len(files),
        "csv": sum(p.suffix.lower() == ".csv" for p in files),
        "no_csv": [str(p.relative_to(da.ROOT)) for p in files if p.suffix.lower() != ".csv"],
        "mb_total": round(sum(p.stat().st_size for p in files) / 1024**2, 1),
        "principales": {p.name: p.stat().st_size for p in da.DATA_DIR.glob("*.csv")},
    }
    tfiles = da.tracking_files()
    sizes = [p.stat().st_size for p in tfiles]
    rep["tracking_archivos"] = {
        "n": len(tfiles),
        "mb_total": round(sum(sizes) / 1024**2, 1),
        "mb_min": round(min(sizes) / 1024**2, 2),
        "mb_max": round(max(sizes) / 1024**2, 2),
        "nombres_inesperados": sorted(
            p.name for p in da.TRACKING_DIR.iterdir() if p not in tfiles),
    }

    # 5. Tablas principales
    games, plays, players, pff = da.load_games(), da.load_plays(), da.load_players(), da.load_pff()
    tables = {"games": games, "plays": plays, "players": players, "pffScoutingData": pff}
    rep["tablas"] = {k: describe(v) for k, v in tables.items()}

    # 6. Llaves
    rep["llaves"] = {
        "games.gameId_unico": bool(games["gameId"].is_unique),
        "plays(gameId,playId)_unico": bool(not plays.duplicated(da.KEYS_PLAY).any()),
        "players.nflId_unico": bool(players["nflId"].is_unique),
        "pff(gameId,playId,nflId)_duplicados": int(pff.duplicated(da.KEYS_PLAYER_PLAY).sum()),
        "plays_con_gameId_inexistente_en_games": int((~plays["gameId"].isin(games["gameId"])).sum()),
        "pff_jugadas_no_en_plays": int(
            (~pff.set_index(da.KEYS_PLAY).index.isin(plays.set_index(da.KEYS_PLAY).index)).sum()),
        "pff_nflId_no_en_players": int((~pff["nflId"].dropna().isin(players["nflId"])).sum()),
    }

    # 7-8. Tracking por archivo
    play_keys = set(map(tuple, plays[da.KEYS_PLAY].to_numpy().tolist()))
    player_ids = set(players["nflId"].tolist())
    first_cols: list[str] | None = None
    schema_mismatch, dtype_seen = [], defaultdict(set)
    nulls, rows_total = Counter(), 0
    events = Counter()
    games_in_files, name_vs_content = set(), []
    tracking_play_keys: set = set()
    dup_rows = 0
    nonmono = 0
    unknown_nfl: set = set()
    plays_by_event: Counter = Counter()  # nº de jugadas con cada evento
    plays_missing_snap, plays_missing_throw = 0, 0
    max_df_mb = 0.0
    per_game_plays: dict[int, int] = {}
    ranges = {"x": [1e9, -1e9], "y": [1e9, -1e9], "s": [1e9, -1e9]}
    teams, directions = Counter(), Counter()

    for gid_name, df in da.iter_tracking():
        max_df_mb = max(max_df_mb, da.mem_mb(df))
        rows_total += len(df)
        cols = list(df.columns)
        first_cols = first_cols or cols
        if cols != first_cols:
            schema_mismatch.append(gid_name)
        for c in cols:
            dtype_seen[c].add(str(df[c].dtype))
        nulls.update({c: int(n) for c, n in df.isna().sum().items() if n})
        ids = set(df["gameId"].unique().tolist())
        games_in_files |= ids
        if ids != {gid_name}:
            name_vs_content.append({"archivo": gid_name, "gameIds_en_contenido": sorted(ids)})
        dup_rows += int(df.duplicated(da.KEYS_PLAYER_PLAY + ["frameId"]).sum())
        g = df.groupby(da.KEYS_PLAY + ["nflId"], dropna=False, observed=True)["frameId"]
        nonmono += int((g.diff().dropna() != 1).sum())
        keys = set(map(tuple, df[da.KEYS_PLAY].drop_duplicates().to_numpy().tolist()))
        tracking_play_keys |= keys
        per_game_plays[gid_name] = len(keys)
        unknown_nfl |= set(df["nflId"].dropna().unique().tolist()) - player_ids
        events.update(df["event"].dropna().astype(str).value_counts().to_dict())
        ev_play = df.dropna(subset=["event"]).groupby(da.KEYS_PLAY, observed=True)["event"]
        sets = ev_play.agg(lambda s: set(s.astype(str)))
        for st in sets:
            plays_by_event.update(st)
        plays_missing_snap += len(keys) - int(sets.map(lambda s: bool(s & set(da.EVENTS_SNAP))).sum())
        plays_missing_throw += len(keys) - int(sets.map(lambda s: bool(s & set(da.EVENTS_THROW))).sum())
        for c in ranges:
            ranges[c][0] = min(ranges[c][0], float(df[c].min()))
            ranges[c][1] = max(ranges[c][1], float(df[c].max()))
        teams.update(df["team"].astype(str).value_counts().to_dict())
        directions.update(df["playDirection"].astype(str).value_counts().to_dict())

    # Muestra de formato de 'time' (columna no cargada con dtype; se lee solo una fila)
    sample = pd.read_csv(tfiles[0], nrows=3)
    game_ids_games = set(games["gameId"].tolist())
    rep["tracking"] = {
        "archivos_leidos": len(tfiles),
        "filas_totales": rows_total,
        "columnas": first_cols,
        "archivos_con_esquema_distinto": schema_mismatch,
        "dtypes_por_columna": {c: sorted(v) for c, v in dtype_seen.items()},
        "nulos_por_columna": dict(nulls),
        "duplicados_(game,play,nfl,frame)": dup_rows,
        "saltos_o_repeticiones_de_frameId": nonmono,
        "gameIds_en_tracking": len(games_in_files),
        "juegos_en_games.csv": len(game_ids_games),
        "juegos_con_tracking_y_sin_games": sorted(games_in_files - game_ids_games),
        "juegos_en_games_sin_tracking": sorted(game_ids_games - games_in_files),
        "archivos_cuyo_nombre_no_coincide_con_gameId": name_vs_content,
        "jugadas_distintas_en_tracking": len(tracking_play_keys),
        "jugadas_tracking_no_en_plays": len(tracking_play_keys - play_keys),
        "jugadas_en_plays_sin_tracking": len(play_keys - tracking_play_keys),
        "nflId_de_tracking_no_en_players": sorted(map(int, unknown_nfl)),
        "rangos_x_y_s": ranges,
        "equipos": dict(teams),
        "playDirection": dict(directions),
        "muestra_time": sample["time"].tolist(),
        "dataframe_mas_grande_MB": round(max_df_mb, 1),
    }
    rep["eventos"] = {
        "frames_por_evento": dict(events.most_common()),
        "jugadas_con_cada_evento": dict(plays_by_event.most_common()),
        "requeridos_presentes": {e: e in events for e in REQUIRED_EVENTS},
        "jugadas_sin_ball_snap_ni_autoevent_ballsnap": plays_missing_snap,
        "jugadas_sin_pass_forward_ni_autoevent_passforward": plays_missing_throw,
    }
    rep["jugadas"] = {
        "n_juegos_games.csv": int(games["gameId"].nunique()),
        "n_jugadas_plays.csv": int(len(plays)),
        "passResult": plays["passResult"].value_counts(dropna=False).to_dict(),
        "dropBackType": plays["dropBackType"].value_counts(dropna=False).to_dict(),
    }
    rep["rendimiento"] = {
        "segundos": round(time.time() - t0, 1),
        "pico_memoria_proceso_MB": round(rss_mb() or -1, 0),
        "os_cpu_count": os.cpu_count(),
    }

    text = json.dumps(rep, indent=2, ensure_ascii=False, default=str)
    print(text)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            f.write(text)


if __name__ == "__main__":
    main()
