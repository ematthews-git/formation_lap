"""Where every car was, in one coordinate system shared by the whole field.

The overtake counter needs to answer "who was ahead of whom, when" from telemetry. That
only works if every driver's track position is measured by the *same* function. The older
:func:`collector.driver_progress` was not: it normalised each driver's integrated-speed
distance by that driver's own per-lap min/max, so two cars at the identical physical point
got different numbers (measured at Monaco 2025: 0.30 s of systematic spread across drivers
plus per-lap jitter up to 1.26 s — larger than the real gaps at a track where the field
runs inside a second).

Instead we project every car's raw ``pos_data`` X/Y onto one reference centre line with a
KD-tree, the technique :mod:`fastf1.legacy` uses for driver-ahead. The projection is a
single fixed function of position, so it carries no per-driver or per-lap bias, and the
resulting arc length ``s`` doubles as the key for corner attribution.

Everything here is FastF1-facing and stays behind the collector seam.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd
import scipy.spatial

# pos_data X/Y/Z are in 1/10 m from 2020 onwards (fastf1._api.position_data).
_POS_UNITS_PER_M = 10.0

# Reference line resampling step. FastF1's own trajectory projection uses 0.667 m; 1 m
# keeps the KD-tree small while quantising position finely enough that the residual is
# far below any real racing gap.
_REF_STEP_M = 1.0

# Two reference points can sit close together in X/Y while being far apart along the lap
# — tracks that cross over themselves (Suzuka) or run a return leg alongside the start
# straight. Where the two nearest candidates disagree by more than this, the nearest
# neighbour alone is ambiguous and we disambiguate by continuity with the previous sample.
_AMBIGUOUS_M = 100.0


@dataclass(frozen=True)
class TrackFrame:
    """A track's centre line plus the markers we attribute overtakes to.

    ``s`` is arc length in metres from the start/finish line along ``xy``; ``length_m``
    closes the lap. ``corners`` / ``marshal_sectors`` carry the same ``s`` so an event's
    position maps straight onto a corner number.
    """

    xy: np.ndarray
    s: np.ndarray
    length_m: float
    corners: pd.DataFrame
    marshal_sectors: pd.DataFrame
    _tree: scipy.spatial.cKDTree

    def nearest_corner(self, s_m: float) -> tuple[int | None, str]:
        """Corner number nearest ``s_m`` (wrapping at the line), and its letter."""
        if not len(self.corners) or not np.isfinite(s_m):
            return None, ""
        d = np.abs(self.corners["s"].to_numpy(float) - float(s_m))
        d = np.minimum(d, self.length_m - d)  # the line is a loop
        i = int(np.argmin(d))
        row = self.corners.iloc[i]
        return int(row["Number"]), str(row.get("Letter") or "")

    def marshal_sector(self, s_m: float) -> int | None:
        """Marshal sector containing ``s_m`` — the coarser 'part of the track' bucket."""
        if not len(self.marshal_sectors) or not np.isfinite(s_m):
            return None
        starts = self.marshal_sectors["s"].to_numpy(float)
        i = int(np.searchsorted(starts, float(s_m), side="right") - 1)
        if i < 0:
            i = len(starts) - 1
        return int(self.marshal_sectors.iloc[i]["Number"])


def _clean_xy(df: pd.DataFrame) -> np.ndarray:
    """X/Y as float, with FastF1's missing-sample sentinel removed.

    When a driver's position stream is shorter than the longest one, FastF1 pads it by
    outer-merging and filling ``X = Y = Z = 0`` (``_api.position_data``). Those are not
    coordinates — at Monaco 2025 they were 6.5 % of every driver's rows — and ``Status``
    does not flag them, so they have to be dropped explicitly.
    """
    xyz = df[["X", "Y", "Z"]].to_numpy(float)
    keep = ~np.all(xyz == 0.0, axis=1)
    return xyz[keep, :2], keep


def _resample_closed(xy: np.ndarray, step_m: float) -> tuple[np.ndarray, np.ndarray]:
    """Resample a closed polyline to even ``step_m`` spacing; return (xy, arc length)."""
    xy = np.vstack([xy, xy[:1]])  # close the loop back to the line
    seg = np.linalg.norm(np.diff(xy, axis=0), axis=1)
    s_raw = np.concatenate([[0.0], np.cumsum(seg)]) / _POS_UNITS_PER_M
    total = float(s_raw[-1])
    if not np.isfinite(total) or total <= 0:
        raise ValueError("degenerate reference lap")
    s_new = np.arange(0.0, total, step_m)
    out = np.column_stack([
        np.interp(s_new, s_raw, xy[:, 0]),
        np.interp(s_new, s_raw, xy[:, 1]),
    ])
    return out, s_new


def track_frame(ses) -> TrackFrame | None:
    """Build the shared coordinate frame for a session, or None without telemetry.

    The reference lap is the session's fastest — a clean, on-the-racing-line lap, which
    keeps the projection's off-line residual meaningful (a large residual then means the
    car really is off line: pit lane, spin, or excursion).
    """
    try:
        ref_lap = ses.laps.pick_fastest()
        ref_pos = ref_lap.get_pos_data()
    except Exception:
        return None
    if ref_pos is None or len(ref_pos) < 20:
        return None
    xy, _ = _clean_xy(ref_pos)
    if len(xy) < 20:
        return None
    try:
        line, s = _resample_closed(xy, _REF_STEP_M)
    except ValueError:
        return None
    tree = scipy.spatial.cKDTree(line)

    corners = pd.DataFrame(columns=["Number", "Letter", "s"])
    sectors = pd.DataFrame(columns=["Number", "s"])
    try:
        ci = ses.get_circuit_info()
    except Exception:
        ci = None
    if ci is not None:
        # Project the circuit markers through the *same* KD-tree rather than using
        # fastf1's own `Distance` column: that one is measured against an integrated-speed
        # distance in metres, which is a different scale from this geometric arc length.
        def _markers(df: pd.DataFrame, with_letter: bool) -> pd.DataFrame:
            if df is None or not len(df):
                return pd.DataFrame(columns=["Number", "Letter", "s"] if with_letter
                                    else ["Number", "s"])
            pts = df[["X", "Y"]].to_numpy(float)
            _, idx = tree.query(pts, workers=2)
            cols = {"Number": df["Number"].astype(int).to_numpy(),
                    "s": s[np.clip(idx, 0, len(s) - 1)]}
            if with_letter:
                cols["Letter"] = df["Letter"].astype(str).to_numpy()
            return pd.DataFrame(cols).sort_values("s").reset_index(drop=True)

        corners = _markers(ci.corners, True)
        sectors = _markers(ci.marshal_sectors, False)

    return TrackFrame(xy=line, s=s, length_m=float(s[-1] + _REF_STEP_M),
                      corners=corners, marshal_sectors=sectors, _tree=tree)


def _project(frame: TrackFrame, xy: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Project points onto the reference line -> (arc length, off-line distance in m).

    Nearest-neighbour alone is wrong where the line passes close to itself. For those
    samples only, pick whichever of the two candidates continues the car's previous
    position — a car cannot teleport across the circuit between two 220 ms samples.
    """
    dist, idx = frame._tree.query(xy, k=2, workers=2)
    s_cand = frame.s[np.clip(idx, 0, len(frame.s) - 1)]
    s_out = s_cand[:, 0].copy()
    off = dist[:, 0] / _POS_UNITS_PER_M

    gap = np.abs(s_cand[:, 0] - s_cand[:, 1])
    gap = np.minimum(gap, frame.length_m - gap)
    ambiguous = np.flatnonzero(gap > _AMBIGUOUS_M)
    for i in ambiguous:
        if i == 0:
            continue
        prev = s_out[i - 1]
        a, b = s_cand[i, 0], s_cand[i, 1]
        da = abs(a - prev)
        db = abs(b - prev)
        da = min(da, frame.length_m - da)
        db = min(db, frame.length_m - db)
        if db < da:
            s_out[i] = b
            off[i] = dist[i, 1] / _POS_UNITS_PER_M
    return s_out, off


