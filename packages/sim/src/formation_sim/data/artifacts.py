"""Pluggable source for the per-race derived tables the sim reads.

The sim reads cleaned laps (and, for paramset rebuilds, per-race results/lap1) through this
small store abstraction so the data can come from local disk (the default) OR be injected
from outside. ``formation_data`` registers a database-backed store — via :func:`using_store`
just before a sim run — so CI reads laps from Postgres instead of re-fetching ~110 FastF1
sessions to rebuild the strategy prior and season form.

``formation_sim`` stays DB-free: the DB store lives in ``formation_data`` and only has to
satisfy the :class:`ArtifactStore` protocol. The module-global install/reset pattern mirrors
``data/collector.py`` (``_CACHE_READY`` / ``ensure_cache``).
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator, Protocol, runtime_checkable

import pandas as pd

from formation_sim.settings import resolve_path


@runtime_checkable
class ArtifactStore(Protocol):
    """Return the cached per-race frame for one derived ``kind``, or None if not stored.

    ``kind`` is ``"laps"`` (used at prelim/postquali runtime), or ``"results"`` / ``"lap1"``
    (only reached when a paramset is *rebuilt*). A store may back only some kinds and return
    None for the rest, in which case the caller falls back to its next source.
    """

    def read(self, kind: str, year: int, rnd: int, cfg: dict) -> pd.DataFrame | None: ...


class DiskArtifactStore:
    """Default store: the on-disk ``derived/{kind}_{year}_{rnd:02d}.pkl`` pickles.

    The filename format matches ``clean._derived_path`` (laps) and ``dataset._meta_path``
    (results / lap1); the read is intentionally raw — circuit-name normalisation stays in
    ``clean.get_clean_race`` so disk- and DB-sourced frames are treated identically.
    """

    _KINDS = ("laps", "results", "lap1")

    def read(self, kind: str, year: int, rnd: int, cfg: dict) -> pd.DataFrame | None:
        if kind not in self._KINDS:
            return None
        path = resolve_path(cfg["data"]["derived_dir"]) / f"{kind}_{year}_{rnd:02d}.pkl"
        return pd.read_pickle(path) if path.exists() else None


_DISK_DEFAULT = DiskArtifactStore()
_STORE: ArtifactStore | None = None


def get_store() -> ArtifactStore:
    """The active store — an injected one if set, else the disk default."""
    return _STORE if _STORE is not None else _DISK_DEFAULT


def set_store(store: ArtifactStore | None) -> None:
    global _STORE
    _STORE = store


def reset_store() -> None:
    set_store(None)


@contextmanager
def using_store(store: ArtifactStore) -> Iterator[None]:
    """Install ``store`` for the duration of the block, restoring the prior store on exit."""
    global _STORE
    prev = _STORE
    _STORE = store
    try:
        yield
    finally:
        _STORE = prev
