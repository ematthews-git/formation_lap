"""Validate the overtake detector against races whose answer we can argue about.

Prints, per race, the racing count and the full classification breakdown, so a total that
looks wrong can be attributed to a category rather than guessed at. Two kinds of check:

  * ``expect`` — a range the racing count should land in, from what actually happened in
    the race. Monaco is nearly impossible to pass at; Spa and the Red Bull Ring are not.
  * ``published`` — the broadcast overtake figure where one exists. Our definition is
    deliberately stricter (it excludes cars passed while in trouble, which broadcast stats
    count), so ``gross`` should sit at or just below this number. Coming out *above* it
    means something is being double-counted.

Run:  uv run --package formation-sim python scripts/validate_overtakes.py
Optional: pass labels to limit, e.g. ... validate_overtakes.py monaco2025 suzuka2025
Add --events to dump the individual racing passes for eyeballing against the race.
"""

from __future__ import annotations

import os
import sys

import numpy as np

os.environ.setdefault("FASTF1_CACHE_DIR", os.path.expanduser("~/.cache/fastf1"))

# label -> (season, round, expected racing range, published broadcast total or None)
RACES: dict[str, tuple[int, int, tuple[int, int], int | None]] = {
    # Nearly impossible to pass at: a handful of on-track moves in a whole race.
    "monaco2025": (2025, 8, (0, 12), None),
    "monaco2023": (2023, 6, (0, 15), None),
    # Famously processional even though the track is not the reason.
    "suzuka2025": (2025, 3, (5, 25), None),
    # Ordinary racing at circuits where passing is possible.
    "silverstone2024": (2024, 12, (15, 45), None),
    "austria2022": (2022, 11, (30, 70), None),
    "spa2023": (2023, 12, (35, 80), None),
    # Cross-checks against published figures.
    "abudhabi2023": (2023, 22, (30, 70), 70),
    "zandvoort2023": (2023, 13, (30, 90), 188),
    # Chaos: most of the position changes are cars in trouble, not racing.
    "saopaulo2024": (2024, 21, (5, 45), None),
    "vegas2023": (2023, 21, (25, 80), None),
}


def analyse(season: int, rnd: int):
    from formation_data import overtakes as ov
    from formation_sim.data import collector, track_position as tp

    ses = collector.load_session(season, rnd, "R",
                                 weather=False, messages=True, telemetry=True)
    if ses is None:
        return None, None, None
    frame = tp.track_frame(ses)
    if frame is None:
        return None, None, None
    laps = collector.session_laps(ses)
    events = ov.detect_overtakes(
        tp.driver_track_positions(ses, frame),
        laps,
        official=tp.official_positions(ses),
        results=collector.session_results(ses),
        status_windows=collector.session_track_status(ses),
        corners=frame.corners,
        marshal_sectors=frame.marshal_sectors,
        track_length_m=frame.length_m,
    )
    total_laps = int(np.nanmax(laps["lap_number"].to_numpy(dtype=float)))
    return ov.summarise(events, total_laps), str(ses.event["EventName"]), events


def main() -> None:
    args = [a for a in sys.argv[1:]]
    show_events = "--events" in args
    want = [a for a in args if not a.startswith("--")]

    failures: list[str] = []
    print(f"{'race':<17}{'racing':>7}{'gross':>7}{'pub':>6}  breakdown")
    for label, (season, rnd, (lo, hi), published) in RACES.items():
        if want and label not in want:
            continue
        try:
            blob, name, events = analyse(season, rnd)
        except Exception as exc:  # noqa: BLE001 — one bad race must not stop the sweep
            print(f"{label:<17} ERROR {type(exc).__name__}: {exc}")
            failures.append(f"{label}: {type(exc).__name__}")
            continue
        if blob is None:
            print(f"{label:<17} no data (rate limited or telemetry unavailable)")
            continue

        racing = blob["totals"]["racing"]
        gross = blob["totals"]["gross"]
        kinds = {k: v for k, v in blob["totals"]["by_kind"].items() if v}
        flag = ""
        if not (lo <= racing <= hi):
            flag = f"  <-- outside expected {lo}-{hi}"
            failures.append(f"{label}: racing={racing}, expected {lo}-{hi}")
        if published is not None and gross > published:
            flag += f"  <-- gross exceeds published {published}"
            failures.append(f"{label}: gross={gross} > published {published}")
        print(f"{label:<17}{racing:>7}{gross:>7}"
              f"{(published if published is not None else '-'):>6}  {kinds}{flag}")
        top = list(blob["by_corner"].items())[:5]
        if top:
            print(f"{'':<17}hotspots {top}")
        if show_events:
            for e in events:
                if e["kind"] != "racing":
                    continue
                print(f"{'':<19}L{e['lap']:<3} {e['gainer']:>3} on {e['loser']:<3} "
                      f"T{e['corner']} {e['speed_kph']}kph drs={e['drs']}")

    print()
    if failures:
        print(f"{len(failures)} check(s) failed:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("all checks passed")


if __name__ == "__main__":
    main()
