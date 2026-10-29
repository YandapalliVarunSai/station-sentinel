from __future__ import annotations

import logging
import sqlite3
from contextlib import closing
from datetime import date, datetime, time
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Path, Query
from pydantic import BaseModel, BeforeValidator

from station_health import supplied
from station_health.auth import authenticated_operator
from station_health.db import connect


logger = logging.getLogger(__name__)
app = FastAPI(title="Station Health", version="0.2.1")


class StarvationResult(BaseModel):
    station_id: int
    date: date
    starved: bool
    empty_readings: int
    min_empty_readings: int


def parse_date(value: str) -> date:
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("Use YYYY-MM-DD")
    return parsed


def peak_bounds(config: sqlite3.Row, day: date) -> tuple[str, str]:
    start = time.fromisoformat(config["peak_start"])
    end = time.fromisoformat(config["peak_end"])
    threshold = config["min_empty_readings"]
    if (
        start.tzinfo is not None
        or end.tzinfo is not None
        or start.microsecond
        or end.microsecond
        or start >= end
        or type(threshold) is not int
        or threshold <= 0
    ):
        raise ValueError("Invalid starvation configuration")

    # No timezone suffix: exact-boundary UTC readings sort after these bounds,
    # including both Z / +00:00 and optional fractional seconds.
    return (
        datetime.combine(day, start).isoformat(),
        datetime.combine(day, end).isoformat(),
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get(
    "/stations/{station_id}/starvation",
    responses={
        401: {"description": "Invalid or missing bearer token"},
        404: {"description": "Station not found"},
        503: {"description": "Station history or configuration unavailable"},
    },
)
def station_starvation(
    station_id: Annotated[int, Path(gt=0, le=2**63 - 1)],
    requested_date: Annotated[
        date, BeforeValidator(parse_date), Query(alias="date")
    ],
    operator_id: Annotated[int, Depends(authenticated_operator)],
) -> StarvationResult:
    try:
        with closing(connect(supplied.DATABASE_PATH, read_only=True)) as connection:
            # Keep ownership, configuration and readings in one read snapshot.
            connection.execute("BEGIN")
            config = connection.execute(
                """
                SELECT configs.peak_start, configs.peak_end,
                       configs.min_empty_readings
                FROM stations
                LEFT JOIN operator_configs AS configs
                    ON configs.operator_id = stations.operator_id
                WHERE stations.id = ? AND stations.operator_id = ?
                """,
                (station_id, operator_id),
            ).fetchone()
            if config is None:
                raise HTTPException(status_code=404, detail="Station not found")

            try:
                start, end = peak_bounds(config, requested_date)
            except (TypeError, ValueError):
                logger.error(
                    "Invalid starvation configuration for operator %s", operator_id
                )
                raise HTTPException(
                    status_code=503, detail="Station configuration unavailable"
                ) from None

            empty_readings = connection.execute(
                """
                SELECT COUNT(*)
                FROM dock_readings
                WHERE station_id = ?
                  AND recorded_at >= ? AND recorded_at < ?
                  AND bikes_available = 0
                """,
                (station_id, start, end),
            ).fetchone()[0]
    except sqlite3.Error:
        logger.exception("Unable to read station history")
        raise HTTPException(
            status_code=503, detail="Station history unavailable"
        ) from None

    return StarvationResult(
        station_id=station_id,
        date=requested_date,
        starved=empty_readings >= config["min_empty_readings"],
        empty_readings=empty_readings,
        min_empty_readings=config["min_empty_readings"],
    )
