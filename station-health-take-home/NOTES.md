# Notes

- Starvation counts stored rows with exactly zero bikes. Duplicate timestamps and zero-dock readings count; readings need not be consecutive. Missing readings are not inferred. No matching readings returns zero and `starved: false`.
- Windows are on the requested UTC calendar date, with an inclusive start and exclusive end. Configuration must describe a same-day window using timezone-free ISO times with whole-second precision and a positive integer threshold. Overnight, empty, or invalid windows return 503.
- Stored timestamps follow the supplied extended UTC format: `YYYY-MM-DDTHH:MM:SS[.fraction]` followed by `Z` or `+00:00`. This lets the existing station/time index serve the range query, including microsecond boundary cases. Any future ingestion must normalize timestamps to this format.
- Historical requests use the operator's current configuration; the supplied schema has no configuration history. Any valid date, including a future date, is accepted.
- The supplied static token mapping is retained for this exercise. A real deployment needs managed credentials and TLS; no identity provider was added.
- Database access is read-only and request-local. Ownership, configuration, and count share a short read transaction. Connections close on success and errors. Database failures and unavailable configurations return sanitized 503 responses; missing and foreign stations return the same 404.
- Existing setup commands still work. Optional `STATION_HEALTH_DATABASE_PATH` selects an existing database; it is read when the service starts. `seed.py` still writes to its original default path.
- No required endpoint functionality remains unfinished. Linux execution has not been verified in this Windows workspace.
- Project version is 0.2.1. There are no Agents or `incol_common` packages in the supplied project to update.
