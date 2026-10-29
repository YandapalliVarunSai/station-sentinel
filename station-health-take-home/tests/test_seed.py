from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from seed import build_database


EXPECTED_TABLES = {
    "dock_readings",
    "operator_configs",
    "operators",
    "stations",
}


def seeded_connection(tmp_path: Path) -> sqlite3.Connection:
    database_path = build_database(tmp_path / "station_health.db")
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    return connection


def test_seed_builds_the_supplied_schema(tmp_path: Path) -> None:
    with seeded_connection(tmp_path) as connection:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()

    assert {row["name"] for row in rows} >= EXPECTED_TABLES


def test_seed_contains_two_operators_with_owned_stations_and_configs(
    tmp_path: Path,
) -> None:
    with seeded_connection(tmp_path) as connection:
        operators = connection.execute(
            """
            SELECT
                operators.id,
                COUNT(DISTINCT stations.id) AS station_count,
                operator_configs.min_empty_readings
            FROM operators
            JOIN stations ON stations.operator_id = operators.id
            JOIN operator_configs ON operator_configs.operator_id = operators.id
            GROUP BY operators.id, operator_configs.min_empty_readings
            ORDER BY operators.id
            """
        ).fetchall()

    assert [dict(row) for row in operators] == [
        {"id": 1, "station_count": 4, "min_empty_readings": 3},
        {"id": 2, "station_count": 2, "min_empty_readings": 2},
    ]


def test_seed_contains_readings_for_each_operator(tmp_path: Path) -> None:
    with seeded_connection(tmp_path) as connection:
        reading_counts = connection.execute(
            """
            SELECT stations.operator_id, COUNT(*) AS reading_count
            FROM stations
            JOIN dock_readings ON dock_readings.station_id = stations.id
            GROUP BY stations.operator_id
            ORDER BY stations.operator_id
            """
        ).fetchall()

    assert all(row["reading_count"] > 0 for row in reading_counts)
    assert [row["operator_id"] for row in reading_counts] == [1, 2]


def test_seed_reading_timestamps_are_utc_iso_8601(tmp_path: Path) -> None:
    with seeded_connection(tmp_path) as connection:
        rows = connection.execute(
            "SELECT recorded_at FROM dock_readings"
        ).fetchall()

    parsed = [datetime.fromisoformat(row["recorded_at"]) for row in rows]
    assert parsed
    assert all(timestamp.utcoffset().total_seconds() == 0 for timestamp in parsed)


def test_seed_reading_values_are_non_negative(tmp_path: Path) -> None:
    with seeded_connection(tmp_path) as connection:
        row = connection.execute(
            """
            SELECT
                MIN(bikes_available) AS minimum_bikes,
                MIN(docks_total) AS minimum_docks
            FROM dock_readings
            """
        ).fetchone()

    assert row["minimum_bikes"] >= 0
    assert row["minimum_docks"] >= 0
