"""Throwaway diagnostic for the race-trace data-issue fixes (plan §0).

For each audited race it loads the cached FastF1 session (telemetry + messages) and dumps
the signals the fixes depend on:
  * DNF drivers and their laps_completed (for §C dying-car suppression);
  * the authoritative ``ses.track_status`` windows mapped onto lap numbers (§A);
  * red/SC/VSC/green ``race_control_messages`` (§A restart truth);
  * the CURRENT per-lap ``status_by_lap`` (.any() smear) and ``overtakes_by_lap`` counts;
  * a per-driver zoom (TrackStatus, lap_start_s, lap_end_s) around each race's lap-of-interest.

Run:  uv run --package formation-sim python scripts/diagnose_race_traces.py
Optional: pass race labels to limit, e.g. ... diagnose_race_traces.py monza baku2021
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from formation_sim.data import collector

# label -> (season, schedule keyword, lap(s) of interest)
RACES = {
    "monza2023": (2023, "Monza", [53]),            # final-lap false OT
    "baku2021": (2021, "Baku", [48, 49, 50, 51]),  # restart 49 vs 50 (red flag)
    "baku2022": (2022, "Baku", [20, 21, 22]),      # Leclerc DNF -> high OT
    "singapore2022": (2022, "Singapore", [6, 7, 8, 9, 10, 11, 12]),  # SC L7, long VSC
    "austin2025": (2025, "Austin", None),          # 12 OT under VSC / DNF / pit
    "austin2023": (2023, "Austin", [2, 3, 4, 5, 6]),  # 12 OT L4, nothing in highlights
    "mexico2023": (2023, "Mexico", [34, 35, 36, 37]),  # red flag, restart 35 vs 36
    "brazil2024": (2024, "Brazil", [29, 30, 31, 32, 43, 44, 45, 46]),  # red + SC
    # sanity anchors (not flagged): should stay in their known ranges after the fix.
    "monaco2023": (2023, "Monaco", None),        # low-overtake, expect ~30
    "zandvoort2023": (2023, "Zandvoort", None),  # high-overtake, expect ~80-96
}

_CODE = {"4": "sc", "5": "red", "6": "vsc", "7": "vsc", "2": "yellow", "1": "green", "3": "green"}
_RANK = {"green": 0, "yellow": 1, "vsc": 2, "sc": 3, "red": 4}


def _secs(series: pd.Series) -> pd.Series:
    return pd.to_timedelta(series, errors="coerce").dt.total_seconds()


def find_round(year: int, keyword: str) -> int | None:
    sched = collector.get_schedule(year)
    kw = keyword.lower()
    for _, ev in sched.iterrows():
        hay = " ".join(
            str(ev.get(c, "")) for c in ("Location", "Country", "EventName", "OfficialEventName")
        ).lower()
        if kw in hay:
            return int(ev["RoundNumber"])
    return None


def lap_bounds(raw_laps: pd.DataFrame) -> dict[int, tuple[float, float]]:
    """lap number -> (earliest start, latest end) in session seconds, across the field."""
    df = pd.DataFrame({
        "lap": raw_laps["LapNumber"].astype("float"),
        "lo": _secs(raw_laps["LapStartTime"]),
        "hi": _secs(raw_laps["Time"]),
    }).dropna(subset=["lap"])
    out: dict[int, tuple[float, float]] = {}
    for lap, g in df.groupby("lap"):
        out[int(lap)] = (float(g["lo"].min()), float(g["hi"].max()))
    return out


def track_status_windows(ses) -> list[tuple[float, float, str]]:
    """Authoritative (t_start, t_end, mapped_status) windows from ses.track_status."""
    try:
        ts = ses.track_status
    except Exception:
        return []
    if ts is None or not len(ts):
        return []
    t = _secs(ts["Time"]).to_numpy(dtype=float)
    codes = ts["Status"].astype("string").fillna("").to_numpy()
    end = float(np.nanmax([b for b in [ses.laps["Time"].pipe(_secs).max()] if b == b] or [t[-1]]))
    wins = []
    for i in range(len(t)):
        t0 = t[i]
        t1 = t[i + 1] if i + 1 < len(t) else max(end, t0)
        wins.append((t0, t1, _CODE.get(str(codes[i]), f"?{codes[i]}")))
    return wins


def window_to_laps(t0: float, t1: float, bounds: dict[int, tuple[float, float]]) -> list[int]:
    """Half-open overlap: lap [lo,hi) overlaps window [t0,t1) iff t0 < hi and lo < t1."""
    hits = []
    for lap, (lo, hi) in bounds.items():
        lo_eff = lo if np.isfinite(lo) else -np.inf
        hi_eff = hi if np.isfinite(hi) else lo_eff
        if t0 < hi_eff and lo_eff < t1:
            hits.append(lap)
    return sorted(hits)


def dump(label: str, season: int, keyword: str, laps_of_interest) -> None:
    rnd = find_round(season, keyword)
    if rnd is None:
        print(f"\n### {label}: could not find round for '{keyword}' in {season}")
        return
    ses = collector.load_session(season, rnd, "R", weather=True, messages=True, telemetry=True)
    if ses is None:
        print(f"\n### {label}: load failed (rate limited={collector.rate_limited()})")
        return
    ev_name = str(ses.event["EventName"])
    laps = collector.session_laps(ses)
    results = collector.session_results(ses)
    raw = ses.laps
    total = int(np.nanmax(laps["lap_number"].to_numpy())) if len(laps) else 0

    print(f"\n{'=' * 78}\n### {label}: {season} R{rnd} {ev_name} — total_laps={total}")

    dnf = results[results["dnf"].astype(bool)]
    print("DNF laps_completed:", {r.driver: int(r.laps_completed) if np.isfinite(r.laps_completed)
                                  else None for r in dnf.itertuples()})

    bounds = lap_bounds(raw)
    wins = track_status_windows(ses)
    print("authoritative track_status windows (t0..t1 status -> laps):")
    for t0, t1, st in wins:
        if st == "green":
            continue
        print(f"  {t0:8.1f}..{t1:8.1f}  {st:6s} -> laps {window_to_laps(t0, t1, bounds)}")

    # race control: red / SC / VSC / green-restart messages
    try:
        rc = ses.race_control_messages
        m = rc["Message"].astype("string").str.upper()
        keep = rc[m.str.contains("RED|SAFETY CAR|VIRTUAL|GREEN|RESTART", regex=True, na=False)]
        print("race_control (lap | message):")
        for r in keep.itertuples():
            lap = getattr(r, "Lap", None)
            print(f"  L{('' if lap is None or (isinstance(lap, float) and np.isnan(lap)) else int(lap))!s:>3} : {r.Message}")
    except Exception as e:  # noqa: BLE001
        print("race_control unavailable:", e)

    from formation_data import race_trace as rt
    old_status = rt.status_by_lap(laps, total)
    win_df = collector.session_track_status(ses)
    new_status = rt.status_by_lap(laps, total, windows=win_df)
    print("OLD status_by_lap (non-green):",
          {i + 1: s for i, s in enumerate(old_status) if s != "green"})
    print("NEW status_by_lap (non-green):",
          {i + 1: s for i, s in enumerate(new_status) if s != "green"})
    print("red_restart laps:", sorted(rt._red_restart_laps(new_status)))

    prog = collector.driver_progress(ses)
    ot_new = rt.overtakes_by_lap(prog, laps, status=new_status, results=results)
    print(f"NEW overtakes_by_lap (total {sum(ot_new.values())}):", dict(sorted(ot_new.items())))
    cur_status, ot = new_status, ot_new

    if laps_of_interest:
        for L in laps_of_interest:
            g = raw[raw["LapNumber"].astype("float") == float(L)]
            if not len(g):
                continue
            rows = []
            los = _secs(g["LapStartTime"])
            his = _secs(g["Time"])
            for (_, gr), lo, hi in zip(g.iterrows(), los, his):
                rows.append(f"{gr['Driver']}:{gr['TrackStatus']}"
                            f"[{lo:.0f}..{hi:.0f}]" if np.isfinite(lo) and np.isfinite(hi)
                            else f"{gr['Driver']}:{gr['TrackStatus']}[na]")
            print(f"  L{L} status={cur_status[L-1] if L <= total else '-'} OT={ot.get(L, 0)}: "
                  + "  ".join(rows))


def main() -> None:
    want = [a.lower() for a in sys.argv[1:]]
    for label, (season, keyword, loi) in RACES.items():
        if want and label not in want:
            continue
        try:
            dump(label, season, keyword, loi)
        except Exception as e:  # noqa: BLE001
            print(f"\n### {label}: ERROR {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
