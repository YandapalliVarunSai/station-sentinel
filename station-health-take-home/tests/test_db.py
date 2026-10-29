from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from seed import build_database
from station_health.db import connect


def test_read_only_connection_cannot_write(database_path: Path) -> None:
    with closing(connect(database_path, read_only=True)) as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("DELETE FROM dock_readings")


def test_read_only_connection_does_not_create_missing_database(tmp_path: Path) -> None:
    path = tmp_path / "missing.db"
    with pytest.raises(sqlite3.OperationalError):
        connect(path, read_only=True)
    assert not path.exists()


def test_read_only_uri_handles_spaces_and_hashes(tmp_path: Path) -> None:
    path = build_database(tmp_path / "station # data.db")
    with closing(connect(path, read_only=True)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM operators").fetchone()[0] == 2
