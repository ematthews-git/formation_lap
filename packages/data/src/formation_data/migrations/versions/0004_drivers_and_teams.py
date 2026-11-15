"""drivers and teams become tables that results, standings and lap records reference

Until now a driver or team was a string, spelled however its source spelled it:
race_results held a surname slug and Jolpica's constructor name ("RB F1 Team"),
standings held a full name or an entrant name, lap_records a surname, and `drivers` was
a per-season list with a free-text team. Nothing tied them together, so the frontend
lined teams up with substring matching, and a mid-season seat change couldn't be stored.

This adds `teams` (a lineage across rebrands), `team_seasons` (its name and source keys
each season), `drivers` (one row per person, keyed on Jolpica's driverId) and `seats`
(who's entered for which team, dated), and points race_results, both standings tables
and lap_records at them:

- race_results.driver_id is rewritten from the surname slug to Jolpica's driverId (eight
  change: verstappen -> max_verstappen, magnussen -> kevin_magnussen, schumacher ->
  mick_schumacher, de vries -> de_vries, and the four drivers Jolpica keys on given
  name too), and `team` becomes team_id.
- standings splits into driver_standings and constructor_standings, keyed on the race
  weekend the standings follow rather than (season, after_round).
- lap_records.driver (a surname) becomes driver_id.
- the old per-season `drivers` rows become seats.

The reference rows inserted here are a frozen copy of the teams and drivers seeds
(jobs.static.teams, jobs.static.drivers) as of this revision, plus every driver the
stored history names. Every existing row has to map onto them: if one doesn't, the
upgrade stops, lists what it couldn't place, and changes nothing.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-15 12:00:00
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from datetime import date

import sqlalchemy as sa
from alembic import op

from formation_data.migrate import MigrationError

revision: str = '0004'
down_revision: str | Sequence[str] | None = '0003'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# The teams seed (jobs.static.teams) as of this revision.
_TEAMS = [
    ('mercedes', 'Mercedes'),
    ('red_bull', 'Red Bull Racing'),
    ('ferrari', 'Ferrari'),
    ('mclaren', 'McLaren'),
    ('aston_martin', 'Aston Martin'),
    ('alpine', 'Alpine'),
    ('racing_bulls', 'Racing Bulls'),
    ('audi', 'Audi'),
    ('haas', 'Haas'),
    ('williams', 'Williams'),
    ('cadillac', 'Cadillac'),
]

# (team_id, season, name that season, Jolpica constructorId, FastF1 TeamName)
_TEAM_SEASONS = [
    ('mercedes', 2020, 'Mercedes', 'mercedes', None),
    ('red_bull', 2020, 'Red Bull Racing', 'red_bull', None),
    ('ferrari', 2020, 'Ferrari', 'ferrari', None),
    ('mclaren', 2020, 'McLaren', 'mclaren', None),
    ('aston_martin', 2020, 'Racing Point', 'racing_point', None),
    ('alpine', 2020, 'Renault', 'renault', None),
    ('racing_bulls', 2020, 'AlphaTauri', 'alphatauri', None),
    ('audi', 2020, 'Alfa Romeo', 'alfa', None),
    ('haas', 2020, 'Haas', 'haas', None),
    ('williams', 2020, 'Williams', 'williams', None),
    ('mercedes', 2021, 'Mercedes', 'mercedes', 'Mercedes'),
    ('red_bull', 2021, 'Red Bull Racing', 'red_bull', 'Red Bull Racing'),
    ('ferrari', 2021, 'Ferrari', 'ferrari', 'Ferrari'),
    ('mclaren', 2021, 'McLaren', 'mclaren', 'McLaren'),
    ('aston_martin', 2021, 'Aston Martin', 'aston_martin', 'Aston Martin'),
    ('alpine', 2021, 'Alpine', 'alpine', 'Alpine'),
    ('racing_bulls', 2021, 'AlphaTauri', 'alphatauri', 'AlphaTauri'),
    ('audi', 2021, 'Alfa Romeo', 'alfa', 'Alfa Romeo Racing'),
    ('haas', 2021, 'Haas', 'haas', 'Haas F1 Team'),
    ('williams', 2021, 'Williams', 'williams', 'Williams'),
    ('mercedes', 2022, 'Mercedes', 'mercedes', 'Mercedes'),
    ('red_bull', 2022, 'Red Bull Racing', 'red_bull', 'Red Bull Racing'),
    ('ferrari', 2022, 'Ferrari', 'ferrari', 'Ferrari'),
    ('mclaren', 2022, 'McLaren', 'mclaren', 'McLaren'),
    ('aston_martin', 2022, 'Aston Martin', 'aston_martin', 'Aston Martin'),
    ('alpine', 2022, 'Alpine', 'alpine', 'Alpine'),
    ('racing_bulls', 2022, 'AlphaTauri', 'alphatauri', 'AlphaTauri'),
    ('audi', 2022, 'Alfa Romeo', 'alfa', 'Alfa Romeo'),
    ('haas', 2022, 'Haas', 'haas', 'Haas F1 Team'),
    ('williams', 2022, 'Williams', 'williams', 'Williams'),
    ('mercedes', 2023, 'Mercedes', 'mercedes', 'Mercedes'),
    ('red_bull', 2023, 'Red Bull Racing', 'red_bull', 'Red Bull Racing'),
    ('ferrari', 2023, 'Ferrari', 'ferrari', 'Ferrari'),
    ('mclaren', 2023, 'McLaren', 'mclaren', 'McLaren'),
    ('aston_martin', 2023, 'Aston Martin', 'aston_martin', 'Aston Martin'),
    ('alpine', 2023, 'Alpine', 'alpine', 'Alpine'),
    ('racing_bulls', 2023, 'AlphaTauri', 'alphatauri', 'AlphaTauri'),
    ('audi', 2023, 'Alfa Romeo', 'alfa', 'Alfa Romeo'),
    ('haas', 2023, 'Haas', 'haas', 'Haas F1 Team'),
    ('williams', 2023, 'Williams', 'williams', 'Williams'),
    ('mercedes', 2024, 'Mercedes', 'mercedes', 'Mercedes'),
    ('red_bull', 2024, 'Red Bull Racing', 'red_bull', 'Red Bull Racing'),
    ('ferrari', 2024, 'Ferrari', 'ferrari', 'Ferrari'),
    ('mclaren', 2024, 'McLaren', 'mclaren', 'McLaren'),
    ('aston_martin', 2024, 'Aston Martin', 'aston_martin', 'Aston Martin'),
    ('alpine', 2024, 'Alpine', 'alpine', 'Alpine'),
    ('audi', 2024, 'Kick Sauber', 'sauber', 'Kick Sauber'),
    ('haas', 2024, 'Haas', 'haas', 'Haas F1 Team'),
    ('williams', 2024, 'Williams', 'williams', 'Williams'),
    ('racing_bulls', 2024, 'RB', 'rb', 'RB'),
    ('mercedes', 2025, 'Mercedes', 'mercedes', 'Mercedes'),
    ('red_bull', 2025, 'Red Bull Racing', 'red_bull', 'Red Bull Racing'),
    ('ferrari', 2025, 'Ferrari', 'ferrari', 'Ferrari'),
    ('mclaren', 2025, 'McLaren', 'mclaren', 'McLaren'),
    ('aston_martin', 2025, 'Aston Martin', 'aston_martin', 'Aston Martin'),
    ('alpine', 2025, 'Alpine', 'alpine', 'Alpine'),
    ('audi', 2025, 'Kick Sauber', 'sauber', 'Kick Sauber'),
    ('haas', 2025, 'Haas', 'haas', 'Haas F1 Team'),
    ('williams', 2025, 'Williams', 'williams', 'Williams'),
    ('racing_bulls', 2025, 'Racing Bulls', 'rb', 'Racing Bulls'),
    ('mercedes', 2026, 'Mercedes', 'mercedes', 'Mercedes'),
    ('red_bull', 2026, 'Red Bull Racing', 'red_bull', 'Red Bull Racing'),
    ('ferrari', 2026, 'Ferrari', 'ferrari', 'Ferrari'),
    ('mclaren', 2026, 'McLaren', 'mclaren', 'McLaren'),
    ('aston_martin', 2026, 'Aston Martin', 'aston_martin', 'Aston Martin'),
    ('alpine', 2026, 'Alpine', 'alpine', 'Alpine'),
    ('racing_bulls', 2026, 'Racing Bulls', 'rb', 'Racing Bulls'),
    ('audi', 2026, 'Audi', 'audi', 'Audi'),
    ('haas', 2026, 'Haas', 'haas', 'Haas F1 Team'),
    ('williams', 2026, 'Williams', 'williams', 'Williams'),
    ('cadillac', 2026, 'Cadillac', 'cadillac', 'Cadillac'),
]

# Jolpica's constructor `name` for each constructorId, as race_results.team and
# standings.name stored it.
_JOLPICA_NAMES = {
    "mercedes": "Mercedes",
    "red_bull": "Red Bull",
    "ferrari": "Ferrari",
    "mclaren": "McLaren",
    "racing_point": "Racing Point",
    "aston_martin": "Aston Martin",
    "renault": "Renault",
    "alpine": "Alpine F1 Team",
    "alphatauri": "AlphaTauri",
    "rb": "RB F1 Team",
    "alfa": "Alfa Romeo",
    "sauber": "Sauber",
    "audi": "Audi",
    "haas": "Haas F1 Team",
    "williams": "Williams",
    "cadillac": "Cadillac F1 Team",
}

# (Jolpica driverId, the surname slug the old tables used, given name, family name,
# code, nationality). Everyone the stored results, standings and lap records name.
_DRIVERS = [
    ("albon", "albon", "Alexander", "Albon", "ALB", "Thai"),
    ("alonso", "alonso", "Fernando", "Alonso", "ALO", "Spanish"),
    ("antonelli", "antonelli", "Andrea Kimi", "Antonelli", "ANT", "Italian"),
    ("arvid_lindblad", "lindblad", "Arvid", "Lindblad", "LIN", "British"),
    ("bearman", "bearman", "Oliver", "Bearman", "BEA", "British"),
    ("bortoleto", "bortoleto", "Gabriel", "Bortoleto", "BOR", "Brazilian"),
    ("bottas", "bottas", "Valtteri", "Bottas", "BOT", "Finnish"),
    ("colapinto", "colapinto", "Franco", "Colapinto", "COL", "Argentine"),
    ("de_vries", "de vries", "Nyck", "de Vries", "DEV", "Dutch"),
    ("doohan", "doohan", "Jack", "Doohan", "DOO", "Australian"),
    ("gasly", "gasly", "Pierre", "Gasly", "GAS", "French"),
    ("giovinazzi", "giovinazzi", "Antonio", "Giovinazzi", "GIO", "Italian"),
    ("grosjean", "grosjean", "Romain", "Grosjean", "GRO", "French"),
    ("hadjar", "hadjar", "Isack", "Hadjar", "HAD", "French"),
    ("hamilton", "hamilton", "Lewis", "Hamilton", "HAM", "British"),
    ("hulkenberg", "hulkenberg", "Nico", "Hülkenberg", "HUL", "German"),
    ("kevin_magnussen", "magnussen", "Kevin", "Magnussen", "MAG", "Danish"),
    ("kubica", "kubica", "Robert", "Kubica", "KUB", "Polish"),
    ("kvyat", "kvyat", "Daniil", "Kvyat", "KVY", "Russian"),
    ("latifi", "latifi", "Nicholas", "Latifi", "LAT", "Canadian"),
    ("lawson", "lawson", "Liam", "Lawson", "LAW", "New Zealander"),
    ("leclerc", "leclerc", "Charles", "Leclerc", "LEC", "Monegasque"),
    ("max_verstappen", "verstappen", "Max", "Verstappen", "VER", "Dutch"),
    ("mazepin", "mazepin", "Nikita", "Mazepin", "MAZ", "Russian"),
    ("michael_schumacher", None, "Michael", "Schumacher", "MSC", "German"),
    ("mick_schumacher", "schumacher", "Mick", "Schumacher", "MSC", "German"),
    ("norris", "norris", "Lando", "Norris", "NOR", "British"),
    ("ocon", "ocon", "Esteban", "Ocon", "OCO", "French"),
    ("perez", "perez", "Sergio", "Pérez", "PER", "Mexican"),
    ("piastri", "piastri", "Oscar", "Piastri", "PIA", "Australian"),
    ("pietro_fittipaldi", "fittipaldi", "Pietro", "Fittipaldi", "FIT", "Brazilian"),
    ("rafael_camara", "camara", "Rafael", "Camara", "CAM", "Brazilian"),
    ("raikkonen", "raikkonen", "Kimi", "Räikkönen", "RAI", "Finnish"),
    ("ricciardo", "ricciardo", "Daniel", "Ricciardo", "RIC", "Australian"),
    ("russell", "russell", "George", "Russell", "RUS", "British"),
    ("ryo_hirakawa", "hirakawa", "Ryo", "Hirakawa", "HIR", "Japanese"),
    ("sainz", "sainz", "Carlos", "Sainz", "SAI", "Spanish"),
    ("sargeant", "sargeant", "Logan", "Sargeant", "SAR", "American"),
    ("stroll", "stroll", "Lance", "Stroll", "STR", "Canadian"),
    ("tsunoda", "tsunoda", "Yuki", "Tsunoda", "TSU", "Japanese"),
    ("vettel", "vettel", "Sebastian", "Vettel", "VET", "German"),
    ("zhou", "zhou", "Guanyu", "Zhou", "ZHO", "Chinese"),
]


def _fold(name: str) -> str:
    """Accent-stripped and case-folded, so "Pérez" and FastF1's "Perez" agree."""
    return "".join(
        c for c in unicodedata.normalize("NFKD", name) if not unicodedata.combining(c)
    ).casefold()


