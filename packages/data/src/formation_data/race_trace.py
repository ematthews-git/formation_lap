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

TRACE_VERSION = 2

# Full-course neutralisations: no racing, so no overtakes are credited on these laps.
_NEUTRAL = frozenset({"sc", "vsc", "red"})
_STATUS_RANK = {"green": 0, "yellow": 1, "vsc": 2, "sc": 3, "red": 4}

# A race must have actually raced to be worth tracing: fewer green laps than this and
# the pace pane would be wall-to-wall interpolation (2021 Spa: two laps behind the SC).
_MIN_GREEN_LAPS = 5

# On-track overtake counting (telemetry-based durable lead changes).
OVERTAKE_DWELL_S = (
    8.0  # a swap must hold this long to count (filters side-by-side scraps)
)
_OVERTAKE_GRID_S = 0.5  # running-order sampling step
# A pass only counts once the passing car has actually drawn clear by ~this many seconds.
# Two cars running nose-to-tail (well within a second — normal, real racing) sit at a
# near-zero telemetry gap whose sign jitters, and each jitter flip would otherwise read as a
# change of places; requiring the leader to pull a few car-lengths clear tells a completed
# pass from that jitter WITHOUT netting repeated real passes away (a genuine slipstream fight,
# where each car does draw clear in turn, still counts every pass).
_OVERTAKE_MIN_SEP_S = 0.5

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


def _red_restart_laps(status: list[str]) -> set[int]:
    """1-based laps to treat like a race start after a RED-flag suspension.

    After a red flag the field re-forms and relaunches (standing or rolling) from a
    bunched grid — the order shuffle that produces is a restart, not overtaking (same
    reason lap 1 is excluded). Returns the first racing lap (green/yellow) after each red
    block and the lap after it (the launch spills across ~1.5 laps). SC/VSC restarts are
    NOT included here — those keep their real post-restart passes; their bunched-pack
    concertina is removed instead by masking neutralised samples out of pass detection.
    """
    out: set[int] = set()
    in_red = False
    for i, s in enumerate(status):
        if s == "red":
            in_red = True
        elif s in ("sc", "vsc"):
            continue  # still neutralised — keep waiting for the racing lap
        elif in_red:  # first green/yellow lap after the red block
            out.add(i + 1)
            out.add(i + 2)
            in_red = False
    return out


def _dnf_last_lap(results: pd.DataFrame | None) -> dict[str, int]:
    """Retiring driver → last lap they completed. A car that slows to retire gets
    streamed past on-track (the whole field "overtakes" a dying car); those aren't
    racing passes, so swaps involving it on that lap and after are dropped."""
    if results is None or not len(results) or "dnf" not in results.columns:
        return {}
    out: dict[str, int] = {}
    for r in results.itertuples():
        if bool(getattr(r, "dnf", False)):
            lc = getattr(r, "laps_completed", np.nan)
            if np.isfinite(lc):
                out[str(r.driver)] = int(lc)
    return out


