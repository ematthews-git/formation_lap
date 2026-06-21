"""Pre-season job — recompute CircuitStats for the upcoming season.

Cadence: yearly. Runs after the prior season has fully settled. Reads several closed seasons
of FastF1 data and produces one CircuitStats row per circuit, keyed by the *upcoming* season.

Upsert key: CircuitStats UniqueConstraint(circuit_id, season).
"""

from __future__ import annotations

import logging

from sqlalchemy import Connection
from fastf1.exceptions import RateLimitExceededError
import pandas as pd
import numpy as np

from formation_data import domain, repositories, schema
from formation_data.sources import fastf1_client

logger = logging.getLogger(__name__)

HISTORY_SEASONS = 4
FUEL_RATE = -0.06  # s/lap of pace improvement from burning fuel


def run(conn: Connection, *, season: int) -> None:
    """Populates circuit stats.

    Args:
        conn (Connection): Database connection.
        season (int): This is the last season completed.
    """
    items = []
    try:
        for circuit in repositories.list_circuits(conn):
            sessions_race = [
                fastf1_client.get_race_session(s, r)
                for s in range(season - HISTORY_SEASONS, season)
                for r in fastf1_client.rounds_for_location(s, circuit.fastf1_location)
            ]
            if not sessions_race:
                continue  # suggests new venue

            pl = _pit_loss_by_condition(sessions_race)

            items.append(
                domain.CircuitStats(
                    circuit_id=circuit.circuit_id,
                    season=season,
                    sc_probability=_safety_car_probability(sessions_race),
                    red_flag_probability=_red_flag_probability(sessions_race),
                    pit_loss_normal=pl["normal"]["median_s"] or 0.0,
                    pit_loss_sc=pl["sc"]["median_s"] or 0.0,
                    pit_loss_vsc=pl["vsc"]["median_s"] or 0.0,
                    undercut_strength=_undercut_strength(sessions_race),
                    overcut_strength=0,
                )
            )
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

    repositories.upsert(conn, schema.circuit_stats, items, ["circuit_id", "season"])

    logger.info(
        "pre_season.circuit_stats.run season=%s circuits=%s history_seasons=%s",
        season,
        len(items),
        HISTORY_SEASONS,
    )


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


def _undercut_strength(sessions, fuel_rate=FUEL_RATE) -> float:
    """Circuit undercut strength (s): the tyre-degradation engine of the undercut.

    Args:
        sessions: non-empty list of loaded FastF1 race sessions.
        fuel_rate: pace improvement per lap from burning fuel (s/lap).
    """
    if not sessions:
        raise ValueError("sessions must be non-empty")
    vals = []
    for session in sessions:
        df = _fresh_tyre_advantage(session, fuel_rate)
        if df.empty:
            continue
        # drop off-plan / anomalous switches
        vals.extend(df.loc[df["fresh_adv"] > -0.5, "fresh_adv"].tolist())
    return float(np.median(vals))


def _overcut_strength():
    pass


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


# --- HELPER FUNCTIONS ---


def _green_flying(laps):
    """Green-flag flying laps: valid time, no in/out-lap, no SC/VSC/red, TyreLife>1."""
    d = laps.copy()
    d["LapTime_s"] = d["LapTime"].dt.total_seconds()
    return d[
        d["LapTime_s"].notna()
        & d["PitInTime"].isna()
        & d["PitOutTime"].isna()
        & ~d["TrackStatus"].astype(str).str.contains("[4567]", regex=True)
        & (d["TyreLife"] > 1)
    ]


def _fresh_tyre_advantage(session, fuel_rate=FUEL_RATE, n=3):
    """One row per clean green-flag pit stop: fuel-corrected pace gain from worn
    tyres (last `n` laps before the in-lap) to fresh (laps 2..n+1 after the out-lap).

    Keys off PitInTime/PitOutTime + TyreLife only — never the unreliable Stint
    counter.
    """
    gf = _green_flying(session.laps)
    rows = []

    for drv, dall in session.laps.groupby("Driver"):
        dall = dall.sort_values("LapNumber")
        g = gf[gf["Driver"] == drv]

        for L in dall.loc[dall["PitInTime"].notna(), "LapNumber"]:
            worn = g[(g["LapNumber"] >= L - n) & (g["LapNumber"] < L)]
            fresh = g[
                (g["LapNumber"] > L + 1) & (g["LapNumber"] <= L + 1 + n)
            ]  # skip out-lap

            if len(worn) < 2 or len(fresh) < 2:
                continue

            dlap = fresh["LapNumber"].mean() - worn["LapNumber"].mean()

            # project both pools to a common fuel load, then take the tyre delta
            adv = (
                worn["LapTime_s"].median() - fresh["LapTime_s"].median()
            ) + fuel_rate * dlap
            from_comp = (
                worn["Compound"].dropna().iloc[-1]
                if worn["Compound"].notna().any()
                else None
            )
            rows.append(
                {
                    "drv": drv,
                    "pit_lap": int(L),
                    "from": from_comp,
                    "fresh_adv": round(adv, 3),
                }
            )

    return pd.DataFrame(rows)


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
