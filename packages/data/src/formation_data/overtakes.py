"""On-track overtakes: detect every change of places, then explain each one.

The old counter tried to filter its way to a number — drop this lap, drop that pair — and
the filters were lap-keyed and coarse, so it both discarded real racing (a whole lap thrown
away because someone pitted on it) and waved through the failure that actually dominates:
one car in trouble being streamed past by half the field, scored as half a field's worth of
overtakes.

So this module inverts it. Find every durable change of on-track order, then give each one
a reason — ``pit``, ``lapped``, ``neutralised``, ``start``, ``attrition`` or ``racing`` —
and count only the ones that were racing. Because every event is kept with its label, the
headline number is a filter over stored data rather than something that has to be recomputed
to be re-examined, and a total that looks wrong can be broken down until it isn't.

An overtake, concretely: two cars **on the same lap** change places **on track**, and the
new order holds both for ``min_dwell_s`` and all the way to the passing car's next
start/finish crossing — the durability convention F1 and Pirelli use, and the one that stops
a side-by-side scrap through a corner sequence scoring once per change of lead.

Pure pandas/numpy over the canonical frames — no FastF1, DB or sim imports — so it is
unit-testable with fabricated inputs, the same contract as :mod:`race_metrics` and
:mod:`race_trace`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

OVERTAKES_VERSION = 1

# Kinds, in the order they are tested. First match wins, so the more mechanical
# explanations (a pit stop, a lapping) pre-empt the judgement calls (attrition).
KIND_PIT = "pit"
KIND_LAPPED = "lapped"
KIND_NEUTRALISED = "neutralised"
KIND_START = "start"
KIND_ATTRITION = "attrition"
KIND_RACING = "racing"
KINDS = (KIND_RACING, KIND_ATTRITION, KIND_PIT, KIND_LAPPED, KIND_NEUTRALISED, KIND_START)

# Kinds that a broadcast-style count would include: everything that was a real car
# physically passing another, whatever the reason. Excludes pit-cycle and neutralised
# positions (nobody passed anybody on track) and the standing start.
_GROSS = frozenset({KIND_RACING, KIND_ATTRITION, KIND_LAPPED})

GRID_S = 1.0  # running-order sampling step
MIN_DWELL_S = 5.0  # a swap must hold at least this long to be a pass, not a lunge
_MAX_HOLD_S = 120.0  # cap on how far ahead we look for the next line crossing

# Full-course neutralisations: nobody is racing, so nothing here is an overtake.
_NEUTRAL_STATUS = frozenset({"sc", "vsc", "red"})

# The official feed updates every ~3.5 s, so a telemetry swap and its classification
# counterpart can be this far apart and still be the same event.
_OFFICIAL_TOL_S = 8.0

# Pit-lane window padding around the recorded entry/exit stamps: braking for the pit entry
# starts before the timing line, and a car is still up to a corner short of racing speed
# after the exit line.
_PIT_PAD_BEFORE_S = 5.0
_PIT_PAD_AFTER_S = 15.0

# Attrition thresholds.
_SLOW_RATIO = 0.80  # speed where the pass happened vs the loser's own norm there
_CLUSTER_N = 3  # this many cars past the same driver...
_CLUSTER_WINDOW_S = 60.0  # ...inside this long is a car in trouble, not racing
_CLUSTER_N_HARD = 4  # this many is a car in trouble regardless of measured pace
_TERMINAL_LAPS = 3  # passes this close to a retirement are the car dying
_OFF_LINE_M = 12.0  # this far off the racing line is a spin, an excursion, or the pits
_STRADDLE_M = 300.0  # within this of the line, a lap-counter disagreement is a straddle

# Launch phase: from the start until the leader reaches this corner, places change because
# of clutch and grip, not overtaking. Falls back to a fraction of the lap without corners.
_LAUNCH_CORNER = 3
_LAUNCH_FRACTION = 0.15


def _num(s) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def _grid_of(positions: dict[str, pd.DataFrame], step_s: float) -> np.ndarray:
    lo = min(float(df["t"].iloc[0]) for df in positions.values())
    hi = max(float(df["t"].iloc[-1]) for df in positions.values())
    if not (np.isfinite(lo) and np.isfinite(hi)) or hi <= lo:
        return np.array([])
    return np.arange(lo, hi, step_s)


def _on_grid(df: pd.DataFrame, col: str, grid: np.ndarray) -> np.ndarray:
    if col not in df:
        return np.full(len(grid), np.nan)
    return np.interp(grid, df["t"].to_numpy(float), _num(df[col]).to_numpy(float),
                     left=np.nan, right=np.nan)


def _step_on_grid(t: np.ndarray, v: np.ndarray, grid: np.ndarray) -> np.ndarray:
    """Hold-last-value resampling, for signals that step rather than ramp."""
    if not len(t):
        return np.full(len(grid), np.nan)
    i = np.searchsorted(t, grid, side="right") - 1
    out = np.where(i >= 0, v[np.clip(i, 0, None)], np.nan)
    return out.astype(float)


def pit_windows(laps: pd.DataFrame) -> dict[str, list[tuple[float, float]]]:
    """Driver → time spans in the pit lane, from the exact entry/exit stamps.

    Pairing each entry with the exit that follows it spans the stop across the lap
    boundary it straddles. Falling back to whole in/out laps — what the old counter did —
    discards up to two laps of real racing per stop per driver.
    """
    out: dict[str, list[tuple[float, float]]] = {}
    if "pit_in_s" not in laps.columns or "pit_out_s" not in laps.columns:
        return out
    for drv, g in laps.sort_values("lap_number").groupby("driver"):
        ins = _num(g["pit_in_s"]).dropna().to_numpy(float)
        outs = _num(g["pit_out_s"]).dropna().to_numpy(float)
        spans: list[tuple[float, float]] = []
        for t_in in ins:
            later = outs[outs > t_in]
            t_out = float(later[0]) if len(later) else t_in + 60.0
            spans.append((t_in - _PIT_PAD_BEFORE_S, t_out + _PIT_PAD_AFTER_S))
        # An out-lap with no matching entry (started from the pits) still isn't racing.
        for t_out in outs:
            if not any(a <= t_out <= b for a, b in spans):
                spans.append((t_out - 1.0, t_out + _PIT_PAD_AFTER_S))
        if spans:
            out[str(drv)] = sorted(spans)
    return out


def _in_span(spans: list[tuple[float, float]] | None, t: float) -> bool:
    return bool(spans) and any(a <= t <= b for a, b in spans)


def _neutral_spans(status_windows: pd.DataFrame | None) -> list[tuple[float, float]]:
    if status_windows is None or not len(status_windows):
        return []
    w = status_windows
    return [(float(r.t_start), float(r.t_end)) for r in w.itertuples()
            if str(r.status) in _NEUTRAL_STATUS]


def _retire_lap(results: pd.DataFrame | None) -> dict[str, float]:
    """Retiring driver → the last lap they completed."""
    out: dict[str, float] = {}
    if results is None or not len(results) or "dnf" not in results.columns:
        return out
    for r in results.itertuples():
        if bool(getattr(r, "dnf", False)):
            lc = getattr(r, "laps_completed", np.nan)
            if np.isfinite(lc):
                out[str(r.driver)] = float(lc)
    return out


def _launch_window(positions: dict[str, pd.DataFrame], corners: pd.DataFrame | None,
                   track_length_m: float, grid: np.ndarray) -> float:
    """Session time at which the launch phase ends.

    Measured in track distance rather than lap number: the grid shuffle is over once the
    leader is through the opening corners, and everything after that on lap 1 is racing
    that the old "drop all of lap 1" rule threw away.
    """
    if not len(grid):
        return -np.inf
    target = track_length_m * _LAUNCH_FRACTION
    if corners is not None and len(corners) >= _LAUNCH_CORNER:
        s = _num(corners.sort_values("s")["s"]).to_numpy(float)
        if len(s) >= _LAUNCH_CORNER and np.isfinite(s[_LAUNCH_CORNER - 1]):
            target = float(s[_LAUNCH_CORNER - 1])
    lead = np.full(len(grid), -np.inf)
    for df in positions.values():
        rd = _on_grid(df, "race_dist", grid)
        lead = np.fmax(lead, np.nan_to_num(rd, nan=-np.inf))
    reached = np.flatnonzero(lead >= target)
    return float(grid[reached[0]]) if len(reached) else float(grid[0])


def _restart_spans(status_windows: pd.DataFrame | None, launch_s: float
                   ) -> list[tuple[float, float]]:
    """Time spans after each red-flag suspension where the field relaunches.

    A red-flag restart re-forms the field on a bunched grid and launches it again, so the
    order it produces is a start, not overtaking — the same reason the standing start is
    excluded. SC and VSC restarts are deliberately not included: those laps are already
    ``neutralised`` while the pack is together, and the passes after the green flag are
    real racing.
    """
    if status_windows is None or not len(status_windows):
        return []
    out = []
    for r in status_windows.itertuples():
        if str(r.status) == "red":
            out.append((float(r.t_end), float(r.t_end) + max(launch_s, 30.0)))
    return out


class _PaceModel:
    """A driver's normal speed as a function of where they are on the track.

    Comparing a car's speed at the moment it is passed against its own norm *at that point
    of the circuit* is what separates "was overtaken" from "was crawling". A whole-lap time
    comparison misses a car that loses everything in one sector and is fine elsewhere,
    which is exactly the shape of the failure this replaces.
    """

    _BIN_M = 50.0

    def __init__(self, positions: dict[str, pd.DataFrame], track_length_m: float):
        self._n = max(int(track_length_m / self._BIN_M), 1)
        self._med: dict[str, np.ndarray] = {}
        for code, df in positions.items():
            s = _num(df["s"]).to_numpy(float)
            v = _num(df.get("speed")).to_numpy(float)
            ok = np.isfinite(s) & np.isfinite(v) & (v > 0)
            if ok.sum() < 50:
                continue
            b = np.clip((s[ok] / self._BIN_M).astype(int), 0, self._n - 1)
            med = np.full(self._n, np.nan)
            order = np.argsort(b)
            b_s, v_s = b[order], v[ok][order]
            edges = np.searchsorted(b_s, np.arange(self._n + 1))
            for i in range(self._n):
                lo, hi = edges[i], edges[i + 1]
                if hi > lo:
                    med[i] = np.median(v_s[lo:hi])
            self._med[code] = med

    def slow_ratio(self, code: str, s_m: float, speed: float) -> float:
        """Observed speed as a fraction of this driver's own norm there; NaN if unknown."""
        med = self._med.get(code)
        if med is None or not np.isfinite(s_m) or not np.isfinite(speed):
            return np.nan
        i = int(np.clip(s_m / self._BIN_M, 0, self._n - 1))
        ref = med[i]
        if not np.isfinite(ref) or ref <= 0:
            return np.nan
        return float(speed / ref)


