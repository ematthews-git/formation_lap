"""Pre-season job — recompute CircuitStats for the upcoming season.

Cadence: yearly. Runs after the prior season has fully settled. Reads several closed seasons
of FastF1 data and produces one CircuitStats row per circuit, keyed by the *upcoming* season.

Per circuit it derives: SC / red-flag probabilities, pit loss by condition, the pace feeders
(``pace_metrics``: degradation, warm-up, stop age, overtaking difficulty), and the two-layer
undercut/overcut strength (``undercut``).

Upsert key: CircuitStats UniqueConstraint(circuit_id, season).
"""

from __future__ import annotations

import logging

from sqlalchemy import Connection
from fastf1.exceptions import RateLimitExceededError
import numpy as np

from formation_data import domain, repositories, schema
from formation_data.sources import fastf1_client
from formation_data.jobs.pre_season import pace_metrics, undercut

logger = logging.getLogger(__name__)

HISTORY_SEASONS = 4


def _finite(x) -> float:
    """Coalesce a None/NaN aggregate (no data measured) to 0.0 for non-null storage."""
    return float(x) if x is not None and np.isfinite(x) else 0.0


def run(conn: Connection, *, season: int) -> None:
    """Populates circuit stats.

    Args:
        conn (Connection): Database connection.
        season (int): This is the last season completed.
    """
    rows = []
    try:
        for circuit in repositories.list_circuits(conn):
            sessions_race = _load_history(circuit, season)
            if not sessions_race:
                continue  # suggests new venue
            rows.append(_compute(circuit, sessions_race))
    except RateLimitExceededError:
        # Every session fetched so far is already on FastF1's on-disk cache, and
        # cache hits don't count against the limit — so re-running in ~1h resumes
        # for free. Loading a large history for the first time? Warm the cache in
        # smaller HISTORY_SEASONS chunks spaced an hour apart.
        logger.error(
            "pre_season.circuit_stats: FastF1 rate limit hit while loading %s "
            "seasons; progress is cached on disk, re-run to resume.",
            HISTORY_SEASONS,
        )
        raise

    fields = domain.CircuitStats.model_fields
    items = [
        domain.CircuitStats(season=season, **{k: v for k, v in r.items() if k in fields})
        for r in rows
    ]
    repositories.upsert(conn, schema.circuit_stats, items, ["circuit_id", "season"])

    logger.info(
        "pre_season.circuit_stats.run season=%s circuits=%s history_seasons=%s",
        season,
        len(items),
        HISTORY_SEASONS,
    )


def _load_history(circuit, season: int) -> list:
    """Load the `HISTORY_SEASONS` closed-season race sessions for a circuit."""
    return [
        fastf1_client.get_race_session(s, r)
        for s in range(season - HISTORY_SEASONS, season)
        for r in fastf1_client.rounds_for_location(s, circuit.fastf1_location)
    ]


def _compute(circuit, sessions_race) -> dict:
    """All CircuitStats fields for one circuit, plus diagnostic-only extras.

    The stored undercut comes from the tyre model (`pace_metrics.tyre_model` +
    `undercut.undercut_laptime_swing`). The empirical pair miner is run only as a
    cross-check; its fields (`typical_stop_age`, `emp_swing`, `swap_rate`) are surfaced by
    `diagnose()` but not persisted (`run()` filters to the model's columns).
    """
    pl = _pit_loss_by_condition(sessions_race)
    tyre = pace_metrics.tyre_model(sessions_race)
    deg, warmup = tyre["deg"], tyre["warmup"]
    stop_age = pace_metrics.typical_stop_age(sessions_race)
    difficulty = pace_metrics.overtaking_difficulty(circuit.circuit_id)
    swing = undercut.undercut_laptime_swing(deg, warmup, stop_age)
    emp = undercut.empirical_summary(sessions_race)  # diagnostic cross-check only

    return {
        "circuit_id": circuit.circuit_id,
        "sc_probability": _safety_car_probability(sessions_race),
        "red_flag_probability": _red_flag_probability(sessions_race),
        "pit_loss_normal": pl["normal"]["median_s"] or 0.0,
        "pit_loss_sc": pl["sc"]["median_s"] or 0.0,
        "pit_loss_vsc": pl["vsc"]["median_s"] or 0.0,
        "tyre_deg_rate": _finite(deg),
        "warmup_penalty": _finite(warmup),
        "overtaking_difficulty": difficulty,
        "undercut_laptime_swing": _finite(swing),
        "undercut_sample_size": emp["n"],
        "undercut_strength": undercut.undercut_strength(swing, difficulty),
        "overcut_strength": undercut.overcut_strength(swing, difficulty),
        # diagnostic-only (not persisted):
        "typical_stop_age": stop_age,
        "emp_swing": emp["median_swing"],
        "swap_rate": emp["swap_rate"],
    }