def overtakes_by_lap(
    progress: dict[str, pd.DataFrame],
    laps: pd.DataFrame,
    *,
    dwell_s: float = OVERTAKE_DWELL_S,
    grid_step_s: float = _OVERTAKE_GRID_S,
    min_sep_s: float = _OVERTAKE_MIN_SEP_S,
    status: list[str] | None = None,
    results: pd.DataFrame | None = None,
) -> dict[int, int]:
    """On-track overtakes per lap, as telemetry-based durable lead changes.

    ``progress`` is the collector's per-driver ``(t, prog, lap)`` frames
    (:func:`formation_sim.data.collector.driver_progress`); ``laps`` its
    ``session_laps`` frame. All drivers are resampled onto a common time grid, and for
    each pair every order swap that then holds ``>= dwell_s`` AND draws clear by
    ``>= min_sep_s`` is counted once, credited to the lap it completes on. Every real,
    completed pass counts — a repeated slipstream fight counts each pass — but two cars
    running nose-to-tail at a near-zero gap, whose telemetry sign merely jitters, do not.
    Excluded: lap 1 and red-flag restart laps (bunched-grid relaunches, not overtaking);
    pit in/out laps (per-driver); and any lap under SC/VSC/red. Crucially, samples taken
    while either car is under a full-course neutralisation are masked OUT of the swap
    detection itself, not just the credit — otherwise the pack concertina under an SC/VSC
    settles on the green restart lap and reads as a flurry of phantom passes.

    ``status`` is the race-level per-lap status (from :func:`status_by_lap`); when
    omitted it is derived from ``laps``. ``results`` (with ``dnf`` / ``laps_completed``)
    enables dying-car suppression. Falls back to the lap-resolution
    :func:`race_metrics.passes_by_lap` when telemetry progress is unavailable.
    """
    total_laps = _total_laps(laps)
    if status is None:
        status = status_by_lap(laps, total_laps)
    neutral = {i + 1 for i, s in enumerate(status) if s in _NEUTRAL}
    red_restart = _red_restart_laps(status)
    dnf_last = _dnf_last_lap(results)

    if not progress or total_laps < 1:
        return passes_by_lap(laps, neutral=neutral)

    # Per-(driver, lap) pit in/out flags (the only per-car exclusion; neutralisation is
    # applied at race level so a mid-lap deployment neutralises the lap for everyone).
    flags = laps.copy()
    for col in ("is_inlap", "is_outlap"):
        flags[col] = _b(flags[col])
    flags = flags.set_index(["driver", "lap_number"])

    def in_out(drv: str, lap: int) -> bool:
        try:
            r = flags.loc[(drv, float(lap))]
        except KeyError:
            return False
        if isinstance(r, pd.DataFrame):
            r = r.iloc[0]
        return bool(r["is_inlap"] or r["is_outlap"])

    t_min = min(df["t"].iloc[0] for df in progress.values())
    t_max = max(df["t"].iloc[-1] for df in progress.values())
    if not (np.isfinite(t_min) and np.isfinite(t_max)) or t_max <= t_min:
        return passes_by_lap(laps, neutral=neutral)
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
    # Per-car mask: is this sample on a neutralised lap for that car? Masked samples are
    # dropped from detection so an SC/VSC concertina never registers as a confirmed swap.
    neutral_arr = np.array(sorted(neutral), dtype=float)
    car_neutral = {
        c: (np.isin(np.round(lapg[c]), neutral_arr) if neutral_arr.size
            else np.zeros(len(grid), dtype=bool))
        for c in codes
    }
    min_run = max(1, int(round(dwell_s / grid_step_s)))
    # Separation threshold in progress units: convert the ~0.5s "drew clear" margin by the
    # race's median green lap time (a lap of progress == that many seconds), so it means the
    # same on-track distance whether the lap is 75s (Monaco) or 105s (Spa).
    lt = pd.to_numeric(laps.get("lap_time_s"), errors="coerce") if "lap_time_s" in laps else None
    med_lap = float(np.nanmedian(lt)) if lt is not None and lt.notna().any() else np.nan
    if not np.isfinite(med_lap) or med_lap <= 0:
        med_lap = 90.0
    min_sep = min_sep_s / med_lap

    def credited(lp: int, a: str, b: str) -> bool:
        return (
            2 <= lp <= total_laps
            and lp not in neutral
            and lp not in red_restart
            and not in_out(a, lp)
            and not in_out(b, lp)
            and not (a in dnf_last and lp >= dnf_last[a])
            and not (b in dnf_last and lp >= dnf_last[b])
        )

    per_lap: dict[int, int] = {}
    n = len(grid)
    for ia in range(len(codes)):
        a = codes[ia]
        for ib in range(ia + 1, len(codes)):
            b = codes[ib]
            d = prog[a] - prog[b]
            valid = np.isfinite(d) & ~(car_neutral[a] | car_neutral[b])
            if valid.sum() < min_run:
                continue
            sign = np.where(d > 0, 1, np.where(d < 0, -1, 0))
            confirmed: int | None = None
            i = 0
            while i < n:
                if not valid[i]:
                    # A masked stretch — SC/VSC/red, or a data gap — re-baselines the order:
                    # the field pits and concertinas under a neutralisation, so a reorder that
                    # emerges on the far side is a pit-cycle / restart shuffle, not a pass.
                    # Dropping `confirmed` means only changes between two runs of uninterrupted
                    # racing count.
                    confirmed = None
                    i += 1
                    continue
                if sign[i] == 0:
                    i += 1
                    continue
                j = i
                while j < n and valid[j] and sign[j] == sign[i]:
                    j += 1
                # A settled order: held past the dwell AND the leader drew clear (the gap
                # opened past min_sep at some point) — otherwise it's nose-to-tail jitter.
                if j - i >= min_run and float(np.max(np.abs(d[i:j]))) >= min_sep:
                    if confirmed is not None and sign[i] != confirmed:
                        la, lb = lapg[a][i], lapg[b][i]
                        present = [v for v in (la, lb) if np.isfinite(v)]
                        lp = int(round(min(present))) if present else -1
                        if credited(lp, a, b):
                            per_lap[lp] = per_lap.get(lp, 0) + 1
                    confirmed = int(sign[i])
                i = j
    return per_lap