def detect_overtakes(
    positions: dict[str, pd.DataFrame],
    laps: pd.DataFrame,
    *,
    official: pd.DataFrame | None = None,
    results: pd.DataFrame | None = None,
    status_windows: pd.DataFrame | None = None,
    corners: pd.DataFrame | None = None,
    marshal_sectors: pd.DataFrame | None = None,
    track_length_m: float | None = None,
    min_dwell_s: float = MIN_DWELL_S,
    grid_step_s: float = GRID_S,
) -> list[dict]:
    """Every durable change of on-track order in a race, each labelled with its cause.

    ``positions`` is ``formation_sim.data.track_position.driver_track_positions`` output —
    per-driver ``t / s / lap / race_dist / speed / off_line`` on the shared track
    coordinate. ``official`` is the F1 timing feed's classification order
    (``track_position.official_positions``); when supplied, a telemetry swap must be
    corroborated by a classification change nearby in time, which rejects the residual
    coordinate noise that no amount of threshold tuning removes on its own.

    Returns events sorted by time, each a JSON-ready dict. Use :func:`summarise` to reduce
    them to counts.
    """
    if not positions or laps is None or not len(laps):
        return []
    grid = _grid_of(positions, grid_step_s)
    if len(grid) < 3:
        return []
    if track_length_m is None or not np.isfinite(track_length_m) or track_length_m <= 0:
        track_length_m = 5000.0

    codes = sorted(positions)
    rd = {c: _on_grid(positions[c], "race_dist", grid) for c in codes}
    lap_g = {c: _on_grid(positions[c], "lap", grid) for c in codes}
    spd = {c: _on_grid(positions[c], "speed", grid) for c in codes}
    off = {c: _on_grid(positions[c], "off_line", grid) for c in codes}
    s_g = {c: _on_grid(positions[c], "s", grid) for c in codes}
    drs_g = {c: _on_grid(positions[c], "drs", grid) for c in codes}

    off_pos: dict[str, np.ndarray] = {}
    if official is not None and len(official):
        for c, g in official.groupby("driver"):
            g = g.drop_duplicates("t").sort_values("t")
            off_pos[str(c)] = _step_on_grid(g["t"].to_numpy(float),
                                            _num(g["position"]).to_numpy(float), grid)

    pits = pit_windows(laps)
    neutral = _neutral_spans(status_windows)
    retired = _retire_lap(results)
    launch_end = _launch_window(positions, corners, track_length_m, grid)
    restarts = _restart_spans(status_windows, launch_end - float(grid[0]))
    pace = _PaceModel(positions, track_length_m)

    hold = max(1, int(round(min_dwell_s / grid_step_s)))
    max_hold = max(hold, int(round(_MAX_HOLD_S / grid_step_s)))
    tol = max(1, int(round(_OFFICIAL_TOL_S / grid_step_s)))
    n = len(grid)

    def line_index(c: str, k: int) -> int:
        """Grid index of ``c``'s next start/finish crossing after ``k``."""
        d = rd[c]
        if not np.isfinite(d[k]):
            return min(k + hold, n - 1)
        nxt = (np.floor(d[k] / track_length_m) + 1.0) * track_length_m
        seg = d[k:min(k + max_hold, n)]
        hit = np.flatnonzero(np.isfinite(seg) & (seg >= nxt))
        return k + int(hit[0]) if len(hit) else min(k + max_hold, n - 1)

    def corroborated(a: str, b: str, k: int) -> bool:
        pa, pb = off_pos.get(a), off_pos.get(b)
        if pa is None or pb is None:
            return True  # no official feed for this pair; telemetry stands alone
        lo, hi = max(0, k - tol), min(n, k + tol + 1)
        d = pa[lo:hi] - pb[lo:hi]
        d = d[np.isfinite(d)]
        if not len(d):
            return False
        # The classification must actually change places over the window — a ahead at some
        # point and behind at another — and the two must be *adjacent* in the order. Cars
        # several positions apart cannot pass each other directly, so a telemetry crossing
        # between them is bad position data (or a lapped car), never a racing move.
        return bool((d < 0).any() and (d > 0).any() and (np.abs(d) == 1).any())

    raw: list[dict] = []
    for i in range(len(codes)):
        a = codes[i]
        for j in range(i + 1, len(codes)):
            b = codes[j]
            d = rd[a] - rd[b]
            sign = np.sign(d)
            valid = np.isfinite(d) & (sign != 0)
            if valid.sum() < hold + 1:
                continue
            # Walk runs of settled order. A run counts as the order *being* one way only
            # once it has lasted the dwell and survived to the passing car's next line
            # crossing; a pass is then a durable run that replaces a different durable one.
            # Comparing against the last confirmed order — rather than against whatever the
            # previous sample happened to say — is what stops a failed lunge scoring twice:
            # once for the car that dived up the inside, and again for the car that kept
            # the place it never actually lost.
            # Seed the baseline from the first sample rather than waiting for a full
            # durable run: at lights-out the order is simply the grid, and demanding that
            # it prove itself over a whole lap first would silently drop any pass made
            # before the leaders complete lap 1.
            first = int(np.argmax(valid))
            confirmed: float | None = float(sign[first])
            gap_since = 0
            k = first
            while k < n:
                if not valid[k]:
                    gap_since += 1
                    if gap_since > max_hold:
                        # Too long blind to attribute a change to anything on track.
                        confirmed = None
                    k += 1
                    continue
                gap_since = 0
                end = k
                while end + 1 < n and valid[end + 1] and sign[end + 1] == sign[k]:
                    end += 1
                gainer, loser = (a, b) if sign[k] > 0 else (b, a)
                needed = max(min(k + hold, n - 1), line_index(gainer, k))
                if end >= needed:
                    if (confirmed is not None and sign[k] != confirmed
                            and corroborated(a, b, k)):
                        raw.append({"k": k, "gainer": gainer, "loser": loser,
                                    "end": end})
                    confirmed = float(sign[k])
                k = end + 1

    raw.sort(key=lambda e: e["k"])

    # Cluster pass: how many distinct drivers went by this loser in the window around it.
    by_loser: dict[str, list[int]] = {}
    for e in raw:
        by_loser.setdefault(e["loser"], []).append(e["k"])

    def cluster_size(loser: str, k: int) -> int:
        ks = by_loser.get(loser, [])
        w = _CLUSTER_WINDOW_S / grid_step_s
        return sum(1 for x in ks if abs(x - k) <= w)

    events: list[dict] = []
    for e in raw:
        k, gainer, loser = e["k"], e["gainer"], e["loser"]
        t = float(grid[k])
        la, lb = lap_g[gainer][k], lap_g[loser][k]
        lap_no = int(round(min(la, lb))) if np.isfinite(la) and np.isfinite(lb) else -1

        # Two cars whose lap counters disagree at the moment they change places are either
        # a lapping, or simply nose-to-tail across the start/finish line with one counter
        # already ticked over. The straddle is the common case and is real racing, so it is
        # told apart by where they are: a straddle only happens within sight of the line.
        lap_delta = lap_g[gainer][k] - lap_g[loser][k]
        straddling = all(
            np.isfinite(v) and min(v, track_length_m - v) < _STRADDLE_M
            for v in (s_g[gainer][k], s_g[loser][k])
        )

        kind = _classify(
            t=t, lap_no=lap_no, gainer=gainer, loser=loser,
            lap_delta=lap_delta, straddling=straddling,
            pits=pits, neutral=neutral, restarts=restarts, launch_end=launch_end,
            retired=retired, pace=pace,
            off_gain=off[gainer][k], off_lose=off[loser][k],
            s_lose=s_g[loser][k], spd_lose=spd[loser][k],
            cluster=cluster_size(loser, k),
        )

        s_at = s_g[gainer][k]
        corner, letter = _nearest_corner(corners, s_at, track_length_m)
        gap = abs(rd[gainer][k] - rd[loser][k])
        v = spd[gainer][k]
        events.append({
            "t": round(t, 2),
            "lap": lap_no,
            "gainer": gainer,
            "loser": loser,
            "kind": kind,
            "s": None if not np.isfinite(s_at) else round(float(s_at), 1),
            "corner": corner,
            "corner_letter": letter,
            "marshal_sector": _marshal_sector(marshal_sectors, s_at),
            "gap_m": None if not np.isfinite(gap) else round(float(gap), 1),
            "drs": bool(drs_g[gainer][k] >= 10) if np.isfinite(drs_g[gainer][k]) else None,
            "speed_kph": None if not np.isfinite(v) else round(float(v), 1),
        })
    return events


