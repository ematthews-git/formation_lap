"""Unit tests for the pure geometry pipeline in jobs.pre_season.track_maps.

No FastF1 / network — the rotate/normalise/simplify/serialise helpers operate on
plain coordinate arrays.
"""

from __future__ import annotations

import numpy as np

from formation_data.jobs.pre_season import track_maps as tm


def test_to_svg_path_format():
    pts = np.array([[10.0, 20.0], [30.0, 40.0], [50.0, 60.0]])
    assert tm._to_svg_path(pts) == "M10.0 20.0 L30.0 40.0 L50.0 60.0 Z"


def test_simplify_drops_collinear_points():
    # A straight run of points collapses to just the endpoints.
    line = np.array([[0.0, 0.0], [1.0, 0.0], [2.0, 0.0], [3.0, 0.0], [4.0, 0.0]])
    out = tm._simplify(line, epsilon=0.6)
    assert len(out) == 2
    assert out[0].tolist() == [0.0, 0.0]
    assert out[-1].tolist() == [4.0, 0.0]


def test_simplify_keeps_a_real_corner():
    corner = np.array([[0.0, 0.0], [2.0, 0.0], [4.0, 0.0], [4.0, 4.0]])
    out = tm._simplify(corner, epsilon=0.6)
    # The (4,0) corner must survive; the mid-line (2,0) should not.
    kept = {tuple(p) for p in out.tolist()}
    assert (4.0, 0.0) in kept
    assert (2.0, 0.0) not in kept


def test_to_viewbox_fits_and_centers():
    square = np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]])
    out = tm._to_viewbox(square, w=400, h=248, pad=14)
    xs, ys = out[:, 0], out[:, 1]
    # Everything inside the padded viewBox.
    assert xs.min() >= 14 - 1e-6 and xs.max() <= 400 - 14 + 1e-6
    assert ys.min() >= 14 - 1e-6 and ys.max() <= 248 - 14 + 1e-6
    # Square is centered (equal margins horizontally and vertically).
    assert abs(xs.min() - (400 - xs.max())) < 1e-6
    assert abs(ys.min() - (248 - ys.max())) < 1e-6


def test_build_track_path_is_closed_and_in_bounds():
    # A unit square loop; zero rotation.
    x = [0, 1, 1, 0, 0]
    y = [0, 0, 1, 1, 0]
    path = tm.build_track_path(x, y, rotation_deg=0.0)
    assert path.startswith("M")
    assert path.endswith(" Z")
    coords = [
        float(tok[1:]) if tok[0] in "ML" else float(tok)
        for tok in path[:-2].replace("M", "M ").replace("L", "L ").split()
        if tok not in ("M", "L")
    ]
    assert all(0 <= c <= 400 for c in coords)
