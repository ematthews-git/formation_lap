"""Pre-season job — load the driver lineup for a season.

Cadence: yearly, after team lineups are public (typically mid-January through pre-season testing).

Source: sources.jolpica_client.get_drivers(season).
Upsert key: Driver UniqueConstraint(driver_id, season).
"""

from __future__ import annotations

import logging

from sqlalchemy import Connection

logger = logging.getLogger(__name__)


def run(conn: Connection, *, season: int) -> None:
    # TODO:
    #   from formation_data import domain, repositories, schema
    #   from formation_data.sources import jolpica_client
    #   raw = jolpica_client.get_drivers(season)
    #   items = [domain.Driver(
    #       driver_id=d["driverId"],
    #       full_name=f"{d['givenName']} {d['familyName']}",
    #       nationality=d["nationality"],
    #       team=...,        # Jolpica returns drivers and constructors separately — join here
    #       season=season,
    #   ) for d in raw]
    #   repositories.upsert(conn, schema.drivers, items, ["driver_id", "season"])
    logger.info("pre_season.drivers.run season=%s (skeleton)", season)