def _race_distance(s: np.ndarray, lap: np.ndarray, length_m: float) -> np.ndarray:
    """Monotonic distance covered, in metres.

    Summing ``(lap - 1) * L + s`` directly does not work: the timing feed's lap increment
    and the telemetry's ``s`` wrap are milliseconds apart, so at every line crossing the
    sum jumps a whole lap in one direction and back in the other, and patching those jumps
    by integrating differences lets a single bad patch persist for the rest of the race.

    Instead count laps from the telemetry itself, then shift the whole series by the
    single whole-lap offset that best matches the timing feed. Because both lap counts are
    integers advancing in lockstep, their difference is stable and a boundary disagreement
    can move the median but cannot introduce a step.

    Crossings are counted in *both* directions. Right at the line ``s = 0`` and ``s = L``
    are the same tarmac, so the projection flips between them for a sample or two; counting
    only the forward drop would score each flicker as a completed lap, which is enough to
    leave a car reading a full lap out of position for the rest of the race.
    """
    d = np.diff(s)
    half = length_m / 2.0
    crossings = np.zeros(len(s))
    crossings[1:] = (d < -half).astype(float) - (d > half).astype(float)
    tel_lap = 1.0 + np.cumsum(crossings)
    shift = np.nanmedian(lap - tel_lap)
    shift = 0.0 if not np.isfinite(shift) else float(np.round(shift))
    return (tel_lap - 1.0 + shift) * length_m + s


