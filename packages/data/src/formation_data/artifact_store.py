"""Database-backed ArtifactStore for the simulator, plus the dump helpers that fill it.

``formation_sim`` reads cleaned per-race laps through its ArtifactStore seam
(``formation_sim.data.artifacts``). :class:`DbArtifactStore` satisfies that protocol from
Postgres: it returns the Parquet-serialized ``laps`` frame for a race, so a sim run in CI reads
laps from the DB instead of re-fetching ~110 FastF1 sessions to rebuild the strategy prior and
season form. It's registered via ``artifacts.using_store`` right before a sim call (see
``jobs.pre_race.sim_strategies``). Living here keeps ``formation_sim`` DB-free.

The dump helpers serialize the sim's on-disk ``laps_*.pkl`` frames into ``derived_artifacts``:
``dump_all_local_laps`` for the one-time history backfill, ``dump_race_laps`` for keeping the
current season fresh (fetching + cleaning a race first if it isn't cached).
"""
from __future__ import annotations

import io
import re

import pandas as pd
from sqlalchemy import Connection

from formation_data import repositories

_LAPS_RE = re.compile(r"^laps_(\d{4})_(\d{2})\.pkl$")


class DbArtifactStore:
    """Reads serialized per-race derived tables from ``derived_artifacts``.

    Backs ``kind="laps"``; returns ``None`` for other kinds so the sim falls back to
    disk / FastF1. Holds the caller's live ``Connection`` — reads run inside that transaction.
    """

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def read(self, kind: str, year: int, rnd: int, cfg: dict) -> pd.DataFrame | None:
        if kind != "laps":
            return None
        row = repositories.get_derived_artifact(
            self._conn, kind=kind, year=year, round_number=rnd
        )
        if row is None:
            return None
        return pd.read_parquet(io.BytesIO(row.data))


def _to_parquet_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    return buf.getvalue()


def dump_race_laps(
    conn: Connection, season: int, round_number: int, cfg: dict | None = None
) -> bool:
    """Store one race's cleaned laps, fetching + cleaning it first if not already cached.

    Returns True if a frame was stored, False if the race has no usable data. Runs outside any
    ``using_store`` block, so ``get_clean_race`` reads disk / FastF1 (never the DB it's filling).
    """
    from formation_sim.data import clean

    df = clean.get_clean_race(season, round_number, cfg)
    if df is None or not len(df):
        return False
    repositories.upsert_derived_artifact(
        conn, kind="laps", year=season, round_number=round_number, data=_to_parquet_bytes(df)
    )
    return True


def dump_all_local_laps(conn: Connection, cfg: dict | None = None) -> int:
    """Dump every local ``laps_*.pkl`` under the sim's derived dir. Returns the count stored."""
    from formation_sim.settings import load_settings, resolve_path

    cfg = cfg or load_settings()
    derived = resolve_path(cfg["data"]["derived_dir"])
    n = 0
    for path in sorted(derived.glob("laps_*.pkl")):
        m = _LAPS_RE.match(path.name)
        if not m:
            continue
        year, rnd = int(m.group(1)), int(m.group(2))
        df = pd.read_pickle(path)
        repositories.upsert_derived_artifact(
            conn, kind="laps", year=year, round_number=rnd, data=_to_parquet_bytes(df)
        )
        n += 1
    return n
