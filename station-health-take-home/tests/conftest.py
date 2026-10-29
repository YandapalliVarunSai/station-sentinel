from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from seed import build_database
from station_health import supplied
from station_health.app import app
from station_health.db import connect


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    return build_database(tmp_path / "station_health.db")


@pytest.fixture
def db_connection(database_path: Path) -> Iterator[sqlite3.Connection]:
    with closing(connect(database_path)) as connection:
        yield connection


@pytest.fixture
def client(
    database_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    monkeypatch.setattr(supplied, "DATABASE_PATH", database_path)
    with TestClient(app) as test_client:
        yield test_client
