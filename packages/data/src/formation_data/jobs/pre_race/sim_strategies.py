"""Pre-race job — simulate strategy options for an upcoming race.

Runs the strategy simulator (``formation_sim``) and persists the **race-level shown-5**
(the strategies most likely to actually be run) plus the derived **race-context stats**.

Two modes:
- **prelim**    — pre-weekend, season form only. Generated at the end of the *previous*
                  weekend so an early projection is ready.
- **postquali** — grid + quali pace known. Generated ~2h30 after Qualifying starts,
                  superseding the prelim projection.

Sim rows are tagged ``source="sim"``; the historical miner's rows (``source="historical"``,
see ``jobs.pre_race.strategies``) are left untouched, so both remain available. The
race-context numbers land in ``sim_race_stats`` as a single JSONB blob.

Because each run replaces the weekend's sim rows, the ``strategies`` table always holds the
latest phase; the ``phase`` column records which run produced it.

Upsert keys:
- Strategy       UniqueConstraint(race_weekend_id, source, label)
- StrategyStint  UniqueConstraint(strategy_id, stint_order)
- SimRaceStats   UniqueConstraint(race_weekend_id)
"""

from __future__ import annotations

import logging

from sqlalchemy import Connection

from formation_data import domain, repositories

logger = logging.getLogger(__name__)

MODES = ("prelim", "postquali")


def run(
    conn: Connection,
    *,
    season: int,
    round_number: int,
    mode: str,
    n_sims: int | None = None,
    source: str = "disk",
) -> None:
    """Simulate and persist strategy options for (season, round_number) in `mode`.

    `n_sims` overrides the simulator's configured Monte-Carlo count (None = its default).
    `source` selects where the sim reads its cleaned per-race laps: "disk" (local pkl / live
    FastF1, the default) or "db" (the `derived_artifacts` table via `DbArtifactStore`), the
    latter used in CI so the strategy prior + season form don't re-fetch ~110 FastF1 sessions.
    """
    if mode not in MODES:
        raise ValueError(f"unknown sim mode {mode!r} (expected one of {MODES})")
    if source not in ("disk", "db"):
        raise ValueError(f"unknown source {source!r} (expected 'disk' or 'db')")

    rw = repositories.get_race_weekend(conn, season, round_number)
    if rw is None:
        logger.warning(
            "pre_race.sim_strategies.run: no race weekend %s R%s; nothing to do",
            season,
            round_number,
        )
        return

    circuit = repositories.get_circuit(conn, rw.circuit_id)
    if circuit is None:
        logger.warning(
            "pre_race.sim_strategies.run: weekend %s R%s references unknown circuit "
            "%s; nothing to do",
            season,
            round_number,
            rw.circuit_id,
        )
        return

    # Imported lazily: the sim pulls in its own heavy deps and target-race FastF1 data,
    # neither of which the non-sim jobs sharing this process should pay for.
    from formation_sim.api import simulate_race
    from formation_sim.data import artifacts

    if source == "db":
        # Read cleaned laps from Postgres (this open transaction) for the duration of the run,
        # so the sim never touches the FastF1 network for history / season form.
        from formation_data.artifact_store import DbArtifactStore

        with artifacts.using_store(DbArtifactStore(conn)):
            result = simulate_race(mode, season, round_number, n_sims=n_sims)
    else:
        result = simulate_race(mode, season, round_number, n_sims=n_sims)
    shown = result["shown"]
    if not shown:
        logger.warning(
            "pre_race.sim_strategies.run: sim produced no strategies for %s R%s (%s); "
            "nothing written",
            season,
            round_number,
            mode,
        )
        return

    repositories.delete_strategies_for_weekend(conn, rw.id, source="sim")
    for entry in shown:
        strategy, stints = _build_strategy(rw.id, circuit.num_laps, entry, mode)
        repositories.upsert_strategy_with_stints(conn, strategy, stints)

    repositories.upsert_sim_race_stats(
        conn,
        rw.id,
        phase=mode,
        stats={
            "meta": result["meta"],
            "circuit_profile": result["circuit_profile"],
            "race_stats": result["race_stats"],
        },
    )

    logger.info(
        "pre_race.sim_strategies.run season=%s round=%s circuit=%s mode=%s "
        "strategies=%d (base=%s)",
        season,
        round_number,
        circuit.circuit_id,
        mode,
        len(shown),
        "->".join(shown[0]["compounds"]),
    )


# --- persistence shaping ---


def _build_strategy(
    race_weekend_id: int, race_laps: int, entry: dict, mode: str
) -> tuple[domain.Strategy, list[domain.StrategyStint]]:
    """Turn one shown sim strategy into a Strategy + its StrategyStints."""
    compounds: list[str] = entry["compounds"]
    num_stops: int = entry["n_stops"]
    windows = entry.get("pit_windows") or []

    strategy = domain.Strategy(
        race_weekend_id=race_weekend_id,
        source="sim",
        phase=mode,
        is_base=entry["rank"]
        == 1,  # field_display's top-q strategy = the recommendation
        num_stops=num_stops,
        label="->".join(compounds),
        plausibility=entry.get("plausibility"),
        tier=entry.get("tier"),
    )

    stints: list[domain.StrategyStint] = []
    for order, compound in enumerate(compounds, start=1):
        if order <= num_stops and order - 1 < len(windows):
            start, end = _clamp(
                int(windows[order - 1][0]), int(windows[order - 1][1]), race_laps
            )
        else:
            # Final stint runs to the flag — no pit window, pin to race end.
            start = end = race_laps
        stints.append(
            domain.StrategyStint(
                strategy_id=0,  # replaced in upsert_strategy_with_stints
                stint_order=order,
                compound=compound,
                pit_lap_window_start=start,
                pit_lap_window_end=end,
            )
        )
    return strategy, stints


def _clamp(lo: int, hi: int, race_laps: int) -> tuple[int, int]:
    """Clamp a [lo, hi] pit-window lap range into [1, race_laps], lo ≤ hi."""
    lo = max(1, min(lo, race_laps))
    hi = max(lo, min(hi, race_laps))
    return lo, hi
