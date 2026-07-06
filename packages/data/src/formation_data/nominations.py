"""Bridge to the simulator's Pirelli compound nominations.

The per-weekend tyre allocation (which C-numbers are the soft/medium/hard) is
maintained in exactly ONE place: the simulator's ``config/nominations.yaml`` (read via
``formation_sim.params.nominations``). The sim uses it to translate historical laps
into the target year's label space; the data pipeline reads the *same* table here to
fill ``race_weekends.{soft,medium,hard}_compound``, so the API — and the frontend that
renders it — show the real per-track allocation without a second copy to keep in sync.

Nominations are keyed by FastF1 event Location. The circuits seed stores each venue's
canonical (current) ``fastf1_location``, but a few venues were renamed across seasons
(Miami/Miami Gardens, Yas Island/Yas Marina, Monaco/Monte Carlo) and the nominations
file records whichever spelling was current when the allocation was published. We
therefore try every name a venue has used (``fastf1_client.aliases_for``) so the lookup
hits regardless of spelling.
"""

from __future__ import annotations

from formation_sim.params.nominations import compound_nomination

from formation_data.sources.fastf1_client import aliases_for


def compounds_for(season: int, fastf1_location: str) -> tuple[str, str, str] | None:
    """Nominated ``(soft, medium, hard)`` compound codes for the circuit at
    ``fastf1_location`` in ``season`` — e.g. ``("C5", "C4", "C3")`` — or ``None`` when
    the circuit-year has no nomination (a new venue, or one absent from the file)."""
    for name in aliases_for(fastf1_location):
        triple = compound_nomination(season, name)
        if triple is not None:
            hard, medium, soft = triple
            return (f"C{soft}", f"C{medium}", f"C{hard}")
    return None
