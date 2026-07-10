"""Preliminary (pre-weekend) race context.

For an upcoming race there is no practice or qualifying yet, so we lean on:
  * the current-season entry list and *relative* form (latest completed dry weekend),
    transferred onto the target circuit's lap-time scale, and
  * the previous year at this circuit for the expected grid order.
Everything else (params, circuit profile, plausibility prior) is identical to the
post-quali path, so generation / evaluation / selection are unchanged.
"""
from __future__ import annotations

import logging
from datetime import date

import numpy as np
import pandas as pd

from formation_sim.context.postquali import WeekendContext
from formation_sim.data import collector
from formation_sim.data.schema import DRY_COMPOUNDS
from formation_sim.generation.plausibility import build_strategy_prior
from formation_sim.params import pace
from formation_sim.params.circuit import get_profile
from formation_sim.settings import load_settings

logger = logging.getLogger(__name__)


def _prev_round(year: int, circuit: str) -> int | None:
    try:
        sched = collector.get_schedule(year)
    except Exception:
        return None
    match = sched[sched["Location"] == circuit]
    return int(match["RoundNumber"].iloc[0]) if len(match) else None


def _load_last_completed_race(year: int, rnd: int, sched: pd.DataFrame,
                              today: date | None = None):
    """Load the most recent *completed* race before round `rnd`, for the entry-list seed.

    "Completed" is taken from the calendar (race date on or before today) and then confirmed
    by data availability — FastF1 can lag a few hours after a race — walking back a round at a
    time when the latest one isn't published yet. This avoids assuming ``rnd - 1`` (or a static
    config round) actually ran: mid-season the previous round may be cancelled, postponed, or
    just not uploaded yet. Returns ``(session, round)``, or ``(None, None)`` when there is no
    usable completed race (e.g. the season opener).
    """
    today = today or date.today()
    done = sched[
        (sched["RoundNumber"] < rnd) & (sched["EventDate"] <= pd.Timestamp(today))
    ]
    for r in sorted(done["RoundNumber"].astype(int), reverse=True):
        ses = collector.load_session(year, r, "R", weather=False)
        if ses is not None:
            return ses, r
    return None, None


def build_prelim_context(year: int, rnd: int, params, profiles, cfg=None) -> WeekendContext:
    cfg = cfg or load_settings()
    sched = collector.get_schedule(year)
    circuit = str(sched[sched["RoundNumber"] == rnd]["Location"].iloc[0])
    profile = get_profile(circuit, profiles, params.lap)

    # Entry list from the latest *actually completed* current-season race (determined from the
    # calendar + data availability, not a static config round that assumes rnd-1 has run).
    cur_race, last = _load_last_completed_race(year, rnd, sched)
    if cur_race is None:
        raise ValueError(
            f"no completed current-season race to seed prelim before round {rnd}"
        )
    logger.info("prelim %s R%s: entry list seeded from last completed round %s", year, rnd, last)
    cur_res = collector.session_results(cur_race)
    teams = {str(r["driver"]): str(r["team"]) for _, r in cur_res.iterrows()}
    entry = list(teams)

    # Expected pace: robust current-season form (many races), re-anchored to the target
    # circuit scale. Falls back to the previous year's quali at this circuit, then to a
    # flat field if neither is available (e.g. season opener / brand-new circuit).
    form = pace.season_form_delta(year, params.lap, cfg)
    anchor = profile.base_lap_time
    if form:
        med = float(np.median(list(form.values())))
        base_pace = {d: anchor + form.get(d, med + 0.3) for d in entry}
    else:
        prev = pace.quali_pace(year - 1, _prev_round(year - 1, circuit))
        med = float(np.median(list(prev.values()))) if prev else anchor
        base_pace = {d: (prev.get(d, med + 0.5) if prev else anchor) for d in entry}

    # Grid is *consistent* with predicted pace: fastest expected car starts on pole. This
    # avoids the contradiction of seeding a slow-pace driver onto the front row.
    grid = {d: i + 1 for i, d in enumerate(sorted(entry, key=lambda d: base_pace[d]))}

    prior = build_strategy_prior(circuit, cfg, before=(year, rnd))
    return WeekendContext(
        year=year, round=rnd, circuit=circuit, profile=profile, params=params,
        prior=prior, grid=grid, base_pace=base_pace, teams=teams,
        allocation=tuple(DRY_COMPOUNDS), cfg=cfg, mode="prelim",
    )
