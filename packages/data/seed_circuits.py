"""For populating circuit info."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CircuitRow:
    circuit_id: str
    event_name: str
    country: str
    track_length_km: float
    num_corners: int
    num_laps: int
    sm_zones: int
