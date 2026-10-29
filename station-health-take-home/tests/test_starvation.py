from __future__ import annotations

import importlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from random import Random
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from station_health import supplied
from station_health.db import connect


METRO = {"Authorization": "Bearer metro-token"}
DAY = "2026-09-15"
ROUTE = "/stations/101/starvation"


def result(
    client: TestClient, station_id: int = 101, day: str = DAY, token: str = "metro-token"
) -> Response:
    return client.get(
        f"/stations/{station_id}/starvation",
        params={"date": day},
        headers={"Authorization": f"Bearer {token}"},
    )


@pytest.mark.parametrize(
    ("station_id", "token", "count", "starved", "threshold"),
    [
        (101, "metro-token", 3, True, 3),
        (102, "metro-token", 2, False, 3),
        (103, "metro-token", 3, True, 3),  # Zero docks still count.
        (104, "metro-token", 3, True, 3),  # Duplicate timestamps count separately.
        (201, "harbour-token", 2, True, 2),
        (202, "harbour-token", 1, False, 2),
    ],
)
def test_seeded_station_results(
    client: TestClient,
    station_id: int,
    token: str,
    count: int,
    starved: bool,
    threshold: int,
) -> None:
    response = result(client, station_id, token=token)
    assert response.status_code == 200
    assert response.json() == {
        "station_id": station_id,
        "date": DAY,
        "starved": starved,
        "empty_readings": count,
        "min_empty_readings": threshold,
    }


