"""Pre-season job — generate a circuit-outline SVG path from FastF1 telemetry.

Cadence: rare. Circuit shapes don't change, so run once (or when a new venue
joins the calendar) and store the result on the `circuits` table.

For each circuit we trace the fastest lap's position telemetry from the most
recent season it was raced, then run a single shared normalisation pipeline so
every map comes out visually consistent:

  rotate (canonical orientation) → scale-to-fit a fixed viewBox → simplify (RDP)
  → emit an SVG path string.

The shared viewBox + uniform pipeline guarantee consistent sizing/orientation;
the telemetry guarantees the shape is the real racing line. Output is stored in
`circuits.track_outline` (viewBox "0 0 400 248").

Safety: circuits never raced in the lookback window (new venues without
telemetry) are skipped and left null; a FastF1 rate-limit error is re-raised
(cache makes a re-run resume for free); any other per-circuit load error is
logged and skipped so one bad circuit doesn't sink the batch.
"""

from __future__ import annotations

import logging

import numpy as np
from fastf1.exceptions import RateLimitExceededError
from sqlalchemy import Connection

from formation_data import repositories, schema
from formation_data.sources import fastf1_client

logger = logging.getLogger(__name__)

# How many seasons back to search for a running of each circuit.
LOOKBACK_SEASONS = 4
# Output canvas — matches the frontend's circuit SVG viewBox.
VIEWBOX_W = 400
VIEWBOX_H = 248
PADDING = 14
# Ramer–Douglas–Peucker tolerance in viewBox units (higher = fewer points).
SIMPLIFY_TOLERANCE = 0.6


def run(conn: Connection, *, season: int, circuit_id: str | None = None) -> None:
    """Generate outlines for one circuit (`circuit_id`) or all of them.

    `season` is the most recent season to source telemetry from; older seasons
    are tried if a circuit wasn't raced that year.
    """
    if circuit_id is not None:
        circuit = repositories.get_circuit(conn, circuit_id)
        if circuit is None:
            logger.warning("track_maps.run: unknown circuit %s", circuit_id)
            return
        circuits = [circuit]
    else:
        circuits = repositories.list_circuits(conn)

    generated = 0
    for circuit in circuits:
        found = _source_round(season, circuit.fastf1_location)
        if found is None:
            logger.warning(
                "track_maps.run: %s not raced in the %s seasons up to %s; skipping",
                circuit.circuit_id,
                LOOKBACK_SEASONS,
                season,
            )
            continue
        src_season, src_round = found

        try:
            x, y, rotation = fastf1_client.get_fastest_lap_track(src_season, src_round)
        except RateLimitExceededError:
            logger.error(
                "track_maps.run: FastF1 rate limit hit on %s; cached progress "
                "resumes a re-run for free.",
                circuit.circuit_id,
            )
            raise
        except Exception as exc:  # noqa: BLE001 - one bad circuit shouldn't sink the batch
            logger.warning(
                "track_maps.run: could not trace %s from %s R%s (%s); skipping",
                circuit.circuit_id,
                src_season,
                src_round,
                exc,
            )
            continue

        if x is None or len(x) < 3:
            logger.warning("track_maps.run: no usable telemetry for %s", circuit.circuit_id)
            continue

        circuit.track_outline = build_track_path(x, y, rotation)
        repositories.upsert(conn, schema.circuits, [circuit], ["circuit_id"])
        generated += 1
        logger.info(
            "track_maps.run: %s traced from %s R%s",
            circuit.circuit_id,
            src_season,
            src_round,
        )

    logger.info("track_maps.run season=%s generated=%d", season, generated)


def _source_round(season: int, fastf1_location: str) -> tuple[int, int] | None:
    """Most recent (season, round) within the lookback window for a circuit."""
    for s in range(season, season - LOOKBACK_SEASONS, -1):
        rounds = fastf1_client.rounds_for_location(s, fastf1_location)
        if rounds:
            return s, rounds[0]
    return None


# --- geometry pipeline (pure; unit-tested) ---


def build_track_path(x, y, rotation_deg: float) -> str:
    """Telemetry X/Y + rotation → a normalised, simplified SVG path string."""
    track = np.column_stack([np.asarray(x, dtype=float), np.asarray(y, dtype=float)])
    track = _rotate(track, rotation_deg)
    points = _to_viewbox(track)
    points = _simplify(points, SIMPLIFY_TOLERANCE)
    return _to_svg_path(points)


def _rotate(track: np.ndarray, rotation_deg: float) -> np.ndarray:
    """Rotate points by the circuit's canonical angle (FastF1 convention)."""
    angle = rotation_deg / 180.0 * np.pi
    rot = np.array(
        [[np.cos(angle), np.sin(angle)], [-np.sin(angle), np.cos(angle)]]
    )
    return track @ rot


def _to_viewbox(
    points: np.ndarray, w: int = VIEWBOX_W, h: int = VIEWBOX_H, pad: int = PADDING
) -> np.ndarray:
    """Uniformly scale + center points into the viewBox, flipping Y for SVG."""
    xs, ys = points[:, 0], points[:, 1]
    minx, maxx = xs.min(), xs.max()
    miny, maxy = ys.min(), ys.max()
    span_x = (maxx - minx) or 1.0
    span_y = (maxy - miny) or 1.0
    scale = min((w - 2 * pad) / span_x, (h - 2 * pad) / span_y)
    off_x = (w - span_x * scale) / 2
    off_y = (h - span_y * scale) / 2
    svg_x = off_x + (xs - minx) * scale
    svg_y = off_y + (maxy - ys) * scale  # flip: telemetry Y is up, SVG Y is down
    return np.column_stack([svg_x, svg_y])


def _simplify(points: np.ndarray, epsilon: float) -> np.ndarray:
    """Ramer–Douglas–Peucker simplification (iterative, keeps endpoints)."""
    n = len(points)
    if n < 3:
        return points
    keep = np.zeros(n, dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        start, end = stack.pop()
        seg = points[end] - points[start]
        seg_len = float(np.hypot(seg[0], seg[1])) or 1e-9
        d_max, idx = 0.0, -1
        for i in range(start + 1, end):
            # perpendicular distance from point i to the start–end segment
            # (2D cross product, written out — np.cross on 2D is deprecated)
            v = points[i] - points[start]
            d = abs(seg[0] * v[1] - seg[1] * v[0]) / seg_len
            if d > d_max:
                d_max, idx = d, i
        if d_max > epsilon and idx != -1:
            keep[idx] = True
            stack.append((start, idx))
            stack.append((idx, end))
    return points[keep]


def _to_svg_path(points: np.ndarray) -> str:
    """Closed SVG path: 'M x y L x y … Z' with 1-decimal coordinates."""
    cmds = [
        f"{'M' if i == 0 else 'L'}{x:.1f} {y:.1f}"
        for i, (x, y) in enumerate(points)
    ]
    return " ".join(cmds) + " Z"
