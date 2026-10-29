from __future__ import annotations

import sqlite3
from pathlib import Path


DEFAULT_DATABASE_PATH = Path(__file__).with_name("station_health.db")


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE operators (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE operator_configs (
    operator_id INTEGER PRIMARY KEY REFERENCES operators(id),
    peak_start TEXT NOT NULL,
    peak_end TEXT NOT NULL,
    min_empty_readings INTEGER NOT NULL CHECK (min_empty_readings > 0)
);

CREATE TABLE stations (
    id INTEGER PRIMARY KEY,
    operator_id INTEGER NOT NULL REFERENCES operators(id),
    name TEXT NOT NULL
);

CREATE TABLE dock_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    station_id INTEGER NOT NULL REFERENCES stations(id),
    recorded_at TEXT NOT NULL,
    bikes_available INTEGER NOT NULL CHECK (bikes_available >= 0),
    docks_total INTEGER NOT NULL CHECK (docks_total >= 0)
);

CREATE INDEX idx_stations_operator ON stations(operator_id, id);
CREATE INDEX idx_readings_station_time ON dock_readings(station_id, recorded_at);
"""


OPERATORS = [
    (1, "MetroCycle"),
    (2, "Harbour Bikes"),
]

OPERATOR_CONFIGS = [
    (1, "08:00", "10:00", 3),
    (2, "07:30", "09:30", 2),
]

STATIONS = [
    (101, 1, "Central Square"),
    (102, 1, "Riverside"),
    (103, 1, "Museum Gate"),
    (104, 1, "Market Street"),
    (201, 2, "Harbour Front"),
    (202, 2, "Old Port"),
]

READINGS = [
    # MetroCycle readings around the configured peak boundaries.
    (101, "2026-09-15T07:45:00+00:00", 0, 12),
    (101, "2026-09-15T08:00:00+00:00", 5, 12),
    (101, "2026-09-15T08:15:00+00:00", 0, 12),
    (101, "2026-09-15T08:30:00+00:00", 0, 12),
    (101, "2026-09-15T08:45:00+00:00", 0, 12),
    (101, "2026-09-15T09:00:00+00:00", 4, 12),
    (101, "2026-09-15T10:00:00+00:00", 0, 12),
    (101, "2026-09-14T08:15:00+00:00", 0, 12),
    # Additional MetroCycle station readings.
    (102, "2026-09-15T08:00:00+00:00", 0, 10),
    (102, "2026-09-15T08:15:00+00:00", 2, 10),
    (102, "2026-09-15T08:30:00+00:00", 0, 10),
    (102, "2026-09-15T08:45:00+00:00", 3, 10),
    (103, "2026-09-15T08:00:00+00:00", 0, 0),
    (103, "2026-09-15T08:15:00+00:00", 0, 0),
    (103, "2026-09-15T08:30:00+00:00", 0, 0),
    (104, "2026-09-15T08:00:00+00:00", 0, 14),
    (104, "2026-09-15T08:00:00+00:00", 0, 14),
    (104, "2026-09-15T08:15:00+00:00", 0, 14),
    (104, "2026-09-15T08:30:00+00:00", 2, 14),
    # Harbour Bikes uses a different peak window and threshold.
    (201, "2026-09-15T07:30:00+00:00", 0, 16),
    (201, "2026-09-15T07:45:00+00:00", 0, 16),
    (201, "2026-09-15T08:00:00+00:00", 3, 16),
    (202, "2026-09-15T07:30:00+00:00", 0, 8),
    (202, "2026-09-15T07:45:00+00:00", 4, 8),
]


def build_database(path: Path = DEFAULT_DATABASE_PATH) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)

    with sqlite3.connect(path) as connection:
        connection.executescript(SCHEMA)
        connection.executemany("INSERT INTO operators VALUES (?, ?)", OPERATORS)
        connection.executemany(
            "INSERT INTO operator_configs VALUES (?, ?, ?, ?)",
            OPERATOR_CONFIGS,
        )
        connection.executemany("INSERT INTO stations VALUES (?, ?, ?)", STATIONS)
        connection.executemany(
            """
            INSERT INTO dock_readings (
                station_id,
                recorded_at,
                bikes_available,
                docks_total
            ) VALUES (?, ?, ?, ?)
            """,
            READINGS,
        )

    return path


if __name__ == "__main__":
    database_path = build_database()
    print(f"Created {database_path}")