def driver_track_positions(ses, frame: TrackFrame | None = None
                           ) -> dict[str, pd.DataFrame]:
    """Per-driver track position: ``{code: DataFrame(t, s, lap, race_dist, speed, drs, off_line)}``.

    ``t`` is session seconds, ``s`` metres along the lap from the line, ``race_dist``
    metres covered since the start, ``off_line`` metres from the racing line (large in the
    pit lane or after an excursion). Ordering drivers by ``race_dist`` at a given ``t``
    gives the on-track running order.

    Returns ``{}`` without telemetry so callers can fall back to lap resolution.
    """
    if frame is None:
        frame = track_frame(ses)
    if frame is None:
        return {}
    laps = ses.laps
    if laps is None or not len(laps):
        return {}
    try:
        pos_data = ses.pos_data
        car_data = ses.car_data
    except Exception:
        return {}

    num_to_code = (laps[["DriverNumber", "Driver"]].dropna().drop_duplicates()
                   .set_index("DriverNumber")["Driver"].to_dict())

    out: dict[str, pd.DataFrame] = {}
    for num, code in num_to_code.items():
        pos = pos_data.get(str(num))
        if pos is None or len(pos) < 10:
            continue
        xy, keep = _clean_xy(pos)
        if len(xy) < 10:
            continue
        t = (pd.to_timedelta(pos["SessionTime"].to_numpy()[keep], errors="coerce")
             .total_seconds().to_numpy(float))
        finite = np.isfinite(t)
        xy, t = xy[finite], t[finite]
        if len(t) < 10:
            continue
        order = np.argsort(t)
        xy, t = xy[order], t[order]

        s, off = _project(frame, xy)

        dl = laps[laps["DriverNumber"] == num].sort_values("LapNumber")
        starts = pd.DataFrame({
            "LapStartTime": pd.to_timedelta(dl["LapStartTime"], errors="coerce")
            .dt.total_seconds(),
            "lap": dl["LapNumber"].astype(float),
        })
        # Lap 1 has no recorded start (standing start); anchor it at the first sample so
        # opening-lap positions still land on lap 1.
        starts["LapStartTime"] = starts["LapStartTime"].fillna(t[0])
        starts = starts.dropna().sort_values("LapStartTime")
        if not len(starts):
            continue
        df = pd.merge_asof(
            pd.DataFrame({"t": t, "s": s, "off_line": off}),
            starts.rename(columns={"LapStartTime": "t"}),
            on="t", direction="backward",
        ).dropna(subset=["lap"])
        if len(df) < 10:
            continue

        df["race_dist"] = _race_distance(df["s"].to_numpy(float),
                                         df["lap"].to_numpy(float), frame.length_m)

        car = car_data.get(str(num))
        if car is not None and len(car):
            chan = pd.DataFrame({
                "t": pd.to_timedelta(car["SessionTime"], errors="coerce")
                     .dt.total_seconds(),
                "speed": pd.to_numeric(car["Speed"], errors="coerce"),
                "drs": pd.to_numeric(car.get("DRS"), errors="coerce"),
            }).dropna(subset=["t", "speed"]).sort_values("t")
            # asof rather than merge_channels: the position and car streams sample at
            # different rates (220 vs 240 ms) and merge_channels interpolates X/Y
            # quadratically, which overshoots on sudden changes.
            df = pd.merge_asof(df, chan, on="t", direction="nearest", tolerance=0.5)
        else:
            df["speed"] = np.nan
            df["drs"] = np.nan

        # Drop post-flag cool-down: a car that has finished or retired decelerates and the
        # field streams past it, which would otherwise read as a flurry of last-lap passes.
        t_end = pd.to_timedelta(dl["Time"], errors="coerce").dt.total_seconds().max()
        if pd.notna(t_end):
            df = df[df["t"] <= float(t_end)]
        df = df.drop_duplicates("t")
        if len(df) >= 10:
            out[str(code)] = df.reset_index(drop=True)
    return out


def official_positions(ses) -> pd.DataFrame:
    """F1's own classification order over time: ``[t, driver, position, interval_s]``.

    FastF1 parses this stream and then throws it away — ``Session._load_laps_data`` keeps
    only the per-lap frame. It comes from the same cached ``timing_data`` page the lap load
    already fetches, so reading it costs no extra API requests, and it is the sport's own
    answer to "who was classified where", updated roughly every 3-4 seconds. Used to
    corroborate telemetry swaps: a swap the official feed never registers is coordinate
    noise, and a classification change with no on-track swap is a pit or penalty artefact.

    Empty frame when the stream is unavailable.
    """
    empty = pd.DataFrame(columns=["t", "driver", "position", "interval_s"])
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from fastf1 import _api
        _, stream = _api.timing_data(ses.api_path)
    except Exception:
        return empty
    if stream is None or not len(stream) or "Position" not in stream:
        return empty
    laps = ses.laps
    num_to_code = (laps[["DriverNumber", "Driver"]].dropna().drop_duplicates()
                   .set_index("DriverNumber")["Driver"].to_dict())
    out = pd.DataFrame({
        "t": pd.to_timedelta(stream["Time"], errors="coerce").dt.total_seconds(),
        "driver": stream["Driver"].astype(str).map(num_to_code),
        "position": pd.to_numeric(stream["Position"], errors="coerce"),
        # "+1.234" parses; the feed also emits "LAP 1"/"LAP 0" for lapped cars, which
        # coerce to NaN — exactly the rows where an interval is meaningless anyway.
        "interval_s": pd.to_numeric(stream["IntervalToPositionAhead"], errors="coerce"),
    }).dropna(subset=["t", "driver", "position"])
    return out.sort_values("t").reset_index(drop=True)
