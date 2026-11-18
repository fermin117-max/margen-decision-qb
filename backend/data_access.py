"""Acceso de solo lectura a los datos del proyecto (carpeta data/).

Solo usa pandas y numpy (versiones fijadas por el hackathon). Nunca escribe en data/.
El tracking se procesa archivo por archivo: no cargues los 122 CSV a la vez.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Iterable, Iterator

import pandas as pd

# Ruta relativa a la raíz del proyecto (backend/ -> raíz).
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
TRACKING_DIR = DATA_DIR / "tracking"

KEYS_PLAY = ["gameId", "playId"]
KEYS_PLAYER_PLAY = ["gameId", "playId", "nflId"]

TRACKING_COLUMNS = [
    "gameId", "playId", "nflId", "frameId", "time", "jerseyNumber", "team",
    "playDirection", "x", "y", "s", "a", "dis", "o", "dir", "event",
]

# Tipos compactos. nflId es NaN para el balón, por eso Int32 anulable. gameId (~2.0e9) cabe en int32 (máx 2.147e9).
TRACKING_DTYPES: dict[str, str] = {
    "gameId": "int32",
    "playId": "int32",
    "nflId": "Int32",
    "frameId": "int16",
    "jerseyNumber": "Int16",
    "team": "category",
    "playDirection": "category",
    "x": "float32",
    "y": "float32",
    "s": "float32",
    "a": "float32",
    "dis": "float32",
    "o": "float32",
    "dir": "float32",
    "event": "category",
}

# Eventos que el proyecto necesita (se verifican en inspect_dataset.py).
EVENTS_SNAP = ("ball_snap", "autoevent_ballsnap")
EVENTS_THROW = ("pass_forward", "autoevent_passforward")

_TRACKING_RE = re.compile(r"^tracking_(\d+)\.csv$")


def _read(name: str, **kw) -> pd.DataFrame:
    path = DATA_DIR / name
    if not path.is_file():
        raise FileNotFoundError(f"No se encontró {path}")
    return pd.read_csv(path, **kw)


def load_games() -> pd.DataFrame:
    return _read("games.csv")


def load_plays() -> pd.DataFrame:
    return _read("plays.csv", dtype={"gameId": "int32", "playId": "int32"})


def load_players() -> pd.DataFrame:
    return _read("players.csv", dtype={"nflId": "int32"})


def load_pff() -> pd.DataFrame:
    return _read("pffScoutingData.csv", dtype={"gameId": "int32", "playId": "int32", "nflId": "Int32"})


def tracking_files() -> list[Path]:
    """Lista ordenada de CSV de tracking."""
    if not TRACKING_DIR.is_dir():
        raise FileNotFoundError(f"No se encontró {TRACKING_DIR}")
    return sorted(p for p in TRACKING_DIR.iterdir() if _TRACKING_RE.match(p.name))


def game_id_from_path(path: Path) -> int:
    m = _TRACKING_RE.match(path.name)
    if not m:
        raise ValueError(f"Nombre de tracking inesperado: {path.name}")
    return int(m.group(1))


def read_tracking_file(path: Path, usecols: Iterable[str] | None = None) -> pd.DataFrame:
    """Lee un archivo de tracking completo (≈7-10 MB en disco) con tipos compactos."""
    cols = list(usecols) if usecols is not None else None
    dtypes = {k: v for k, v in TRACKING_DTYPES.items() if cols is None or k in cols}
    return pd.read_csv(path, usecols=cols, dtype=dtypes)


def iter_tracking(
    usecols: Iterable[str] | None = None,
    game_ids: Iterable[int] | None = None,
) -> Iterator[tuple[int, pd.DataFrame]]:
    """Genera (gameId, DataFrame) de un juego a la vez. Libera memoria al avanzar."""
    wanted = set(game_ids) if game_ids is not None else None
    for path in tracking_files():
        gid = game_id_from_path(path)
        if wanted is not None and gid not in wanted:
            continue
        yield gid, read_tracking_file(path, usecols)


def reduce_tracking(
    fn: Callable[[pd.DataFrame], pd.DataFrame],
    usecols: Iterable[str] | None = None,
    game_ids: Iterable[int] | None = None,
) -> pd.DataFrame:
    """Aplica fn a cada juego y concatena solo los resultados (deben ser pequeños)."""
    parts = [fn(df) for _, df in iter_tracking(usecols, game_ids)]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def play_event_frames(df: pd.DataFrame, events: Iterable[str]) -> pd.DataFrame:
    """Primer frame de cada jugada para los eventos dados (un valor por gameId/playId)."""
    ev = df.loc[df["event"].isin(list(events)), KEYS_PLAY + ["frameId", "event"]]
    return ev.sort_values(KEYS_PLAY + ["frameId"]).drop_duplicates(KEYS_PLAY)


def mem_mb(df: pd.DataFrame) -> float:
    return float(df.memory_usage(deep=True).sum()) / 1024**2


