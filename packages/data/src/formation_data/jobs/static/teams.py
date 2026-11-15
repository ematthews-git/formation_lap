"""Static job: seed teams and what each was called, season by season.

Cadence: once a season, when the entry list is known, and whenever a team rebrands.
Ingest resolves a source's team through this table (Jolpica's constructorId, FastF1's
team name) and stops with an error naming the team when it finds one that isn't here,
so a new season needs its rows added before its first results load.

A team is a lineage, keyed after its current entry: Toro Rosso, AlphaTauri, RB and Racing
Bulls are all `racing_bulls`; Sauber, Alfa Romeo, Kick Sauber and Audi are all `audi`.
The team_id also names the frontend's colour token (`--team-<team_id>`).

jolpica_id comes from Jolpica's /{season}/constructors. fastf1_name is FastF1's TeamName
as it appears in that season's sessions; it's None for 2020, which no stored race trace
covers.

Upsert keys: teams (team_id), team_seasons (team_id, season).
"""

from __future__ import annotations

import logging

from sqlalchemy import Connection

from formation_data.domain import Team, TeamSeason

logger = logging.getLogger(__name__)


TEAMS = [
    Team(team_id="mercedes", name="Mercedes"),
    Team(team_id="red_bull", name="Red Bull Racing"),
    Team(team_id="ferrari", name="Ferrari"),
    Team(team_id="mclaren", name="McLaren"),
    Team(team_id="aston_martin", name="Aston Martin"),  # Racing Point until 2020
    Team(team_id="alpine", name="Alpine"),  # Renault until 2020
    Team(team_id="racing_bulls", name="Racing Bulls"),  # AlphaTauri, then RB
    Team(team_id="audi", name="Audi"),  # Alfa Romeo, then Kick Sauber
    Team(team_id="haas", name="Haas"),
    Team(team_id="williams", name="Williams"),
    Team(team_id="cadillac", name="Cadillac"),  # new entry, 2026
]


def _season(season: int, rows: list[tuple[str, str, str, str | None]]) -> list[TeamSeason]:
    return [
        TeamSeason(
            team_id=team_id, season=season, name=name, jolpica_id=jolpica_id, fastf1_name=ff1
        )
        for team_id, name, jolpica_id, ff1 in rows
    ]


# (team_id, name that season, Jolpica constructorId, FastF1 TeamName)
_2021_TO_2023 = [
    ("mercedes", "Mercedes", "mercedes", "Mercedes"),
    ("red_bull", "Red Bull Racing", "red_bull", "Red Bull Racing"),
    ("ferrari", "Ferrari", "ferrari", "Ferrari"),
    ("mclaren", "McLaren", "mclaren", "McLaren"),
    ("aston_martin", "Aston Martin", "aston_martin", "Aston Martin"),
    ("alpine", "Alpine", "alpine", "Alpine"),
    ("racing_bulls", "AlphaTauri", "alphatauri", "AlphaTauri"),
    ("audi", "Alfa Romeo", "alfa", "Alfa Romeo"),
    ("haas", "Haas", "haas", "Haas F1 Team"),
    ("williams", "Williams", "williams", "Williams"),
]

_2024_TO_2025 = [
    ("mercedes", "Mercedes", "mercedes", "Mercedes"),
    ("red_bull", "Red Bull Racing", "red_bull", "Red Bull Racing"),
    ("ferrari", "Ferrari", "ferrari", "Ferrari"),
    ("mclaren", "McLaren", "mclaren", "McLaren"),
    ("aston_martin", "Aston Martin", "aston_martin", "Aston Martin"),
    ("alpine", "Alpine", "alpine", "Alpine"),
    ("audi", "Kick Sauber", "sauber", "Kick Sauber"),
    ("haas", "Haas", "haas", "Haas F1 Team"),
    ("williams", "Williams", "williams", "Williams"),
]

TEAM_SEASONS = [
    *_season(
        2020,
        [
            ("mercedes", "Mercedes", "mercedes", None),
            ("red_bull", "Red Bull Racing", "red_bull", None),
            ("ferrari", "Ferrari", "ferrari", None),
            ("mclaren", "McLaren", "mclaren", None),
            ("aston_martin", "Racing Point", "racing_point", None),
            ("alpine", "Renault", "renault", None),
            ("racing_bulls", "AlphaTauri", "alphatauri", None),
            ("audi", "Alfa Romeo", "alfa", None),
            ("haas", "Haas", "haas", None),
            ("williams", "Williams", "williams", None),
        ],
    ),
    # FastF1 called the Sauber entry "Alfa Romeo Racing" in 2021 only.
    *_season(
        2021,
        [r if r[0] != "audi" else ("audi", "Alfa Romeo", "alfa", "Alfa Romeo Racing")
         for r in _2021_TO_2023],
    ),
    *_season(2022, _2021_TO_2023),
    *_season(2023, _2021_TO_2023),
    *_season(2024, [*_2024_TO_2025, ("racing_bulls", "RB", "rb", "RB")]),
    *_season(2025, [*_2024_TO_2025, ("racing_bulls", "Racing Bulls", "rb", "Racing Bulls")]),
    *_season(
        2026,
        [
            ("mercedes", "Mercedes", "mercedes", "Mercedes"),
            ("red_bull", "Red Bull Racing", "red_bull", "Red Bull Racing"),
            ("ferrari", "Ferrari", "ferrari", "Ferrari"),
            ("mclaren", "McLaren", "mclaren", "McLaren"),
            ("aston_martin", "Aston Martin", "aston_martin", "Aston Martin"),
            ("alpine", "Alpine", "alpine", "Alpine"),
            ("racing_bulls", "Racing Bulls", "rb", "Racing Bulls"),
            ("audi", "Audi", "audi", "Audi"),
            ("haas", "Haas", "haas", "Haas F1 Team"),
            ("williams", "Williams", "williams", "Williams"),
            ("cadillac", "Cadillac", "cadillac", "Cadillac"),
        ],
    ),
]


def run(conn: Connection) -> None:
    from formation_data import repositories, schema

    repositories.upsert(conn, schema.teams, TEAMS, ["team_id"])
    repositories.upsert(conn, schema.team_seasons, TEAM_SEASONS, ["team_id", "season"])
    logger.info(
        "static.teams.run teams=%d team_seasons=%d seasons=%s",
        len(TEAMS),
        len(TEAM_SEASONS),
        sorted({t.season for t in TEAM_SEASONS}),
    )