def _lap_bounds(laps: pd.DataFrame) -> dict[int, tuple[float, float]] | None:
    """lap number → (earliest start, latest end) in session seconds, across the field.

    ``None`` when the frame carries no absolute-time columns (fabricated test frames),
    so callers fall back to the per-lap-flag method. A lap missing its start (lap 1, and
    some post-red restart laps have a NaT ``LapStartTime``) inherits the previous lap's
    end so the timeline stays contiguous.
    """
    if "lap_start_s" not in laps.columns or "lap_end_s" not in laps.columns:
        return None
    df = pd.DataFrame(
        {
            "lap": laps["lap_number"].astype(float),
            "lo": pd.to_numeric(laps["lap_start_s"], errors="coerce"),
            "hi": pd.to_numeric(laps["lap_end_s"], errors="coerce"),
        }
    ).dropna(subset=["lap"])
    bounds: dict[int, tuple[float, float]] = {}
    for lap, g in df.groupby("lap"):
        lo, hi = g["lo"].min(), g["hi"].max()
        bounds[int(lap)] = (
            float(lo) if np.isfinite(lo) else np.nan,
            float(hi) if np.isfinite(hi) else np.nan,
        )
    for lap in sorted(bounds):
        lo, hi = bounds[lap]
        if not np.isfinite(lo) and np.isfinite(bounds.get(lap - 1, (np.nan, np.nan))[1]):
            bounds[lap] = (bounds[lap - 1][1], hi)
    return bounds


def _status_from_windows(
    windows: pd.DataFrame, bounds: dict[int, tuple[float, float]], total_laps: int
) -> list[str]:
    """Map authoritative ``(t_start, t_end, status)`` windows onto lap numbers.

    A lap ``[lo, hi)`` takes the worst status of every window it overlaps, using
    half-open intervals: a restart lap whose start coincides with a red/SC window's end
    does NOT overlap it, so it comes out green rather than one lap late. The mapping is
    field-wide (one lap span, all cars) so a stoppage neutralises the lap uniformly
    instead of only the cars whose own lap happened to carry the code.
    """
    wins = [
        (float(r.t_start), float(r.t_end), str(r.status))
        for r in windows.itertuples()
    ]
    out: list[str] = []
    for lap in range(1, total_laps + 1):
        lo, hi = bounds.get(lap, (np.nan, np.nan))
        lo_eff = lo if np.isfinite(lo) else -np.inf
        hi_eff = hi if np.isfinite(hi) else lo_eff
        best = "green"
        for w0, w1, st in wins:
            if w0 < hi_eff and lo_eff < w1 and _STATUS_RANK.get(st, 0) > _STATUS_RANK[best]:
                best = st
        out.append(best)
    return out


def status_by_lap(
    laps: pd.DataFrame, total_laps: int, *, windows: pd.DataFrame | None = None
) -> list[str]:
    """One race-level status per lap (``green|yellow|vsc|sc|red``), worst wins.

    When ``windows`` (the collector's authoritative ``session_track_status`` time-series)
    is given, each lap is classified from the status timeline mapped onto its session-time
    span — precise boundaries, correct restart lap, uniform across the field. Without it
    (unit tests, or a session with no track-status feed) it falls back to ``any`` across
    the per-driver-lap flags: a deployment mid-lap flags the whole lap.
    """
    if windows is not None and len(windows):
        bounds = _lap_bounds(laps)
        if bounds is not None:
            return _status_from_windows(windows, bounds, total_laps)

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
        # A restart — the bunched-field, cold-tyre resumption — follows a red flag just
        # as it follows a safety car, so both count (a red-flag race resumes green,
        # sometimes from a standing start).
        if prev in ("sc", "red") and s not in ("sc", "red"):
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
    status: list[str] | None = None,
    overtakes_by_lap: dict[int, int] | None = None,
) -> dict | None:
    """Reduce one race's frames to the RACE_TRACE blob; None when the race is unusable.

    ``status`` is the precomputed race-level per-lap status (from :func:`status_by_lap`
    with the authoritative windows); when omitted it is derived from ``laps`` (the
    per-lap-flag fallback the unit tests use). ``overtakes_by_lap`` is the telemetry-based
    per-lap pass count from :func:`overtakes_by_lap`; when omitted it falls back to the
    lap-resolution ``race_metrics.passes_by_lap`` (used by the unit tests, no telemetry).
    """
    total_laps = _total_laps(laps)
    if total_laps < 2 or not len(results):
        return None

    if status is None:
        status = status_by_lap(laps, total_laps)
    if sum(1 for s in status if s == "green") < _MIN_GREEN_LAPS:
        return None

    weather = weather_by_lap(laps, lap_rainfall, total_laps)
    neutral = {i + 1 for i, s in enumerate(status) if s in _NEUTRAL}
    passes = (
        overtakes_by_lap
        if overtakes_by_lap is not None
        else passes_by_lap(laps, neutral=neutral)
    )
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