@pytest.mark.parametrize(
    "authorization",
    [
        None, "", "Bearer", "Bearer ", "Basic metro-token", "metro-token",
        "Bearer unknown", "Bearer METRO-TOKEN", "Bearer metro-token extra",
        "Bearer metro-token\t",
    ],
)
def test_invalid_authentication(client: TestClient, authorization: str | None) -> None:
    headers = {} if authorization is None else {"Authorization": authorization}
    response = client.get(ROUTE, params={"date": DAY}, headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {"detail": "Invalid or missing bearer token"}


def test_bearer_scheme_is_case_insensitive(client: TestClient) -> None:
    response = client.get(
        ROUTE, params={"date": DAY},
        headers={"Authorization": "bEaReR metro-token"},
    )
    assert response.status_code == 200


@pytest.mark.parametrize(
    ("token", "foreign_station"), [("metro-token", 201), ("harbour-token", 101)]
)
def test_foreign_station_is_indistinguishable_from_missing_station(
    client: TestClient, token: str, foreign_station: int
) -> None:
    foreign = result(client, foreign_station, token=token)
    missing = result(client, 999, token=token)
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json() == {"detail": "Station not found"}


def test_query_parameters_cannot_override_authenticated_operator(client: TestClient) -> None:
    response = client.get(
        "/stations/201/starvation",
        params={"date": DAY, "operator_id": 2, "token": "harbour-token"},
        headers=METRO,
    )
    assert response.status_code == 404


def test_token_in_query_does_not_authenticate(client: TestClient) -> None:
    response = client.get(ROUTE, params={"date": DAY, "token": "metro-token"})
    assert response.status_code == 401


@pytest.mark.parametrize(
    "day",
    [
        "", "not-a-date", "2026-02-29", "2026-09-31", "2026-00-15",
        "2026-9-15", "20260915", "2026-W38-2", "0", "1799971200",
        "2026-09-15T00:00:00Z", "2026-09-15T08:00:00+00:00",
        "2026-09-15' OR 1=1 --", "0000-01-01", "10000-01-01",
    ],
)
def test_invalid_dates(client: TestClient, day: str) -> None:
    assert result(client, day=day).status_code == 422


def test_date_is_required(client: TestClient) -> None:
    assert client.get(ROUTE, headers=METRO).status_code == 422


@pytest.mark.parametrize(
    "station_id", ["0", "-1", "abc", "1.5", "9223372036854775808", "101 OR 1=1"]
)
def test_invalid_station_ids(client: TestClient, station_id: str) -> None:
    response = client.get(
        f"/stations/{station_id}/starvation", params={"date": DAY}, headers=METRO
    )
    assert response.status_code == 422


def test_largest_sqlite_id_does_not_overflow(client: TestClient) -> None:
    assert result(client, 2**63 - 1).status_code == 404


@pytest.mark.parametrize(
    "day", ["2026-09-14", "2026-09-16", "2024-02-29", "0001-01-01", "9999-12-31"]
)
def test_only_requested_date_counts(client: TestClient, day: str) -> None:
    response = result(client, day=day)
    assert response.status_code == 200
    assert response.json()["date"] == day
    assert response.json()["empty_readings"] == (1 if day == "2026-09-14" else 0)
    assert response.json()["starved"] is False


@pytest.mark.parametrize("suffix", ["+00:00", "Z"])
def test_peak_boundaries_and_fractional_seconds(
    client: TestClient, db_connection: sqlite3.Connection, suffix: str
) -> None:
    times = [
        ("07:59:59.999999", 0),
        ("08:00:00", 0),  # Inclusive start.
        ("08:00:00.000000", 0),
        ("08:00:00.000001", 0),
        ("08:15:00", 2),  # Non-empty reading.
        ("09:59:59.999999", 0),
        ("10:00:00", 0),  # Exclusive end.
        ("10:00:00.000000", 0),
        ("10:00:00.000001", 0),
    ]
    with db_connection:
        db_connection.execute("DELETE FROM dock_readings WHERE station_id = 101")
        db_connection.executemany(
            """INSERT INTO dock_readings
               (station_id, recorded_at, bikes_available, docks_total)
               VALUES (101, ?, ?, 12)""",
            [(f"{DAY}T{time}{suffix}", bikes) for time, bikes in times],
        )
    response = result(client)
    assert response.status_code == 200
    assert response.json()["empty_readings"] == 4
    assert response.json()["starved"] is True


@pytest.mark.parametrize("bikes", [None, 5])
def test_no_readings_or_only_nonempty_readings(
    client: TestClient, db_connection: sqlite3.Connection, bikes: int | None
) -> None:
    with db_connection:
        db_connection.execute("DELETE FROM dock_readings WHERE station_id = 101")
        if bikes is not None:
            db_connection.execute(
                """INSERT INTO dock_readings
                   (station_id, recorded_at, bikes_available, docks_total)
                   VALUES (101, ?, ?, 12)""",
                (f"{DAY}T08:00:00+00:00", bikes),
            )
    response = result(client)
    assert response.status_code == 200
    assert response.json()["empty_readings"] == 0
    assert response.json()["starved"] is False


def test_updated_rule_is_used_on_next_request(
    client: TestClient, db_connection: sqlite3.Connection
) -> None:
    assert result(client).json()["starved"] is True
    with db_connection:
        db_connection.execute(
            "UPDATE operator_configs SET min_empty_readings = 4 WHERE operator_id = 1"
        )
    response = result(client)
    assert response.json()["empty_readings"] == 3
    assert response.json()["min_empty_readings"] == 4
    assert response.json()["starved"] is False
    with db_connection:
        db_connection.execute(
            """UPDATE operator_configs
               SET peak_start = '07:45', peak_end = '08:15', min_empty_readings = 1
               WHERE operator_id = 1"""
        )
    response = result(client)
    assert response.json()["empty_readings"] == 1
    assert response.json()["starved"] is True


@pytest.mark.parametrize(
    ("start", "end", "threshold"),
    [
        ("bad", "10:00", 3), ("25:00", "10:00", 3),
        ("08:00", "bad", 3), ("10:00", "08:00", 3),
        ("08:00", "08:00", 3), ("23:00", "01:00", 3),
        ("08:00+00:00", "10:00+00:00", 3),
        ("08:00:00.000001", "10:00", 3), ("08:00", "10:00", 1.5),
    ],
)
def test_invalid_configuration_does_not_report_false_success(
    client: TestClient, db_connection: sqlite3.Connection,
    start: str, end: str, threshold: int | float,
) -> None:
    with db_connection:
        db_connection.execute(
            """UPDATE operator_configs
               SET peak_start = ?, peak_end = ?, min_empty_readings = ?
               WHERE operator_id = 1""",
            (start, end, threshold),
        )
    response = result(client)
    assert response.status_code == 503
    assert response.json() == {"detail": "Station configuration unavailable"}


def test_missing_configuration_is_only_visible_to_owner(
    client: TestClient, db_connection: sqlite3.Connection
) -> None:
    with db_connection:
        db_connection.execute("DELETE FROM operator_configs WHERE operator_id = 1")
    assert result(client).status_code == 503
    assert result(client, token="harbour-token").status_code == 404


def test_database_failure_is_sanitized_and_does_not_create_database(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "missing.db"
    monkeypatch.setattr(supplied, "DATABASE_PATH", missing)
    response = result(client)
    assert response.status_code == 503
    assert response.json() == {"detail": "Station history unavailable"}
    assert not missing.exists()


def test_missing_schema_returns_service_unavailable(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty = tmp_path / "empty.db"
    empty.touch()
    monkeypatch.setattr(supplied, "DATABASE_PATH", empty)
    assert result(client).status_code == 503


def test_unauthenticated_requests_do_not_access_database(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unexpected_connection(*args, **kwargs):
        pytest.fail("Unauthenticated request accessed the database")

    monkeypatch.setattr(
        importlib.import_module("station_health.app"), "connect", unexpected_connection
    )
    response = client.get(
        "/stations/invalid/starvation", params={"date": "invalid"}
    )
    assert response.status_code == 401


@pytest.mark.parametrize("outcome", ["success", "not_found", "invalid_config", "sql_error"])
def test_connection_closes_on_every_exit(
    client: TestClient, db_connection: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch, outcome: str,
) -> None:
    connections = []

    def tracking_connect(path: Path, *, read_only: bool = False):
        connection = Mock(wraps=connect(path, read_only=read_only))
        connections.append(connection)
        return connection

    monkeypatch.setattr(
        importlib.import_module("station_health.app"), "connect", tracking_connect
    )
    with db_connection:
        if outcome == "invalid_config":
            db_connection.execute("DELETE FROM operator_configs WHERE operator_id = 1")
        elif outcome == "sql_error":
            db_connection.execute("DROP TABLE dock_readings")
    response = result(client, 999 if outcome == "not_found" else 101)
    assert response.status_code == {
        "success": 200, "not_found": 404, "invalid_config": 503, "sql_error": 503,
    }[outcome]
    assert len(connections) == 1
    connections[0].close.assert_called_once_with()


def test_parallel_requests_keep_operators_separate(client: TestClient) -> None:
    requests = [(101, "metro-token", 3), (201, "harbour-token", 2)] * 12

    def check(request: tuple[int, str, int]) -> None:
        station_id, token, expected = request
        response = result(client, station_id, token=token)
        assert response.status_code == 200
        assert response.json()["station_id"] == station_id
        assert response.json()["empty_readings"] == expected

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(check, requests))


def test_rule_supports_whole_second_boundaries(
    client: TestClient, db_connection: sqlite3.Connection
) -> None:
    with db_connection:
        db_connection.execute(
            """UPDATE operator_configs
               SET peak_start = '08:00:30', peak_end = '08:01:30',
                   min_empty_readings = 2
               WHERE operator_id = 1"""
        )
        db_connection.execute("DELETE FROM dock_readings WHERE station_id = 101")
        db_connection.executemany(
            """INSERT INTO dock_readings
               (station_id, recorded_at, bikes_available, docks_total)
               VALUES (101, ?, 0, 12)""",
            [
                (f"{DAY}T{time}Z",)
                for time in [
                    "08:00:29.999999", "08:00:30", "08:01:29.999999", "08:01:30"
                ]
            ],
        )
    response = result(client)
    assert response.status_code == 200
    assert response.json()["empty_readings"] == 2
    assert response.json()["starved"] is True


def test_rule_and_readings_share_a_snapshot_during_concurrent_update(
    client: TestClient, db_connection: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # WAL lets a writer commit while this request holds a read snapshot.
    assert db_connection.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"

    def snapshot_connect(path: Path, *, read_only: bool = False):
        connection = connect(path, read_only=read_only)
        wrapped = Mock(wraps=connection)

        def execute(sql: str, *parameters):
            if "SELECT COUNT(*)" in sql:
                with closing(connect(path)) as writer, writer:
                    writer.execute(
                        """UPDATE operator_configs
                           SET min_empty_readings = 4 WHERE operator_id = 1"""
                    )
                    writer.execute("DELETE FROM dock_readings WHERE station_id = 101")
            return connection.execute(sql, *parameters)

        wrapped.execute.side_effect = execute
        return wrapped

    monkeypatch.setattr(
        importlib.import_module("station_health.app"), "connect", snapshot_connect
    )
    response = result(client)
    assert response.status_code == 200
    assert response.json()["empty_readings"] == 3
    assert response.json()["min_empty_readings"] == 3
    assert response.json()["starved"] is True
    # A subsequent request sees the newly committed configuration and readings.
    next_response = result(client)
    assert next_response.json()["empty_readings"] == 0
    assert next_response.json()["min_empty_readings"] == 4
    assert next_response.json()["starved"] is False


def test_openapi_describes_bearer_security_and_date(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    operation = schema["paths"]["/stations/{station_id}/starvation"]["get"]
    assert operation["security"] == [{"HTTPBearer": []}]
    date_parameter = next(
        parameter for parameter in operation["parameters"] if parameter["name"] == "date"
    )
    assert date_parameter["required"] is True
    assert date_parameter["schema"]["format"] == "date"


def test_sql_count_matches_datetime_oracle_for_mixed_histories(
    client: TestClient, db_connection: sqlite3.Connection
) -> None:
    random = Random(753)
    origin = datetime(2026, 9, 15, tzinfo=UTC)
    rules = {
        "metro-token": ("08:00:30", "10:00:45", 5, (101, 102, 103, 104)),
        "harbour-token": ("07:30:15", "09:30:30", 7, (201, 202)),
    }
    readings: list[tuple[int, str, int, int]] = []
    for start, end, _, stations in rules.values():
        for station_id in stations:
            timestamps = [
                origin + timedelta(
                    seconds=random.randrange(-86400, 172800),
                    microseconds=random.randrange(1000000),
                )
                for _ in range(120)
            ]
            # Include exact boundaries and adjacent microseconds on every date.
            for day_offset in (-1, 0, 1):
                for boundary in (start, end):
                    instant = datetime.combine(
                        (origin + timedelta(days=day_offset)).date(),
                        time.fromisoformat(boundary),
                        tzinfo=UTC,
                    )
                    timestamps.extend(
                        instant + timedelta(microseconds=offset)
                        for offset in (-1, 0, 1)
                    )
            for instant in timestamps:
                recorded_at = instant.isoformat()
                if random.choice((False, True)):
                    recorded_at = recorded_at.replace("+00:00", "Z")
                readings.append(
                    (station_id, recorded_at, random.choice((0, 0, 1, 5)),
                     random.choice((0, 12)))
                )
    readings.extend(random.choices(readings, k=40))

    with db_connection:
        db_connection.execute("DELETE FROM dock_readings")
        db_connection.executemany(
            """INSERT INTO dock_readings
               (station_id, recorded_at, bikes_available, docks_total)
               VALUES (?, ?, ?, ?)""",
            readings,
        )
        for operator_id, (start, end, threshold, _) in enumerate(rules.values(), 1):
            db_connection.execute(
                """UPDATE operator_configs
                   SET peak_start = ?, peak_end = ?, min_empty_readings = ?
                   WHERE operator_id = ?""",
                (start, end, threshold, operator_id),
            )

    parsed = [
        (station_id, datetime.fromisoformat(recorded_at), bikes)
        for station_id, recorded_at, bikes, _ in readings
    ]
    for token, (start, end, threshold, stations) in rules.items():
        for day in (date(2026, 9, 14), date(2026, 9, 15), date(2026, 9, 16)):
            lower = datetime.combine(day, time.fromisoformat(start), tzinfo=UTC)
            upper = datetime.combine(day, time.fromisoformat(end), tzinfo=UTC)
            for station_id in stations:
                expected = sum(
                    station == station_id and bikes == 0 and lower <= instant < upper
                    for station, instant, bikes in parsed
                )
                response = result(client, station_id, day.isoformat(), token)
                assert response.status_code == 200
                assert response.json()["empty_readings"] == expected
                assert response.json()["starved"] is (expected >= threshold)