def _team_by_season_name() -> dict[tuple[int, str], str]:
    """(season, a name the old tables used) -> team_id: Jolpica's constructor name, and
    the season's name from team_seasons (which the drivers seed and a downgrade use)."""
    names: dict[tuple[int, str], str] = {}
    for team_id, season, name, jolpica_id, _ in _TEAM_SEASONS:
        for key in ((season, name), (season, _JOLPICA_NAMES[jolpica_id])):
            assert names.setdefault(key, team_id) == team_id, f"{key} names two teams"
    return names


def _lap_record_holder(surname: str, year: int) -> str | None:
    if _fold(surname) == "schumacher":
        return "michael_schumacher" if year <= 2012 else "mick_schumacher"
    matches = [d[0] for d in _DRIVERS if _fold(d[3]) == _fold(surname)]
    return matches[0] if len(matches) == 1 else None


def upgrade() -> None:
    bind = op.get_bind()
    team_by_name = _team_by_season_name()
    by_legacy = {legacy: driver_id for driver_id, legacy, *_ in _DRIVERS if legacy}
    by_full_name = {f"{given} {family}": driver_id for driver_id, _, given, family, *_ in _DRIVERS}

    # --- every existing row has to map before anything changes -----------------------
    problems: list[str] = []
    for season, legacy, team in bind.exec_driver_sql("""
        SELECT DISTINCT rw.season, rr.driver_id, rr.team
        FROM race_results rr JOIN race_weekends rw ON rw.id = rr.race_weekend_id
        ORDER BY 1, 2
    """):
        if legacy not in by_legacy:
            problems.append(f"race_results {season}: driver {legacy!r}")
        if (season, team) not in team_by_name:
            problems.append(f"race_results {season}: team {team!r}")
    for season, after_round, type_, name, weekend_id in bind.exec_driver_sql("""
        SELECT DISTINCT s.season, s.after_round, s.type, s.name, rw.id
        FROM standings s
        LEFT JOIN race_weekends rw ON rw.season = s.season AND rw.round_number = s.after_round
        ORDER BY 1, 2
    """):
        if weekend_id is None:
            problems.append(f"standings {season} R{after_round}: no race weekend")
        if type_ == "driver" and name not in by_full_name:
            problems.append(f"standings {season}: driver {name!r}")
        if type_ == "constructor" and (season, name) not in team_by_name:
            problems.append(f"standings {season}: team {name!r}")
    holders = {}
    for circuit_id, surname, year in bind.exec_driver_sql(
        "SELECT circuit_id, driver, year FROM lap_records ORDER BY 1"
    ):
        holders[circuit_id] = _lap_record_holder(surname, year)
        if holders[circuit_id] is None:
            problems.append(f"lap_records {circuit_id}: driver {surname!r} ({year})")
    grid = bind.exec_driver_sql("SELECT driver_id, team, season FROM drivers ORDER BY 3, 1").all()
    for legacy, team, season in grid:
        if legacy not in by_legacy:
            problems.append(f"drivers {season}: driver {legacy!r}")
        if (season, team) not in team_by_name:
            problems.append(f"drivers {season}: team {team!r}")
    if problems:
        listed = "\n".join(f"  {p}" for p in sorted(set(problems)))
        raise MigrationError(
            "Some rows name a driver or team that 0004 doesn't know, so it wasn't applied "
            f"and nothing changed:\n{listed}\n"
            "Every one of these can be loaded again from its source once the upgrade is "
            "done: delete those rows, run `formation-data db upgrade`, then reload them "
            "(`results backfill`, `standings refresh`, `lap-records refresh`, "
            "`drivers seed`)."
        )

    # --- teams --------------------------------------------------------------------------
    teams = op.create_table(
        "teams",
        sa.Column("team_id", sa.String(length=30), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("team_id", name="teams_pkey"),
    )
    op.bulk_insert(teams, [{"team_id": t, "name": n} for t, n in _TEAMS])
    team_seasons = op.create_table(
        "team_seasons",
        sa.Column("team_id", sa.String(length=30), nullable=False),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("jolpica_id", sa.String(length=50), nullable=False),
        sa.Column("fastf1_name", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["team_id"], ["teams.team_id"], name="team_seasons_team_id_fkey"),
        sa.PrimaryKeyConstraint("team_id", "season", name="team_seasons_pkey"),
        sa.UniqueConstraint("season", "jolpica_id", name="team_seasons_season_jolpica_id_key"),
        sa.UniqueConstraint("season", "fastf1_name", name="team_seasons_season_fastf1_name_key"),
    )
    op.bulk_insert(
        team_seasons,
        [
            {"team_id": t, "season": s, "name": n, "jolpica_id": j, "fastf1_name": f}
            for t, s, n, j, f in _TEAM_SEASONS
        ],
    )

    # --- drivers: the per-season list becomes people + seats ----------------------------
    op.drop_table("drivers")
    drivers = op.create_table(
        "drivers",
        sa.Column("driver_id", sa.String(length=50), nullable=False),
        sa.Column("given_name", sa.String(), nullable=False),
        sa.Column("family_name", sa.String(), nullable=False),
        sa.Column("code", sa.String(length=3), nullable=True),
        sa.Column("nationality", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("driver_id", name="drivers_pkey"),
    )
    op.bulk_insert(
        drivers,
        [
            {"driver_id": d, "given_name": g, "family_name": f, "code": c, "nationality": n}
            for d, _, g, f, c, n in _DRIVERS
        ],
    )
    seats = op.create_table(
        "seats",
        sa.Column("driver_id", sa.String(length=50), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("team_id", sa.String(length=30), nullable=False),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.CheckConstraint("valid_to > valid_from", name=op.f("seats_valid_range_check")),
        sa.ForeignKeyConstraint(["driver_id"], ["drivers.driver_id"], name="seats_driver_id_fkey"),
        sa.ForeignKeyConstraint(
            ["team_id", "season"],
            ["team_seasons.team_id", "team_seasons.season"],
            name="seats_team_id_season_fkey",
        ),
        sa.PrimaryKeyConstraint("driver_id", "valid_from", name="seats_pkey"),
    )
    op.bulk_insert(
        seats,
        [
            {
                "driver_id": by_legacy[legacy],
                "valid_from": date(season, 1, 1),
                "valid_to": None,
                "team_id": team_by_name[(season, team)],
                "season": season,
            }
            for legacy, team, season in grid
        ],
    )

    # --- race_results --------------------------------------------------------------------
    op.add_column("race_results", sa.Column("team_id", sa.String(length=30), nullable=True))
    bind.execute(
        sa.text("""
            UPDATE race_results rr SET team_id = :team_id
            FROM race_weekends rw
            WHERE rw.id = rr.race_weekend_id AND rw.season = :season AND rr.team = :name
        """),
        [{"season": s, "name": n, "team_id": t} for (s, n), t in team_by_name.items()],
    )
    bind.execute(
        sa.text("UPDATE race_results SET driver_id = :new WHERE driver_id = :old"),
        [{"old": old, "new": new} for old, new in by_legacy.items() if old != new],
    )
    op.drop_column("race_results", "team")
    op.alter_column("race_results", "team_id", existing_type=sa.String(length=30), nullable=False)
    op.alter_column(
        "race_results", "driver_id", type_=sa.String(length=50), existing_nullable=False
    )
    op.create_foreign_key(
        "race_results_driver_id_fkey", "race_results", "drivers", ["driver_id"], ["driver_id"]
    )
    op.create_foreign_key(
        "race_results_team_id_fkey", "race_results", "teams", ["team_id"], ["team_id"]
    )
    op.create_unique_constraint(
        "race_results_race_weekend_id_driver_id_key",
        "race_results",
        ["race_weekend_id", "driver_id"],
    )

    # --- standings -> driver_standings + constructor_standings ----------------------------
    op.create_table(
        "driver_standings",
        sa.Column("race_weekend_id", sa.Integer(), nullable=False),
        sa.Column("driver_id", sa.String(length=50), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("points", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["driver_id"], ["drivers.driver_id"], name="driver_standings_driver_id_fkey"
        ),
        sa.ForeignKeyConstraint(
            ["race_weekend_id"],
            ["race_weekends.id"],
            name="driver_standings_race_weekend_id_fkey",
        ),
        sa.PrimaryKeyConstraint("race_weekend_id", "driver_id", name="driver_standings_pkey"),
    )
    op.create_table(
        "constructor_standings",
        sa.Column("race_weekend_id", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.String(length=30), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("points", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["race_weekend_id"],
            ["race_weekends.id"],
            name="constructor_standings_race_weekend_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["team_id"], ["teams.team_id"], name="constructor_standings_team_id_fkey"
        ),
        sa.PrimaryKeyConstraint("race_weekend_id", "team_id", name="constructor_standings_pkey"),
    )
    from_standings = """
        FROM standings s
        JOIN race_weekends rw ON rw.season = s.season AND rw.round_number = s.after_round
    """
    bind.execute(
        sa.text(f"""
            INSERT INTO driver_standings (race_weekend_id, driver_id, position, points)
            SELECT rw.id, :driver_id, s.position, s.points {from_standings}
            WHERE s.type = 'driver' AND s.name = :name
        """),
        [{"name": n, "driver_id": d} for n, d in by_full_name.items()],
    )
    bind.execute(
        sa.text(f"""
            INSERT INTO constructor_standings (race_weekend_id, team_id, position, points)
            SELECT rw.id, :team_id, s.position, s.points {from_standings}
            WHERE s.type = 'constructor' AND s.season = :season AND s.name = :name
        """),
        [{"season": s, "name": n, "team_id": t} for (s, n), t in team_by_name.items()],
    )
    moved = bind.exec_driver_sql(
        "SELECT (SELECT count(*) FROM driver_standings) + "
        "(SELECT count(*) FROM constructor_standings), (SELECT count(*) FROM standings)"
    ).one()
    if moved[0] != moved[1]:
        raise MigrationError(
            f"Moved {moved[0]} of {moved[1]} standings rows, so 0004 wasn't applied."
        )
    op.drop_table("standings")

    # --- lap_records ---------------------------------------------------------------------
    op.add_column("lap_records", sa.Column("driver_id", sa.String(length=50), nullable=True))
    if holders:
        bind.execute(
            sa.text("UPDATE lap_records SET driver_id = :driver_id WHERE circuit_id = :circuit_id"),
            [{"circuit_id": c, "driver_id": d} for c, d in holders.items()],
        )
    op.alter_column("lap_records", "driver_id", existing_type=sa.String(length=50), nullable=False)
    op.drop_column("lap_records", "driver")
    op.create_foreign_key(
        "lap_records_driver_id_fkey", "lap_records", "drivers", ["driver_id"], ["driver_id"]
    )


def _surname_slug(family_name: str) -> str:
    """The old tables' driver key: the accent-stripped, lowercased surname."""
    return "".join(
        c for c in unicodedata.normalize("NFKD", family_name) if not unicodedata.combining(c)
    ).lower()


def downgrade() -> None:
    bind = op.get_bind()
    legacy = {d: old for d, old, *_ in _DRIVERS if old}
    for driver_id, family_name in bind.exec_driver_sql("SELECT driver_id, family_name FROM drivers"):
        legacy.setdefault(driver_id, _surname_slug(family_name))

    # --- lap_records ---------------------------------------------------------------------
    op.add_column("lap_records", sa.Column("driver", sa.String(), nullable=True))
    bind.exec_driver_sql(
        "UPDATE lap_records lr SET driver = d.family_name FROM drivers d "
        "WHERE d.driver_id = lr.driver_id"
    )
    op.alter_column("lap_records", "driver", existing_type=sa.String(), nullable=False)
    op.drop_constraint("lap_records_driver_id_fkey", "lap_records", type_="foreignkey")
    op.drop_column("lap_records", "driver_id")

    # --- standings -------------------------------------------------------------------------
    op.create_table(
        "standings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("after_round", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=15), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("points", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="standings_pkey"),
        sa.UniqueConstraint(
            "season",
            "after_round",
            "type",
            "position",
            name="standings_season_after_round_type_position_key",
        ),
    )
    bind.exec_driver_sql("""
        INSERT INTO standings (season, after_round, type, position, name, points)
        SELECT rw.season, rw.round_number, 'driver', ds.position,
               d.given_name || ' ' || d.family_name, ds.points
        FROM driver_standings ds
        JOIN race_weekends rw ON rw.id = ds.race_weekend_id
        JOIN drivers d ON d.driver_id = ds.driver_id
    """)
    bind.exec_driver_sql("""
        INSERT INTO standings (season, after_round, type, position, name, points)
        SELECT rw.season, rw.round_number, 'constructor', cs.position, ts.name, cs.points
        FROM constructor_standings cs
        JOIN race_weekends rw ON rw.id = cs.race_weekend_id
        JOIN team_seasons ts ON ts.team_id = cs.team_id AND ts.season = rw.season
    """)
    op.drop_table("driver_standings")
    op.drop_table("constructor_standings")

    # --- race_results ----------------------------------------------------------------------
    op.add_column("race_results", sa.Column("team", sa.String(), nullable=True))
    bind.exec_driver_sql("""
        UPDATE race_results rr SET team = ts.name
        FROM race_weekends rw, team_seasons ts
        WHERE rw.id = rr.race_weekend_id AND ts.team_id = rr.team_id AND ts.season = rw.season
    """)
    op.alter_column("race_results", "team", existing_type=sa.String(), nullable=False)
    op.drop_constraint("race_results_race_weekend_id_driver_id_key", "race_results", type_="unique")
    op.drop_constraint("race_results_driver_id_fkey", "race_results", type_="foreignkey")
    op.drop_constraint("race_results_team_id_fkey", "race_results", type_="foreignkey")
    op.drop_column("race_results", "team_id")
    op.alter_column("race_results", "driver_id", type_=sa.String(), existing_nullable=False)
    bind.execute(
        sa.text("UPDATE race_results SET driver_id = :old WHERE driver_id = :new"),
        [{"old": old, "new": new} for new, old in legacy.items() if old != new],
    )

    # --- seats -> the per-season drivers list ---------------------------------------------
    grid = bind.exec_driver_sql("""
        SELECT DISTINCT ON (s.season, s.driver_id)
               s.driver_id, d.given_name || ' ' || d.family_name, d.nationality, ts.name, s.season
        FROM seats s
        JOIN drivers d ON d.driver_id = s.driver_id
        JOIN team_seasons ts ON ts.team_id = s.team_id AND ts.season = s.season
        ORDER BY s.season, s.driver_id, s.valid_from DESC
    """).all()
    op.drop_table("seats")
    op.drop_table("drivers")
    old_drivers = op.create_table(
        "drivers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("driver_id", sa.String(length=10), nullable=False),
        sa.Column("full_name", sa.String(), nullable=False),
        sa.Column("nationality", sa.String(), nullable=False),
        sa.Column("team", sa.String(), nullable=False),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="drivers_pkey"),
        sa.UniqueConstraint("driver_id", "season", name="drivers_driver_id_season_key"),
    )
    op.bulk_insert(
        old_drivers,
        [
            {
                "driver_id": legacy[driver_id][:10],
                "full_name": full_name,
                "nationality": nationality or "",
                "team": team,
                "season": season,
            }
            for driver_id, full_name, nationality, team, season in grid
        ],
    )
    op.drop_table("team_seasons")
    op.drop_table("teams")
