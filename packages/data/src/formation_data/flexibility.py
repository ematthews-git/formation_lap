"""Strategy flexibility — how many genuinely-distinct strategies are in play at a circuit.

A track is *flexible* when the race can credibly be run several ways: more than one stop
count is live AND plausibility mass is spread across several compound sequences rather than
piled onto a single dominant plan. A track is *rigid* when one stop count and one sequence
dominate — a de-facto forced strategy.

Each ingredient is measured with the inverse-Simpson effective count (``1 / Σ pᵢ²``) — the
"effective number of options" a distribution carries: 1.0 when a single option owns all the
mass, rising toward N as mass spreads evenly over N options. The circuit's flexibility is
the geometric mean of the two effective counts (stop-count spread × sequence spread).

The absolute score isn't meaningful on its own; the frontend surfaces a circuit's
PERCENTILE among the calendar (rank 1 = most flexible), mirroring the tyre-degradation rank.
The cross-weekend ranking lives in the repository layer, which holds the calendar data —
this module is pure math over one weekend's numbers plus the field of peers to rank against.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping


def effective_count(weights: Iterable[float | None]) -> float | None:
    """Inverse-Simpson effective number of options from non-negative weights.

    ``1 / Σ pᵢ²`` over the mass-normalised positive weights: 1.0 when a single option
    carries all the mass, rising toward the option count as mass spreads evenly. ``None``
    when no option has positive mass (nothing to measure)."""
    vals = [float(w) for w in weights if w is not None and w > 0]
    total = sum(vals)
    if total <= 0:
        return None
    return 1.0 / sum((w / total) ** 2 for w in vals)


def flexibility_score(
    stop_distribution: Mapping[str, float | None] | None,
    plausibilities: Iterable[float | None],
) -> float | None:
    """Geometric mean of the stop-count and shown-strategy effective counts.

    ``stop_distribution`` is the sim's ``stop_count_distribution`` (stop count -> share);
    ``plausibilities`` are the shown sim strategies' plausibility masses. ``None`` when
    either ingredient is missing (no stop distribution, or no plausible strategy)."""
    stops = effective_count((stop_distribution or {}).values())
    sequences = effective_count(plausibilities)
    if stops is None or sequences is None:
        return None
    return (stops * sequences) ** 0.5


def rank_of(score: float, field: Iterable[float]) -> dict:
    """Rank ``score`` among ``field`` (which must include ``score`` itself), highest first.

    Returns ``{"score", "rank", "of"}`` where rank 1 = the most flexible circuit and
    ``of`` = the number of circuits scored. Ties share the better rank, matching the
    degradation rank (see ``report.stats._deg_rank``)."""
    scores = list(field)
    rank = 1 + sum(1 for s in scores if s > score)
    return {"score": round(float(score), 4), "rank": rank, "of": len(scores)}
