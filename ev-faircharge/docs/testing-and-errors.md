# Testing and Error Boundaries

## Run the tests

From the `ev-faircharge` project directory:

```powershell
python -m unittest discover -s tests -v
```

The tests use a new temporary SQLite database for each test. They do not need to modify `backend/faircharge.db`. The latest verified run contains **23 passing tests**.

## Coverage map

| Area | Automated evidence |
|---|---|
| Sample import | First CSV import creates 20 rows; repeating it skips existing IDs without duplicates. |
| Baseline and priority scheduling | Both algorithms produce expected sample metrics and deterministic service counts. |
| Physical constraints | Departure-too-close, unavailable charger, socket/capacity conflict, transformer overload, and overstay blocks produce expected unserved outcomes. |
| Slot-boundary correctness | A request arriving at 16:10 cannot be assigned before the next 15-minute boundary (16:15). |
| Flexibility and numeric validation | Valid 15-minute flexibility is accepted and recorded; unsupported fractional increments and non-finite numeric values are rejected. |
| Fairness and objective trade-off | Sample and constructed contention case assert served counts, energy, wait, Jain index, deadline misses, and group service results. |
| Reviewer controls | Missing credentials and invalid policy are rejected; named token identity is enforced; overrides are saved and survive rescheduling. |
| Configuration and blocks | Authenticated transformer and impact-factor changes are checked; charger blocks trigger schedule recomputation. |
| Feedback | Stakeholder-session records are stored and retrievable only through reviewer authorization. |

The tests are in `tests/test_scheduler.py`; they use Flask's test client rather than requiring a live web server.

## API error boundaries

| Condition | Expected behavior |
|---|---|
| JSON body is missing, not an object, or has invalid/missing fields | Return JSON `{"error": "..."}` with HTTP `400`. |
| Request has a duplicate `request_id` | Return HTTP `409`; do not replace the existing request. |
| Request references an unknown charger | Return HTTP `400`. |
| Invalid time, priority, flexibility, non-positive energy, or non-finite numeric input | Reject input with HTTP `400`; do not create or update the affected record. |
| Reviewer credentials are not configured on the server | Protected operations return HTTP `503`. |
| Reviewer token is missing or wrong | Protected operations return HTTP `401`. |
| Configured named reviewer identity does not match the supplied reviewer name | Return HTTP `403`. |
| Requested override schedule or referenced resource does not exist | Return HTTP `404` where the endpoint checks for that resource. |
| Unknown route or unsupported HTTP method | Return JSON `404` or `405`. |
| Bundled CSV cannot be read, parsed, or inserted | CSV endpoint returns JSON error with HTTP `500`; it does not report a successful import. |
| Database/health check fails unexpectedly | The health endpoint does not return a false `"ok"` result; the request fails rather than reporting healthy. |

Errors are deliberately not converted to success-shaped defaults. The API has explicit handlers for common `400`, `404`, and `405` responses. Unexpected server errors are not hidden by a blanket exception handler; Flask returns a server error. The local app runs with debug mode disabled.

## Known limits

- This is a local student prototype, not a publicly deployed service. Request creation and CSV import are not authenticated; do not expose it to the public internet without deployment-specific access controls.
- Reviewer tokens are environment-configured prototype credentials, not production accounts with lifecycle, role management, expiry, or revocation.
- SQLite and the bundled synthetic dataset support demonstration and repeatable evaluation, not multi-site production load.
- Tests verify software behavior for specified synthetic cases; they do not establish real-world fairness, electrical safety certification, user acceptance, or charger interoperability.
