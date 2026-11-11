"""FastF1 failure handling: sign-in vs unpublished data, post-race resilience, CLI messages."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest
from fastf1.exceptions import DataNotLoadedError, F1AuthError
from formation_sim.data import collector, f1tv
from sqlalchemy import exc as sa_exc

from formation_data import cli, orchestrator
from formation_data.jobs.post_race import lap_records
from formation_data.sources import fastf1_client

_NO_CREDS = "No F1 account credentials available. Set F1_USERNAME and F1_PASSWORD."

# Captured at import, before conftest's autouse fixture stubs it for each test.
_real_auth_problem = f1tv.auth_problem


class _EmptySession:
    """What FastF1 hands back when every request failed: load() returns normally, and
    reading `.laps` raises DataNotLoadedError."""

    event = {"EventName": "United States Grand Prix"}

    def load(self, **_kwargs):
        return None

    @property
    def laps(self):
        raise DataNotLoadedError("The data you are trying to access has not been loaded yet.")


def _signed_out(monkeypatch):
    monkeypatch.setattr(f1tv, "auth_problem", lambda: _NO_CREDS)


@pytest.fixture
def empty_session(monkeypatch):
    monkeypatch.setattr(fastf1_client.fastf1, "get_session", lambda *a, **k: _EmptySession())


# --- collector.has_laps ---


def test_has_laps_handles_unloaded_and_empty_sessions():
    assert collector.has_laps(_EmptySession()) is False
    assert collector.has_laps(SimpleNamespace(laps=pd.DataFrame())) is False
    assert collector.has_laps(SimpleNamespace(laps=pd.DataFrame({"x": [1]}))) is True


# --- fastf1_client.load_session ---


def test_load_session_signed_out_raises_auth_error_with_fix(monkeypatch, empty_session):
    _signed_out(monkeypatch)
    with pytest.raises(fastf1_client.F1TVAuthError) as err:
        fastf1_client.load_session(2026, 18, "R")
    msg = str(err.value)
    assert _NO_CREDS in msg
    assert "formation-data f1tv login" in msg


def test_load_session_signed_in_but_no_data_is_unavailable(empty_session):
    with pytest.raises(fastf1_client.SessionDataUnavailable) as err:
        fastf1_client.load_session(2026, 18, "R")
    assert "2026 R18 R (United States Grand Prix)" in str(err.value)


def test_get_session_results_reraises_auth_but_not_unavailable(monkeypatch, empty_session):
    schedule = pd.DataFrame(
        [{"EventFormat": "conventional", "Location": "Austin", "RoundNumber": 18,
          "EventDate": pd.Timestamp("2026-10-25")}]
    )
    monkeypatch.setattr(fastf1_client, "get_event_schedule", lambda season: schedule)

    # Signed in, nothing published yet -> [] so the poll retries later.
    assert fastf1_client.get_session_results(2026, "Austin", date(2026, 10, 25), "Race") == []

    # Signed out -> loud, since retrying won't help.
    _signed_out(monkeypatch)
    with pytest.raises(fastf1_client.F1TVAuthError):
        fastf1_client.get_session_results(2026, "Austin", date(2026, 10, 25), "Race")


# --- post_race.lap_records ---


def test_lap_records_skips_unpublished_race(empty_session):
    # Used to crash with DataNotLoadedError at `session.laps.pick_fastest()`.
    assert lap_records.run(None, circuit_id="austin", season=2026, round_number=18) is None


def test_lap_records_propagates_auth_error(monkeypatch, empty_session):
    _signed_out(monkeypatch)
    with pytest.raises(fastf1_client.F1TVAuthError):
        lap_records.run(None, circuit_id="austin", season=2026, round_number=18)


# --- f1tv.auth_problem ---


def test_auth_problem_remembers_a_failure(monkeypatch):
    calls = []

    def failing_get_token(*_a, **_k):
        calls.append(1)
        raise F1AuthError(_NO_CREDS)

    monkeypatch.setattr(f1tv.f1account, "get_token", failing_get_token)
    assert _real_auth_problem() == _NO_CREDS
    assert _real_auth_problem() == _NO_CREDS
    assert len(calls) == 1  # no second sign-in attempt / prompt in the same run


# --- orchestrator.run_post_race_for_last_weekend ---


def _weekend(rnd, circuit):
    return SimpleNamespace(season=2026, round_number=rnd, circuit_id=circuit)


def test_post_race_commits_results_before_fastf1_and_surfaces_auth(monkeypatch):
    committed: list[str] = []

    @contextmanager
    def fake_scope():
        yield SimpleNamespace()

    monkeypatch.setattr(orchestrator, "connection_scope", fake_scope)
    monkeypatch.setattr(
        orchestrator.repositories,
        "race_weekends_missing_results",
        lambda conn, before: [_weekend(18, "austin"), _weekend(19, "mexico")],
    )
    monkeypatch.setattr(
        orchestrator.repositories,
        "most_recent_race_weekend_before",
        lambda conn, today: _weekend(19, "mexico"),
    )
    monkeypatch.setattr(
        orchestrator.repositories,
        "get_circuit",
        lambda conn, cid: SimpleNamespace(circuit_id=cid, jolpica_id=cid),
    )
    rounds = {"austin": "18", "mexico": "19"}
    monkeypatch.setattr(
        orchestrator.jolpica_client,
        "get_circuit_race",
        lambda season, jid: {"round": rounds[jid], "Results": [{}]},
    )
    monkeypatch.setattr(
        orchestrator.race_results, "run",
        lambda conn, season, round_number: committed.append(f"results R{round_number}"),
    )
    monkeypatch.setattr(
        orchestrator.standings, "run",
        lambda conn, season, round_number: committed.append(f"standings R{round_number}"),
    )
    monkeypatch.setattr(
        orchestrator.repositories,
        "races_missing_fastf1_data",
        lambda conn, season: [(2026, 18, "austin"), (2026, 19, "mexico")],
    )
    attempted: list[int] = []

    def refresh(season, rnd, circuit_id):
        attempted.append(rnd)
        raise fastf1_client.F1TVAuthError(_NO_CREDS)

    monkeypatch.setattr(orchestrator, "_refresh_fastf1_race", refresh)

    with pytest.raises(fastf1_client.F1TVAuthError):
        orchestrator.run_post_race_for_last_weekend(today=date(2026, 11, 10))

    # Jolpica data for both weekends is in before FastF1 is touched...
    assert committed == ["results R18", "standings R18", "results R19", "standings R19"]
    # ...and the run stops at the first sign-in failure instead of retrying every race.
    assert attempted == [18]


# --- CLI error reporting ---


def test_explain_database_unreachable_without_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    orig = Exception(
        'connection to server at "localhost" (127.0.0.1), port 5432 failed: Connection refused'
    )
    title, detail = cli._explain(sa_exc.OperationalError("SELECT 1", {}, orig))
    assert title == "Can't reach the database"
    assert "localhost:5432/formation_lap" in detail
    assert "docker compose up -d db" in detail


def test_explain_ignores_unrelated_errors():
    assert cli._explain(ValueError("boom")) is None


def test_main_prints_short_message_for_auth_error(monkeypatch, capsys):
    monkeypatch.setattr(cli.fastf1_client, "enable_cache", lambda: None)
    monkeypatch.setattr(cli, "_verbose", False)

    def boom():
        raise fastf1_client.F1TVAuthError(_NO_CREDS)

    monkeypatch.setattr(cli.orchestrator, "run_post_race_for_last_weekend", boom)
    monkeypatch.setattr("sys.argv", ["formation-data", "run-post-race"])

    with pytest.raises(SystemExit) as exit_info:
        cli.main()
    assert exit_info.value.code == 1
    err = capsys.readouterr().err
    assert "Error: FastF1 couldn't sign in to F1TV" in err
    assert "formation-data f1tv login" in err
    assert "Traceback" not in err
