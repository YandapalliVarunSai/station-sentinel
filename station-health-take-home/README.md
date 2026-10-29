# Take-home: Station Health Service

Thanks for making time for this exercise. It is a small, self-contained service created for the interview; Bizimply will not use your solution in production.

## The problem

A bike-share company manages stations across a city. Each station contains **docks**: individual spaces where bicycles are parked and locked. During the morning commute, some stations repeatedly have no bikes available, leaving riders unable to start a journey.

The company's operations team wants to review past station availability so it can decide where to investigate or adjust bike replenishment.

The service is shared by multiple bike-share companies. Each company is an **operator** and manages its own set of stations. An authenticated operations team may access all stations belonging to its operator, but no stations belonging to another operator.

## Your task

Build an API endpoint that lets an authenticated operator check whether one of its stations met the **starvation rule** on a selected date.

Each operator has:

- a morning peak window in UTC;
- a minimum number of empty readings.

A station qualifies as starved when it has at least the configured minimum number of readings with `bikes_available == 0` during its peak window on the requested date. The peak window includes its start time and excludes its end time.

The result must state whether the station qualified as starved and include the empty-reading count supporting that result.

Operators must not be able to access another operator's stations or discover whether those stations exist.

Choose the endpoint route, response structure, and internal organisation you consider appropriate. Add tests that give confidence in the behaviour.

## What is supplied

The project includes:

- a minimal runnable FastAPI application;
- a SQLite connection helper;
- a token-to-operator mapping;
- `seed.py`, which creates a SQLite database containing synthetic operators, configurations, stations, and historical readings;
- a working pytest setup with basic scaffold tests.

Each historical reading records:

- `station_id`;
- `recorded_at`, an ISO 8601 UTC timestamp;
- `bikes_available`;
- `docks_total`, the station's total number of bicycle parking spaces at that time.

Readings are normally recorded every 15 minutes.

Inspect the supplied schema and data as you would when joining an existing service. Where behaviour is unspecified, make a reasonable assumption and continue.

## Time and tools

Spend no more than **three hours**, including setup and testing. Stop when you reach the limit and submit what you have. An incomplete submission is acceptable; briefly identify what remains unfinished.

Use the tools you would normally use at work, including AI coding assistants. You are responsible for the solution you submit and should be prepared to explain and modify it during the debrief.

If the supplied setup prevents you from getting started, contact us so we can resolve it and adjust the time allowance.

## Setup

Python 3.12 or newer is required.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python seed.py
pytest
uvicorn station_health.app:app --reload
```

The supplied test suite should report eight passing tests before you begin. The health endpoint is available at `GET /health`.

Do not modify the synthetic seed data merely to make your implementation pass.

## Notes

Include a short `NOTES.md` containing:

- assumptions that materially affect the service's behaviour;
- incomplete functionality;
- any changes needed to the supplied setup or run commands.

Short bullets are enough. Design history, AI transcripts, and a lengthy report are not required.

## Submitting

Send a ZIP file or a link to a private repository containing your implementation, tests, and `NOTES.md`.

Exclude `.venv/`, cache directories, and the generated `station_health.db` file.

The submission will form the basis of a 60-minute interview. We will walk through your solution, discuss a small requirement change, and ask you to implement that change using the tools you normally use.

## Implemented API (0.2.1)

`GET /stations/{station_id}/starvation?date=YYYY-MM-DD` requires an
`Authorization: Bearer <token>` header. The supplied tokens are `metro-token`
(operator 1) and `harbour-token` (operator 2). API documentation is at `/docs`.

```bash
curl -H 'Authorization: Bearer metro-token' \
  'http://127.0.0.1:8000/stations/101/starvation?date=2026-09-15'
```

```json
{
  "station_id": 101,
  "date": "2026-09-15",
  "starved": true,
  "empty_readings": 3,
  "min_empty_readings": 3
}
```

| Status | Meaning |
| --- | --- |
| 200 | Result for the owned station, including when no readings match |
| 401 | Missing, malformed, or unknown bearer token |
| 404 | Station does not exist or belongs to another operator |
| 422 | Missing/invalid date or station ID outside the positive signed 64-bit range |
| 503 | Database unavailable or operator configuration missing/invalid |

Dates must use `YYYY-MM-DD`. See [NOTES.md](NOTES.md) for counting and timestamp
assumptions. The implementation counts rows in SQL using the existing
`(station_id, recorded_at)` index; it does not load historical readings into Python.
Each request opens and closes its own read-only connection. Two SELECTs share
a short read transaction: ownership and configuration are checked before
counting history, and concurrent updates cannot mix different database snapshots.
Time bounds are normalized in Python; the indexed timestamp column is compared
directly. SQL returns one count, so Python memory use does not grow with history.

The original eight scaffold tests passed before changes. The completed suite has
87 passing tests on Python 3.12.7 / Windows. Run it with `python -m pytest`; it
covers tenant isolation, authentication, date validation,
UTC boundaries, duplicates, zero docks, unavailable data, connection cleanup,
concurrent requests, and concurrent configuration updates. A deterministic
test also compares SQL counts with independent timezone-aware datetime arithmetic
across 868 mixed readings and 18 station/date combinations.

SQLite query-plan inspection confirmed:

```text
SEARCH dock_readings USING INDEX idx_readings_station_time
(station_id=? AND recorded_at>? AND recorded_at<?)
```

For a Linux server, provision the database first, then run without development
reload:

```bash
export STATION_HEALTH_DATABASE_PATH=/absolute/path/to/station_health.db
uvicorn station_health.app:app --host 0.0.0.0 --port 8000
```

The environment variable is optional and is read at startup; its default remains
the project-root database. `python seed.py` recreates the synthetic database at
that default path. Retain the supplied token mapping only for the exercise;
production deployment needs managed credentials and TLS. No new runtime
dependency beyond explicitly requiring Pydantic 2 (already used by FastAPI) was
introduced.
