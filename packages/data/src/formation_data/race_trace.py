"""Lap-by-lap race trace — pure reduction of one race to the RACE_TRACE panel's blob.

Given the tidy per-race frames the collector already produces (``session_laps`` /
``session_results``) plus its per-lap rainfall map, :func:`build_trace` reduces one race
to a single JSON-friendly document: per-lap track status, weather, excitement index and
on-track overtakes, plus every starter's lap times, pit laps and the team they drove for
in THAT race. The team snapshot is the point — the frontend colours lines from the blob,
never from the current season's lineup, so lookbacks show period-correct teams.

Nothing here touches FastF1, the DB, or the sim — it's pure pandas/numpy over the
canonical frames (and, for overtakes, the collector's per-driver telemetry progress),
so it's unit-testable with fabricated DataFrames (same contract as ``race_metrics``).
Conventions:
  * per-lap arrays are lists of length ``total_laps``, index 0 = lap 1;
  * track status is one of ``green | yellow | vsc | sc | red`` (worst status any car saw
    on that lap wins, red > sc > vsc > yellow);
  * weather is ``dry | damp | wet`` from rainfall + the field's tyre choice;
  * overtakes are telemetry-based durable on-track passes (see :func:`overtakes_by_lap`),
    the single source of truth shared with ``circuit_race_stats`` so the two feeds agree;
  * the excitement index is a 0–100 composite; weights live in the ``_EXC_*`` constants
    and the blob carries ``version`` so the recipe can evolve without ambiguity.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from formation_data.race_metrics import _b, passes_by_lap

TRACE_VERSION = 1

# A race must have actually raced to be worth tracing: fewer green laps than this and
# the pace pane would be wall-to-wall interpolation (2021 Spa: two laps behind the SC).
_MIN_GREEN_LAPS = 5

# On-track overtake counting (telemetry-based durable lead changes).
OVERTAKE_DWELL_S = (
    8.0  # a swap must hold this long to count (filters side-by-side scraps)
)
_OVERTAKE_GRID_S = 0.5  # running-order sampling step

# --------------------------------------------------------------------- excitement weights
_EXC_BASE = 15.0
_EXC_PER_OVERTAKE = 6.0
_EXC_LAP1 = 35.0  # standing start
_EXC_SC_DEPLOY = 35.0  # something just happened
_EXC_SC_RUNNING = -8.0  # trundling behind the SC is dull
_EXC_VSC_DEPLOY = 18.0
_EXC_RESTART = 40.0  # bunched field, cold tyres
_EXC_RAIN_START = 28.0
_EXC_RAIN_RUNNING = 10.0
_EXC_PIT_PER_STOP = 3.0  # pit-window action
_EXC_PIT_CAP = 12.0
_EXC_GAP_WINDOW = 10  # final N laps where a close lead fight builds tension
_EXC_GAP_THRESHOLD_S = 2.5
_EXC_GAP_PER_S = 8.0
_EXC_GAP_CAP = 20.0


def _total_laps(laps: pd.DataFrame) -> int:
    if not len(laps):
        return 0
    m = np.nanmax(laps["lap_number"].to_numpy(dtype=float))
    return int(m) if np.isfinite(m) else 0


def overtakes_by_lap(
    progress: dict[str, pd.DataFrame],
    laps: pd.DataFrame,
    *,
    dwell_s: float = OVERTAKE_DWELL_S,
    grid_step_s: float = _OVERTAKE_GRID_S,
) -> dict[int, int]:
    """On-track overtakes per lap, as telemetry-based durable lead changes.

    ``progress`` is the collector's per-driver ``(t, prog, lap)`` frames
    (:func:`formation_sim.data.collector.driver_progress`); ``laps`` its
    ``session_laps`` frame, used for the per-lap exclusion flags. All drivers are
    resampled onto a common time grid, and for each pair every order swap that then
    holds ``>= dwell_s`` is counted once, credited to the lap it completes on —
    excluding swaps while either car is on a pit in/out lap or under SC/VSC/red
    (bunched or non-racing running). This catches restart-shuffle and near-pit passes
    the lap-line method misses, while the dwell suppresses side-by-side flip-flopping.

    Falls back to the lap-resolution :func:`race_metrics.passes_by_lap` when telemetry
    progress is unavailable, so a race with no telemetry still yields a count (the same
    fallback both callers get, keeping the trace and circuit-stats feeds consistent).
    """
    total_laps = _total_laps(laps)
    if not progress or total_laps < 1:
        return passes_by_lap(laps)

    # Per-(driver, lap) exclusion flags.
    flags = laps.copy()
    for col in ("is_sc", "is_vsc", "is_red", "is_inlap", "is_outlap"):
        flags[col] = _b(flags[col])
    flags = flags.set_index(["driver", "lap_number"])

    def excluded(drv: str, lap: int) -> bool:
        try:
            r = flags.loc[(drv, float(lap))]
        except KeyError:
            return False
        if isinstance(r, pd.DataFrame):
            r = r.iloc[0]
        return bool(
            r["is_inlap"] or r["is_outlap"] or r["is_sc"] or r["is_vsc"] or r["is_red"]
        )

    t_min = min(df["t"].iloc[0] for df in progress.values())
    t_max = max(df["t"].iloc[-1] for df in progress.values())
    if not (np.isfinite(t_min) and np.isfinite(t_max)) or t_max <= t_min:
        return passes_by_lap(laps)
    grid = np.arange(t_min, t_max, grid_step_s)

    codes = list(progress)
    prog = {
        c: np.interp(
            grid, progress[c]["t"], progress[c]["prog"], left=np.nan, right=np.nan
        )
        for c in codes
    }
    lapg = {
        c: np.interp(
            grid, progress[c]["t"], progress[c]["lap"], left=np.nan, right=np.nan
        )
        for c in codes
    }
    min_run = max(1, int(round(dwell_s / grid_step_s)))

    per_lap: dict[int, int] = {}
    n = len(grid)
    for ia in range(len(codes)):
        a = codes[ia]
        for ib in range(ia + 1, len(codes)):
            b = codes[ib]
            d = prog[a] - prog[b]
            valid = np.isfinite(d)
            if valid.sum() < min_run:
                continue
            sign = np.where(d > 0, 1, np.where(d < 0, -1, 0))
            confirmed: int | None = None
            i = 0
            while i < n:
                if not valid[i] or sign[i] == 0:
                    i += 1
                    continue
                j = i
                while j < n and valid[j] and sign[j] == sign[i]:
                    j += 1
                if j - i >= min_run:  # a run long enough to be a settled order
                    if confirmed is not None and sign[i] != confirmed:
                        la, lb = lapg[a][i], lapg[b][i]
                        present = [v for v in (la, lb) if np.isfinite(v)]
                        lp = int(round(min(present))) if present else -1
                        # Lap 1 is excluded: a standing start packs the field within
                        # metres at near-identical progress, so the launch scramble
                        # generates dozens of spurious durable crossings (and F1's own
                        # overtake stats exclude the start too — it isn't "overtaking").
                        # The start shuffle is captured separately by the lap-1 position
                        # changes; SC-start races race from a later restart lap, which is
                        # green and counts normally.
                        if (
                            2 <= lp <= total_laps
                            and not excluded(a, lp)
                            and not excluded(b, lp)
                        ):
                            per_lap[lp] = per_lap.get(lp, 0) + 1
                    confirmed = int(sign[i])
                i = j
    return per_lap


def status_by_lap(laps: pd.DataFrame, total_laps: int) -> list[str]:
    """Collapse the per-driver-lap status flags to one race-level status per lap.

    ``any`` across the cars running that lap, worst status wins — a deployment mid-lap
    flags the whole lap, which is what a lap-resolution strip can honestly show.
    """
    flags = pd.DataFrame(
        {
            "lap": laps["lap_number"].astype(float),
            "red": _b(laps["is_red"]),
            "sc": _b(laps["is_sc"]),
            "vsc": _b(laps["is_vsc"]),
            "yellow": _b(laps["is_yellow"]),
        }
    )
    by_lap = flags.groupby("lap").any()
    out: list[str] = []
    for lap in range(1, total_laps + 1):
        if lap not in by_lap.index:
            out.append("green")
            continue
        row = by_lap.loc[lap]
        if row["red"]:
            out.append("red")
        elif row["sc"]:
            out.append("sc")
        elif row["vsc"]:
            out.append("vsc")
        elif row["yellow"]:
            out.append("yellow")
        else:
            out.append("green")
    return out


def weather_by_lap(
    laps: pd.DataFrame, lap_rainfall: dict[int, bool] | None, total_laps: int
) -> list[str]:
    """dry / damp / wet per lap from rainfall and what the field is running.

    Tyre choice is the ground truth for track state (rain sensors miss a drying or
    soaked track): a majority on full wets → wet; a majority on inters/wets, or rain
    falling → damp; otherwise dry.
    """
    rain = lap_rainfall or {}
    comp = pd.DataFrame(
        {
            "lap": laps["lap_number"].astype(float),
            "compound": laps["compound"].astype("string"),
        }
    ).dropna(subset=["lap"])
    out: list[str] = []
    for lap in range(1, total_laps + 1):
        c = comp.loc[comp["lap"] == lap, "compound"].dropna()
        wet_share = float((c == "WET").mean()) if len(c) else 0.0
        inter_share = float(c.isin(["INTERMEDIATE", "WET"]).mean()) if len(c) else 0.0
        if wet_share > 0.5:
            out.append("wet")
        elif inter_share > 0.5 or rain.get(lap, False):
            out.append("damp")
        else:
            out.append("dry")
    return out


def _front_gap_by_lap(laps: pd.DataFrame, total_laps: int) -> list[float]:
    """P1→P2 gap (s) per lap from cumulative race time, NaN where undefined.

    Cars are compared at equal laps completed (the standard race-trace gap); a car
    missing any earlier lap time drops out of the comparison from that lap on.
    """
    piv = laps.pivot_table(
        index="lap_number", columns="driver", values="lap_time_s", aggfunc="first"
    ).sort_index()
    piv = piv.reindex(range(1, total_laps + 1))
    cum = piv.cumsum(skipna=False)
    out: list[float] = []
    for lap in range(1, total_laps + 1):
        row = (
            cum.loc[lap].dropna().sort_values()
            if lap in cum.index
            else pd.Series(dtype=float)
        )
        out.append(float(row.iloc[1] - row.iloc[0]) if len(row) >= 2 else float("nan"))
    return out


def _excitement(
    status: list[str],
    weather: list[str],
    overtakes: list[int],
    pit_counts: list[int],
    front_gap: list[float],
    total_laps: int,
) -> list[int]:
    out: list[int] = []
    for i in range(total_laps):
        lap = i + 1
        s, prev = status[i], status[i - 1] if i > 0 else "green"
        v = _EXC_BASE + _EXC_PER_OVERTAKE * overtakes[i]
        if lap == 1:
            v += _EXC_LAP1
        if s == "sc":
            v += _EXC_SC_DEPLOY if prev != "sc" else _EXC_SC_RUNNING
        if s == "vsc" and prev != "vsc":
            v += _EXC_VSC_DEPLOY
        if prev == "sc" and s != "sc":
            v += _EXC_RESTART
        if weather[i] != "dry":
            was_dry = i == 0 or weather[i - 1] == "dry"
            v += _EXC_RAIN_START if was_dry else _EXC_RAIN_RUNNING
        v += min(_EXC_PIT_PER_STOP * pit_counts[i], _EXC_PIT_CAP)
        gap = front_gap[i]
        if (
            lap > total_laps - _EXC_GAP_WINDOW
            and np.isfinite(gap)
            and gap < _EXC_GAP_THRESHOLD_S
        ):
            v += min((_EXC_GAP_THRESHOLD_S - gap) * _EXC_GAP_PER_S, _EXC_GAP_CAP)
        out.append(int(round(max(0.0, min(100.0, v)))))
    return out


def _first_green_lap(status: list[str]) -> int:
    """First lap the race actually raced (1-based); laps+1 if it never went green."""
    for i, s in enumerate(status):
        if s == "green":
            return i + 1
    return len(status) + 1


def _driver_rows(
    laps: pd.DataFrame, results: pd.DataFrame, total_laps: int, first_green: int
) -> list[dict]:
    """One entry per starter, sorted by finishing position (classified first).

    ``team`` is the session's own team name — the period-correct snapshot. ``second_car``
    marks the team's higher-numbered entry so the frontend can dash it apart from its
    teammate. DNF drivers keep ``lap_times`` null-padded after their last completed lap.
    Pit-ins before the race's first green lap are dropped: an aborted/suspended start
    routes the whole field through the pit lane (e.g. Melbourne 2025), which FastF1
    records as in-laps but no fan would call pit stops.
    """
    res = results[~_b(results["dns"])].copy()
    if not len(res):
        return []
    fin = res["finish_position"].astype(float)
    res["_sort"] = np.where(np.isfinite(fin), fin, np.inf)
    res = res.sort_values(["_sort"]).reset_index(drop=True)

    times = laps.pivot_table(
        index="lap_number", columns="driver", values="lap_time_s", aggfunc="first"
    ).reindex(range(1, total_laps + 1))
    inlaps = laps[_b(laps["is_inlap"])]
    pit_by_driver: dict[str, list[int]] = {
        str(d): sorted(
            int(lap) for lap in g["lap_number"].dropna() if int(lap) >= first_green
        )
        for d, g in inlaps.groupby("driver")
    }
    numbers = (
        laps.groupby("driver")["driver_number"].first()
        if "driver_number" in laps.columns
        else pd.Series(dtype=object)
    )

    def car_no(code: str) -> float:
        try:
            return float(numbers.get(code))
        except (TypeError, ValueError):
            return float("inf")

    # The team's numerically-lowest car number is the "first" car; any other entries
    # (normally exactly one) get second_car. Falls back to results order when the laps
    # frame carries no numbers.
    second: set[str] = set()
    for _, group in res.groupby("team"):
        codes = sorted(group["driver"], key=car_no)
        second.update(codes[1:])

    rows: list[dict] = []
    for i, r in res.iterrows():
        code = str(r["driver"])
        col = (
            times[code]
            if code in times.columns
            else pd.Series(np.nan, index=times.index)
        )
        fin_v = float(r["finish_position"])
        rows.append(
            {
                "code": code,
                "team": str(r["team"]),
                "second_car": code in second,
                "finish_pos": int(fin_v) if np.isfinite(fin_v) else int(i) + 1,
                "classified": bool(r["classified"]),
                "lap_times": [
                    round(float(t), 3) if np.isfinite(t) else None
                    for t in col.to_numpy(dtype=float)
                ],
                "pit_laps": pit_by_driver.get(code, []),
            }
        )
    return rows


def build_trace(
    laps: pd.DataFrame,
    results: pd.DataFrame,
    lap_rainfall: dict[int, bool] | None,
    *,
    season: int,
    round_number: int,
    event_name: str,
    overtakes_by_lap: dict[int, int] | None = None,
) -> dict | None:
    """Reduce one race's frames to the RACE_TRACE blob; None when the race is unusable.

    ``overtakes_by_lap`` is the telemetry-based per-lap pass count from
    :func:`overtakes_by_lap`; when omitted it falls back to the lap-resolution
    ``race_metrics.passes_by_lap`` (used by the unit tests, which have no telemetry).
    """
    total_laps = _total_laps(laps)
    if total_laps < 2 or not len(results):
        return None

    status = status_by_lap(laps, total_laps)
    if sum(1 for s in status if s == "green") < _MIN_GREEN_LAPS:
        return None

    weather = weather_by_lap(laps, lap_rainfall, total_laps)
    passes = overtakes_by_lap if overtakes_by_lap is not None else passes_by_lap(laps)
    overtakes = [int(passes.get(lap, 0)) for lap in range(1, total_laps + 1)]

    # Start-procedure pit visits (see _driver_rows) are excluded from the pit-activity
    # excitement term too, so an aborted start doesn't read as a pit frenzy.
    first_green = _first_green_lap(status)
    inlap_counts = laps.loc[_b(laps["is_inlap"]), "lap_number"].value_counts()
    pit_counts = [
        int(inlap_counts.get(lap, 0)) if lap >= first_green else 0
        for lap in range(1, total_laps + 1)
    ]

    return {
        "version": TRACE_VERSION,
        "season": season,
        "round_number": round_number,
        "event_name": event_name,
        "total_laps": total_laps,
        "track_status": status,
        "weather": weather,
        "excitement": _excitement(
            status,
            weather,
            overtakes,
            pit_counts,
            _front_gap_by_lap(laps, total_laps),
            total_laps,
        ),
        "overtakes": overtakes,
        "drivers": _driver_rows(laps, results, total_laps, first_green),
    }