def _classify(*, t, lap_no, gainer, loser, lap_delta, straddling,
              pits, neutral, restarts, launch_end, retired, pace, off_gain, off_lose,
              s_lose, spd_lose, cluster) -> str:
    if _in_span(pits.get(gainer), t) or _in_span(pits.get(loser), t):
        return KIND_PIT
    if off_gain is not None and np.isfinite(off_gain) and off_gain > _OFF_LINE_M:
        return KIND_PIT  # the "passing" car is in the pit lane, not on track
    if any(a <= t <= b for a, b in neutral):
        return KIND_NEUTRALISED
    if np.isfinite(lap_delta) and abs(lap_delta) >= 1.0 and not straddling:
        return KIND_LAPPED
    if t <= launch_end or any(a <= t <= b for a, b in restarts):
        return KIND_START
    if _is_attrition(loser, lap_no, retired, pace, off_lose, s_lose, spd_lose, cluster):
        return KIND_ATTRITION
    return KIND_RACING


def _is_attrition(loser, lap_no, retired, pace, off_lose, s_lose, spd_lose, cluster
                  ) -> bool:
    """Was the passed car in trouble rather than simply beaten?

    Any one signal is enough: it is about to retire, it has left the racing line, its pace
    through the pass zone has collapsed against its own norm there, or so many cars are
    going by at once that no plausible amount of racing explains it.
    """
    last = retired.get(loser)
    if last is not None and lap_no >= 0 and lap_no >= last - _TERMINAL_LAPS:
        return True
    if np.isfinite(off_lose) and off_lose > _OFF_LINE_M:
        return True
    if cluster >= _CLUSTER_N_HARD:
        return True
    ratio = pace.slow_ratio(loser, s_lose, spd_lose)
    if np.isfinite(ratio) and ratio < _SLOW_RATIO:
        return True
    return bool(cluster >= _CLUSTER_N and np.isfinite(ratio) and ratio < 0.95)


