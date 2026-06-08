"""Pre-season job — load the driver lineup for a season.

Cadence: yearly, after team lineups are public (typically mid-January through pre-season testing).

Source: sources.jolpica_client.get_drivers(season).
Upsert key: Driver UniqueConstraint(driver_id, season).
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def run(session: Session, *, season: int) -> None:
    # TODO:
    #   from formation_data.sources import jolpica_client
    #   drivers = jolpica_client.get_drivers(season)
    #   for d in drivers:
    #       stmt = insert(Driver).values(
    #           driver_id=d["driverId"],
    #           full_name=f"{d['givenName']} {d['familyName']}",
    #           nationality=d["nationality"],
    #           team=...,        # join with constructor data — Jolpica returns drivers and constructors separately
    #           season=season,
    #       ).on_conflict_do_update(
    #           index_elements=["driver_id", "season"],
    #           set_={"full_name": ..., "team": ..., ...},
    #       )
    #       session.execute(stmt)
    logger.info("pre_season.drivers.run season=%s (skeleton)", season)
