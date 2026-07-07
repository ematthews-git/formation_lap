"""Per-candidate outcome distributions from Monte-Carlo sims (scoring only).

This module summarises simulation output; it never ranks or prunes — selection is a
separate concern (``selection/selector.py``).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class Outcome:
    finishes: np.ndarray    # finishing positions across sims
    race_times: np.ndarray  # race times (NaN when the driver retired)

    @property
    def mean_finish(self) -> float:
        """Unconditional mean finishing position (DNF counts as its classified place)."""
        return float(np.mean(self.finishes))

    @property
    def mean_finish_classified(self) -> float:
        """Expected finish *given the driver finished* — the intuitive headline number,
        not inflated by DNF sims (matches the paper's 'position given finished')."""
        m = ~np.isnan(self.race_times)
        return float(np.mean(self.finishes[m])) if m.any() else float(np.max(self.finishes))

    @property
    def median_finish(self) -> float:
        return float(np.median(self.finishes))

    @property
    def p_win(self) -> float:
        return float(np.mean(self.finishes == 1))

    @property
    def p_podium(self) -> float:
        return float(np.mean(self.finishes <= 3))

    @property
    def p_points(self) -> float:
        return float(np.mean(self.finishes <= 10))

    @property
    def p_dnf(self) -> float:
        return float(np.mean(np.isnan(self.race_times)))

    @property
    def mean_race_time(self) -> float:
        rt = self.race_times[~np.isnan(self.race_times)]
        return float(np.mean(rt)) if len(rt) else float("nan")

    def finish_ci(self, lo=5, hi=95) -> tuple[float, float]:
        return float(np.percentile(self.finishes, lo)), float(np.percentile(self.finishes, hi))

    def distribution(self, n_positions: int, classified: bool = False) -> dict[int, float]:
        """Finishing-position distribution over 1..n_positions. With ``classified=True``,
        retirement sims are dropped and the mass is renormalised over the sims that
        finished (i.e. the distribution *given the driver finished*)."""
        fin = self.finishes
        if classified:
            fin = fin[~np.isnan(self.race_times)]
        if not len(fin):
            return {p: 0.0 for p in range(1, n_positions + 1)}
        vals, counts = np.unique(fin.astype(int), return_counts=True)
        d = {int(v): float(c) / len(fin) for v, c in zip(vals, counts)}
        return {p: d.get(p, 0.0) for p in range(1, n_positions + 1)}