def _nearest_corner(corners: pd.DataFrame | None, s_m: float, length_m: float):
    if corners is None or not len(corners) or not np.isfinite(s_m):
        return None, ""
    cs = _num(corners["s"]).to_numpy(float)
    d = np.abs(cs - float(s_m))
    d = np.minimum(d, length_m - d)
    i = int(np.nanargmin(d))
    row = corners.iloc[i]
    letter = str(row["Letter"]) if "Letter" in corners.columns else ""
    return int(row["Number"]), ("" if letter in ("nan", "None") else letter)


def _marshal_sector(sectors: pd.DataFrame | None, s_m: float):
    if sectors is None or not len(sectors) or not np.isfinite(s_m):
        return None
    ss = _num(sectors.sort_values("s")["s"]).to_numpy(float)
    i = int(np.searchsorted(ss, float(s_m), side="right") - 1)
    if i < 0:
        i = len(ss) - 1
    return int(sectors.sort_values("s").iloc[i]["Number"])


def by_lap(events: list[dict], total_laps: int, kind: str = KIND_RACING) -> list[int]:
    """Per-lap counts of one kind, as a list of length ``total_laps`` (index 0 = lap 1)."""
    out = [0] * max(int(total_laps), 0)
    for e in events:
        if e.get("kind") != kind:
            continue
        lap = int(e.get("lap", -1))
        if 1 <= lap <= len(out):
            out[lap - 1] += 1
    return out


def summarise(events: list[dict], total_laps: int) -> dict:
    """Reduce an event list to the stored blob: counts, per-lap array, corner histogram.

    ``totals.racing`` is the headline — passes that were actually racing.
    ``totals.gross`` additionally counts cars that were passed while in trouble or being
    lapped, which is roughly what broadcast overtake statistics report; it exists as an
    external cross-check and nothing downstream consumes it.
    """
    counts = {k: 0 for k in KINDS}
    for e in events:
        k = e.get("kind")
        if k in counts:
            counts[k] += 1
    corner_hist: dict[str, int] = {}
    for e in events:
        if e.get("kind") != KIND_RACING:
            continue
        c = e.get("corner")
        if c is not None:
            key = f"{c}{e.get('corner_letter') or ''}"
            corner_hist[key] = corner_hist.get(key, 0) + 1
    return {
        "version": OVERTAKES_VERSION,
        "total_laps": int(total_laps),
        "totals": {
            "racing": counts[KIND_RACING],
            "gross": sum(counts[k] for k in _GROSS),
            "by_kind": counts,
        },
        "by_lap": by_lap(events, total_laps),
        "by_corner": dict(sorted(corner_hist.items(), key=lambda kv: -kv[1])),
        "events": events,
    }
