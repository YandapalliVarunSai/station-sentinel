from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from station_health.app import app
from station_health.db import connect
from station_health.supplied import TOKENS


def test_supplied_tokens_map_to_seeded_operators() -> None:
    assert TOKENS == {
        "metro-token": 1,
        "harbour-token": 2,
    }


def test_connection_helper_returns_named_rows(database_path: Path) -> None:
    with connect(database_path) as connection:
        row = connection.execute(
            "SELECT id, name FROM operators WHERE id = ?",
            (1,),
        ).fetchone()

    assert dict(row) == {"id": 1, "name": "MetroCycle"}


def test_health_endpoint_confirms_the_supplied_app_runs() -> None:
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
