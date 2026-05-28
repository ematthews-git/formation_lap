from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class Circuit:
    """Static circuit info."""

    circuit_id: str
    event_name: str
    country: str
    track_length_km: float
    num_corners: int
    num_laps: int
    sm_zones: int


@dataclass(frozen=True)
class CircuitModel:
    """Derived fields based on historical data.

    Attributes:
        pit_loss: tuple[normal, vsc, sc]
    """

    circuit_id: str
    sc_prob: int  # percentage
    red_flag_prob: int
    pit_loss: Tuple[float, float, float]
    lap_record: tuple[str, int, float]
    undercut_strength: float
    overcut_strength: float

    # strategy


@dataclass
class raceWeekend:
    isSprint: bool
    circuit: Circuit
    circuit_model: CircuitModel
    # conditions: Condtions
