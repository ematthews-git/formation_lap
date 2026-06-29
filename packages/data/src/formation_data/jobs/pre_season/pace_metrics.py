"""Per-circuit pace feeder metrics — tyre degradation, warm-up, overtaking difficulty.

The tyre model (``tyre_model``: degradation s/lap + cold-tyre warm-up s) is the backbone
of the undercut calculation, so it has to be accurate. The hard part is that within a
single stint ``TyreLife`` and ``LapNumber`` move together, so a per-car ``LapTime~TyreLife``
fit cannot separate degradation from fuel burn and track evolution (it returns negative
"degradation" at processional circuits).

We avoid that entirely with a **cross-car, same-lap** estimate: comparing cars *on the same
lap* cancels fuel load and track state exactly (both are identical that lap), leaving only
the effect of differing tyre age. Concretely, per lap we take each car's pace relative to
the field median (``y``) and its tyre age relative to the field mean (``x``); the pooled
slope ``dy/dx`` — after removing each car's intrinsic quality by within-(session,driver)
demeaning — is degradation. Warm-up falls out as the first-flying-lap pace sitting above
that line. Laps are restricted to dry races, slick compounds and clean air, each of which
otherwise biases the slope (drying tracks read as negative deg; dirty air dilutes it).

Pure functions over loaded FastF1 sessions — no DB or network. Tested in
``tests/test_pace_metrics.py``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from formation_data.jobs.pre_season import pace_model

# A race is treated as wet (and dropped from the tyre model) if at least this fraction of
# laps were run on intermediates/wets — drying-track pace falls over a stint and would read
# as negative degradation.
WET_RACE_FRACTION = 0.15
MIN_LAP_CARS = 4  # cars needed to form a field-median reference for a lap
MIN_DRIVER_LAPS = 4  # clean laps a driver needs to contribute (so demeaning is meaningful)
MIN_POOL = 50  # pooled clean laps needed to trust the degradation slope
MIN_WARMUP_SAMPLES = 15  # first-flying-laps needed to trust the warm-up estimate
MIN_STOP_AGE = 5  # ignore opening-lap/incident stops when measuring typical stop age

# Curated overtaking difficulty, 0 (trivial to pass — Monza slipstream) .. 1 (near
# impossible — Monaco). Stable, well-understood track properties; a data-derived pass count
# is far noisier. Layer 2 scales the undercut swing by this — a big lap-time swing on an
# easy-passing track is reversible and so worth less.
OVERTAKING_DIFFICULTY: dict[str, float] = {
    "monaco": 0.98,
    "singapore": 0.85,
    "hungaroring": 0.85,
    "zandvoort": 0.78,
    "lusail": 0.62,
    "suzuka": 0.60,
    "barcelona": 0.60,
    "abu_dhabi": 0.55,
    "madrid": 0.55,
    "melbourne": 0.50,
    "mexico_city": 0.48,
    "shanghai": 0.45,
    "miami": 0.45,
    "silverstone": 0.45,
    "sao_paulo": 0.42,
    "austin": 0.40,
    "montreal": 0.38,
    "spa": 0.35,
    "red_bull_ring": 0.33,
    "baku": 0.25,
    "las_vegas": 0.25,
    "monza": 0.20,
}
_DEFAULT_OVERTAKING_DIFFICULTY = 0.5


def is_wet_race(session) -> bool:
    """True if a meaningful share of the race ran on intermediate/wet tyres."""
    comp = session.laps["Compound"].dropna()
    return len(comp) > 0 and comp.isin(pace_model.WETS).mean() > WET_RACE_FRACTION


def _clean_pace_residuals(sessions):
    """Pooled (tyre_life, x, y) over dry/slick/clean-air laps, car-quality removed.

    ``y`` = lap time minus the lap's field median (cancels fuel + track evolution);
    ``x`` = tyre age minus the lap's field-mean tyre age. Both are demeaned within each
    (session, driver) so a car's intrinsic pace drops out. The slope of ``y`` on ``x`` is
    degradation; the offset of fresh laps above that line is warm-up.
    """
    tyre, xs, ys = [], [], []
    for si, session in enumerate(sessions):
        if is_wet_race(session):
            continue
        laps = pace_model.clean_air(
            pace_model.slick(pace_model.green_flying(pace_model.to_seconds(session.laps)))
        )
        if laps.empty:
            continue
        g = laps.groupby("LapNumber")["LapTime_s"]
        ref = g.median()[g.count() >= MIN_LAP_CARS]
        mean_age = laps.groupby("LapNumber")["TyreLife"].mean()
        laps = laps[laps["LapNumber"].isin(ref.index)]

        for _, d in laps.groupby("Driver"):
            if len(d) < MIN_DRIVER_LAPS:
                continue
            x = d["TyreLife"].to_numpy() - mean_age.reindex(d["LapNumber"]).to_numpy()
            y = d["LapTime_s"].to_numpy() - ref.reindex(d["LapNumber"]).to_numpy()
            tyre.extend(d["TyreLife"].to_numpy())
            xs.extend(x - x.mean())
            ys.extend(y - y.mean())
    return np.asarray(tyre), np.asarray(xs), np.asarray(ys)


def tyre_model(sessions) -> dict:
    """Degradation (s/lap) and fresh-tyre warm-up penalty (s) for a circuit.

    Returns ``{"deg", "warmup", "n_laps"}``; values are NaN when there is too little
    clean data to estimate them.
    """
    tyre, x, y = _clean_pace_residuals(sessions)
    if len(x) < MIN_POOL or not np.any(x**2):
        return {"deg": float("nan"), "warmup": float("nan"), "n_laps": int(len(x))}

    deg = float((x * y).sum() / (x**2).sum())
    fresh = tyre == 2  # first green flying lap on a new set (out-lap excluded: pit transit)
    if fresh.sum() >= MIN_WARMUP_SAMPLES:
        warmup = max(0.0, float((y[fresh] - deg * x[fresh]).mean()))
    else:
        warmup = float("nan")
    return {"deg": deg, "warmup": warmup, "n_laps": int(len(x))}


def tyre_deg_rate(sessions) -> float:
    """Fuel/evolution-corrected tyre degradation (s/lap). See ``tyre_model``."""
    return tyre_model(sessions)["deg"]


def warmup_penalty(sessions) -> float:
    """Fresh-tyre warm-up penalty (s) — first-flying-lap pace above the deg line."""
    return tyre_model(sessions)["warmup"]


def typical_stop_age(sessions, default: float = 18.0) -> float:
    """Median tyre age (laps) at a normal green slick stop — the worn side of an undercut.

    Restricted to green-flag stops off a slick compound past ``MIN_STOP_AGE`` so SC
    pit-cycles and opening-lap incident stops don't drag it down.
    """
    ages = []
    for session in sessions:
        inlaps = session.laps[session.laps["PitInTime"].notna()]
        for status, compound, age in zip(
            inlaps["TrackStatus"], inlaps["Compound"], inlaps["TyreLife"]
        ):
            if any(c in str(status) for c in "4567"):
                continue  # SC/VSC/red stop
            if compound not in pace_model.SLICKS or pd.isna(age) or age < MIN_STOP_AGE:
                continue
            ages.append(float(age))
    return float(np.median(ages)) if ages else default


def overtaking_difficulty(circuit_id: str) -> float:
    """Curated overtaking difficulty in [0, 1] for ``circuit_id`` (see module dict)."""
    return OVERTAKING_DIFFICULTY.get(circuit_id, _DEFAULT_OVERTAKING_DIFFICULTY)
