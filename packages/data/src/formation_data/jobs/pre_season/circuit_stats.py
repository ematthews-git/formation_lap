"""Pre-season job — recompute CircuitStats for the upcoming season.

Cadence: yearly. Runs after the prior season has fully settled. Reads several closed seasons
of FastF1 data and produces one CircuitStats row per circuit, keyed by the *upcoming* season.

Upsert key: CircuitStats UniqueConstraint(circuit_id, season).
"""

from __future__ import annotations

import logging

from sqlalchemy import Connection
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

HISTORY_SEASONS = 5
FUEL_RATE = -0.06  # s/lap of pace improvement from burning fuel


def run(conn: Connection, *, season: int) -> None:
    # TODO:
    #   from formation_data import domain, repositories, schema
    #   from formation_data.sources import fastf1_client
    #   items = []
    #   for circuit in repositories.list_circuits(conn):
    #       sessions = [
    #           fastf1_client.get_race_session(s, _round_for(circuit, s))
    #           for s in range(season - HISTORY_SEASONS, season)
    #           if _round_for(circuit, s) is not None
    #       ]
    #       if not sessions:
    #           continue  # new venue (e.g. madrid in 2026) — no history yet
    #       items.append(domain.CircuitStats(
    #           circuit_id=circuit.circuit_id, season=season,
    #           sc_probability=_safety_car_probability(sessions),
    #           red_flag_probability=_red_flag_probability(sessions),
    #           pit_loss_normal=..., pit_loss_sc=..., pit_loss_vsc=...,
    #           undercut_strength=..., overcut_strength=...,
    #       ))
    #   repositories.upsert(conn, schema.circuit_stats, items, ["circuit_id", "season"])
    logger.info(
        "pre_season.circuit_stats.run season=%s (skeleton — would aggregate %s prior seasons)",
        season,
        HISTORY_SEASONS,
    )


def _safety_car_probability(sessions) -> int:
    """Percentage (0-100) of sessions with at least one full SC deployment.

    VSC messages also contain "SAFETY CAR", so they are excluded explicitly.
    Stored as int percent per the CircuitStats schema. Recommend 5 race sessions.

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

    Stored as int percent per the CircuitStats schema. Recommend 5 race sessions.

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


def _undercut_strength(session, fuel_rate=FUEL_RATE):
    """Circuit undercut strength (s): the tyre-degradation engine of the undercut."""
    df = _fresh_tyre_advantage(session, fuel_rate)
    vals = df.loc[
        df["fresh_adv"] > -0.5, "fresh_adv"
    ]  # drop off-plan / anomalous switches
    return float(np.median(vals)), df


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


def _overcut_strength():
    pass