def diagnose(conn: Connection, *, season: int, circuit_id: str | None = None) -> list[dict]:
    """Compute the per-circuit undercut decomposition without writing to the DB.

    Returns one rich row per circuit (all the `_compute` fields). For eyeballing the
    model against the consensus ranking; see `jobs.pre_season.diagnostics`.
    """
    circuits = repositories.list_circuits(conn)
    if circuit_id is not None:
        circuits = [c for c in circuits if c.circuit_id == circuit_id]

    rows = []
    for circuit in circuits:
        sessions_race = _load_history(circuit, season)
        if not sessions_race:
            logger.info("diagnose: no history for %s, skipping", circuit.circuit_id)
            continue
        rows.append(_compute(circuit, sessions_race))
    return rows


def _safety_car_probability(sessions) -> int:
    """Percentage (0-100) of sessions with at least one full SC deployment.

    VSC messages also contain "SAFETY CAR", so they are excluded explicitly.

    Args:
        sessions: non-empty list of loaded FastF1 race sessions.
    """
    if not sessions:
        raise ValueError("sessions must be non-empty")
    count = 0

    for session in sessions:
        rc = session.race_control_messages
        sc_messages = rc[
            rc["Message"].str.contains("SAFETY CAR", na=False)
            & ~rc["Message"].str.contains("VIRTUAL", na=False)
            & rc["Status"].str.contains("DEPLOYED", na=False)
        ]
        if len(sc_messages) != 0:
            count += 1

    return round(100 * count / len(sessions))


def _red_flag_probability(sessions) -> int:
    """Percentage (0-100) of sessions with at least one red flag.

    Args:
        sessions: non-empty list of loaded FastF1 race sessions.
    """
    if not sessions:
        raise ValueError("sessions must be non-empty")
    count = 0

    for session in sessions:
        rc = session.race_control_messages
        # \b guard: "CHEQUERED FLAG" ends every race and contains "RED FLAG"
        red = rc[rc["Message"].str.contains(r"\bRED FLAG", regex=True, na=False)]
        if len(red) != 0:
            count += 1

    return round(100 * count / len(sessions))


def _pit_loss_by_condition(sessions, min_reference_laps=4):
    """
    Strategic pit loss (seconds) under normal / SC / VSC.

    Per stop:
        loss = (inlap_laptime  - field_pace[inlap_number])
             + (outlap_laptime - field_pace[outlap_number])

    Returns {cond: {"median_s": float | None, "n": int}}.
    """
    buckets = {"normal": [], "sc": [], "vsc": []}

    for session in sessions:
        laps = session.laps
        if laps is None or laps.empty:
            continue
        laps = laps.sort_values(["DriverNumber", "LapNumber"]).copy()

        # Reference pace per lap from cars staying out. Deliberately NOT
        # IsAccurate-filtered: SC/VSC laps are flagged "inaccurate" but we
        # need them to form the slow baseline.
        on_track = laps[laps["PitInTime"].isna() & laps["PitOutTime"].isna()]
        agg = on_track.groupby("LapNumber")["LapTime"].agg(["median", "count"])
        ref = agg.loc[agg["count"] >= min_reference_laps, "median"]

        # Lift the following lap (the outlap) onto the inlap row.
        grp = laps.groupby("DriverNumber")
        laps["OutLapTime"] = grp["LapTime"].shift(-1)
        laps["OutLapNumber"] = grp["LapNumber"].shift(-1)
        laps["OutLapPitOut"] = grp["PitOutTime"].shift(-1)
        laps["OutLapStatus"] = grp["TrackStatus"].shift(-1)

        stops = laps[
            laps["PitInTime"].notna()
            & laps["LapTime"].notna()
            & laps["OutLapTime"].notna()
            & laps["OutLapPitOut"].notna()
            & (laps["OutLapNumber"] == laps["LapNumber"] + 1)  # guard dropouts
        ].copy()

        stops["RefIn"] = stops["LapNumber"].map(ref)
        stops["RefOut"] = stops["OutLapNumber"].map(ref)
        stops = stops.dropna(subset=["RefIn", "RefOut"])

        stops["Loss"] = (
            (stops["LapTime"] - stops["RefIn"])
            + (stops["OutLapTime"] - stops["RefOut"])
        ).dt.total_seconds()

        for in_s, out_s, loss in zip(
            stops["TrackStatus"], stops["OutLapStatus"], stops["Loss"]
        ):
            cond = _condition_of(in_s, out_s)
            if cond is not None and loss > 0:  # drop mispaired/negative
                buckets[cond].append(loss)

    return {
        cond: {"median_s": float(np.median(v)) if v else None, "n": len(v)}
        for cond, v in buckets.items()
    }


def _condition_of(in_status, out_status):
    """Bucket a stop by the most significant status across its two laps."""
    blob = f"{in_status or ''}{out_status or ''}"
    if "5" in blob:
        return None
    if "4" in blob:
        return "sc"
    if "6" in blob or "7" in blob:
        return "vsc"
    return "normal"
