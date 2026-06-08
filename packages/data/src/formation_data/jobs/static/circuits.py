"""Static job — seed the Circuit table from the hand-curated list.

Cadence: rare. Re-run only when the FIA calendar gains/loses a circuit, when sm_zones
are confirmed, or when track measurements change.

Data is hand written. sm_zones yet to be confirmed for future races (currently reflects DRS zones)
"""

from __future__ import annotations

import logging

from sqlalchemy import Connection
from formation_data.domain import Circuit

logger = logging.getLogger(__name__)


def run(conn: Connection) -> None:
    from formation_data import repositories, schema

    repositories.upsert(
        conn, table=schema.circuits, items=CIRCUITS, conflict_cols=["circuit_id"]
    )
    logger.info("static.circuits.run")


CIRCUITS = [
    Circuit(
        circuit_id="melbourne",
        event_name="Australian Grand Prix",
        country="Australia",
        track_length_km=5.278,
        num_corners=14,
        num_laps=58,
        sm_zones=5,
    ),
    Circuit(
        circuit_id="shanghai",
        event_name="Chinese Grand Prix",
        country="China",
        track_length_km=5.451,
        num_corners=16,
        num_laps=56,
        sm_zones=4,
    ),
    Circuit(
        circuit_id="suzuka",
        event_name="Japanese Grand Prix",
        country="Japan",
        track_length_km=5.807,
        num_corners=18,
        num_laps=53,
        sm_zones=2,
    ),
    Circuit(
        circuit_id="miami",
        event_name="Miami Grand Prix",
        country="United States",
        track_length_km=5.412,
        num_corners=19,
        num_laps=57,
        sm_zones=3,
    ),
    Circuit(
        circuit_id="montreal",
        event_name="Canadian Grand Prix",
        country="Canada",
        track_length_km=4.361,
        num_corners=14,
        num_laps=70,
        sm_zones=3,
    ),
    Circuit(
        circuit_id="monaco",
        event_name="Monaco Grand Prix",
        country="Monaco",
        track_length_km=3.337,
        num_corners=19,
        num_laps=78,
        sm_zones=0,
    ),
    Circuit(
        circuit_id="barcelona",
        event_name="Barcelona-Catalunya Grand Prix",
        country="Spain",
        track_length_km=4.657,
        num_corners=16,
        num_laps=66,
        sm_zones=2,
    ),
    Circuit(
        circuit_id="red_bull_ring",
        event_name="Austrian Grand Prix",
        country="Austria",
        track_length_km=4.318,
        num_corners=10,
        num_laps=71,
        sm_zones=3,
    ),
    Circuit(
        circuit_id="silverstone",
        event_name="British Grand Prix",
        country="United Kingdom",
        track_length_km=5.891,
        num_corners=18,
        num_laps=52,
        sm_zones=2,
    ),
    Circuit(
        circuit_id="spa",
        event_name="Belgian Grand Prix",
        country="Belgium",
        track_length_km=7.004,
        num_corners=19,
        num_laps=44,
        sm_zones=2,
    ),
    Circuit(
        circuit_id="hungaroring",
        event_name="Hungarian Grand Prix",
        country="Hungary",
        track_length_km=4.381,
        num_corners=14,
        num_laps=70,
        sm_zones=2,
    ),
    Circuit(
        circuit_id="zandvoort",
        event_name="Dutch Grand Prix",
        country="Netherlands",
        track_length_km=4.259,
        num_corners=14,
        num_laps=72,
        sm_zones=2,
    ),
    Circuit(
        circuit_id="monza",
        event_name="Italian Grand Prix",
        country="Italy",
        track_length_km=5.793,
        num_corners=11,
        num_laps=53,
        sm_zones=2,
    ),
    Circuit(
        circuit_id="madrid",
        event_name="Spanish Grand Prix",
        country="Spain",
        track_length_km=5.476,
        num_corners=22,
        num_laps=57,
        sm_zones=3,
    ),
    Circuit(
        circuit_id="baku",
        event_name="Azerbaijan Grand Prix",
        country="Azerbaijan",
        track_length_km=6.003,
        num_corners=20,
        num_laps=51,
        sm_zones=2,
    ),
    Circuit(
        circuit_id="singapore",
        event_name="Singapore Grand Prix",
        country="Singapore",
        track_length_km=4.940,
        num_corners=19,
        num_laps=62,
        sm_zones=3,
    ),
    Circuit(
        circuit_id="austin",
        event_name="United States Grand Prix",
        country="United States",
        track_length_km=5.513,
        num_corners=20,
        num_laps=56,
        sm_zones=2,
    ),
    Circuit(
        circuit_id="mexico_city",
        event_name="Mexico City Grand Prix",
        country="Mexico",
        track_length_km=4.304,
        num_corners=17,
        num_laps=71,
        sm_zones=3,
    ),
    Circuit(
        circuit_id="sao_paulo",
        event_name="São Paulo Grand Prix",
        country="Brazil",
        track_length_km=4.309,
        num_corners=15,
        num_laps=71,
        sm_zones=2,
    ),
    Circuit(
        circuit_id="las_vegas",
        event_name="Las Vegas Grand Prix",
        country="United States",
        track_length_km=6.201,
        num_corners=17,
        num_laps=50,
        sm_zones=2,
    ),
    Circuit(
        circuit_id="lusail",
        event_name="Qatar Grand Prix",
        country="Qatar",
        track_length_km=5.419,
        num_corners=16,
        num_laps=57,
        sm_zones=2,
    ),
    Circuit(
        circuit_id="abu_dhabi",
        event_name="Abu Dhabi Grand Prix",
        country="United Arab Emirates",
        track_length_km=5.281,
        num_corners=16,
        num_laps=58,
        sm_zones=2,
    ),
]
