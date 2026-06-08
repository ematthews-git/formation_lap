"""Seed data for circuits table."""

from formation_data.models import Circuit

CIRCUITS = [
    Circuit(
        circuit_id="bahrain",
        event_name="Bahrain Grand Prix",
        country="Bahrain",
        track_length_km=5.412,
        num_corners=15,
        num_laps=57,
        sm_zones=3,
    ),
    Circuit(
        circuit_id="jeddah",
        event_name="Saudi Arabian Grand Prix",
        country="Saudi Arabia",
        track_length_km=6.174,
        num_corners=27,
        num_laps=50,
        sm_zones=3,
    ),
    Circuit(
        circuit_id="melbourne",
        event_name="Australian Grand Prix",
        country="Australia",
        track_length_km=5.278,
        num_corners=14,
        num_laps=58,
        sm_zones=4,
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
]
