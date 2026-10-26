# EV FairCharge

EV FairCharge compares a first-come-first-served (FCFS) charging schedule with a priority-aware FairCharge schedule. It includes a request dashboard, schedule comparison, and an auditable human-review queue for flagged FairCharge decisions.

## Requirements

- Python 3.9 or later
- pip

## Run locally (Windows PowerShell)

From the project folder, install dependencies and initialize the database:

```powershell
python -m pip install -r requirements.txt
python backend/database.py
python backend/models.py
```

Configure a distinct key for each reviewer, then start the Flask app and leave that terminal open:

```powershell
$env:FAIRCHARGE_REVIEWERS_JSON = '{"Jaishree":"unique-local-key-one","Operator":"unique-local-key-two"}'
python backend/app.py
```

Open `http://127.0.0.1:5000` in a browser.

## Use the app

1. On **Requests**, choose **Load sample CSV** to import the bundled sample data. Existing request IDs are skipped, so the action is safe to repeat.
2. Open **Schedule** and choose **Run both schedules**. Compare served totals, wait times, and request-level assignments.
3. Open **Human review** to inspect flagged high-priority decisions. Select a request, enter reviewer name and reason, and record the outcome. Reviews are stored in the audit trail.

Named reviewer keys bind the entered name to the audit identity. The legacy `FAIRCHARGE_ADMIN_TOKEN` remains a shared-key compatibility fallback; distinct keys are recommended. These environment-configured keys do not provide production account lifecycle, expiry, or revocation controls.

On **Human review**, enter operator-provided electricity tariff and grid emissions factors to enable cost and emissions estimates. Leave values unset when local figures are unknown. Use the stakeholder-session form only after real user/operator sessions; it stores feedback but does not fabricate validation results.

## Tests and evaluation

Run the automated checks from the project folder:

```powershell
python -m unittest discover -s tests -v
```

The measured sample-dataset results, targets, edge cases, limitations, and stakeholder-validation checklist are in [docs/evaluation.md](docs/evaluation.md). API/schema documentation and test/error-boundary details are in [docs/testing-and-errors.md](docs/testing-and-errors.md). Stakeholder validation is still a real-world task and must not be claimed complete until performed.

The database is stored in `backend/faircharge.db`. The sample data is in `backend/data/ev_requests.csv`.

## API

All API responses use JSON. Reviewer-protected POST requests carry `admin_token` in the JSON body; protected GET requests use the `X-Admin-Token` header.

| Method and path | Access | Purpose |
|---|---|---|
| `GET /api/health` | Public | Return service status after checking database connectivity. |
| `GET /api/requests` | Public | Return requests ordered by ID. |
| `POST /api/requests` | Public prototype API | Validate and create one request; returns `201`, `400` for invalid fields/charger, or `409` for duplicate ID. |
| `POST /api/load-csv` | Public prototype API | Import the bundled CSV; duplicate IDs are skipped. |
| `GET /api/schedule/fcfs` | Public | Read the last saved FCFS schedule and summary. |
| `POST /api/schedule/fcfs` | Public | Recompute and save FCFS, then return schedule and summary. |
| `GET /api/schedule/faircharge` | Public | Read the last saved FairCharge schedule and summary. |
| `POST /api/schedule/faircharge` | Public | Recompute and save FairCharge, then return schedule and summary. |
| `GET /api/metrics` | Public | Return algorithm metrics and their differences. |
| `GET /api/site` | Public | Return transformer cap, optional impact factors, chargers, and blocks. |
| `POST /api/site/transformer-limit` | Reviewer | Set a finite positive kW limit and recompute both schedules. |
| `POST /api/site/impact-factors` | Reviewer | Set non-negative electricity cost and/or emissions factors; `null` clears a factor. |
| `POST /api/charger-blocks` | Reviewer | Add a port block (`outage`, `overstay`, `maintenance`, or `grid curtailment`) and recompute schedules. |
| `POST /api/override` | Reviewer | Change a request's priority policy, require reviewer/reason, write audit entry, and recompute FairCharge. |
| `GET /api/overrides` | Reviewer | Return the priority-override audit history. |
| `GET /api/stakeholder-feedback` | Reviewer | Return recorded stakeholder sessions. |
| `POST /api/stakeholder-feedback` | Reviewer | Validate and save actual session feedback. |

Request creation requires `request_id`, `ev_user`, `arrival_time`, `departure_time`, `energy_required_kwh`, `priority_policy`, and `charger_id`. Times use `HH:MM`; departure must be later than arrival. Priority must be `emergency`, `resident`, `employee`, or `guest`. `departure_flexibility_min` is optional and accepts only `0`, `15`, `30`, `45`, or `60`; it extends the deadline only when necessary and is reported in the schedule reason.

Example request:

```json
{
  "request_id": 101,
  "ev_user": "Sample_User",
  "arrival_time": "16:00",
  "departure_time": "17:00",
  "energy_required_kwh": 3.5,
  "priority_policy": "resident",
  "charger_id": 1,
  "departure_flexibility_min": 15
}
```

### SQLite data model

The database file is `backend/faircharge.db`; schema initialization is in `backend/database.py`. Initialization is additive and seeds two sample chargers plus a default 14 kW site cap without deleting existing requests.

| Table | Key fields and purpose |
|---|---|
| `chargers` | `charger_id` primary key; location, kW per port, port count, availability. |
| `requests` | `request_id` primary key; user, arrival/departure, flexibility, energy, priority, and charger foreign key. |
| `site_limits` | Single row (`limit_id = 1`); transformer kW and optional tariff/emissions factors. |
| `charger_blocks` | Time-bounded blocked ports, reason, and charger foreign key. |
| `schedule_fcfs` | Persisted baseline assignments, status, wait, and explanation. |
| `schedule_faircharge` | Priority schedule plus weight, review-needed, and overridden flags. |
| `overrides` | Priority change audit: original/new policy, reason, reviewer, timestamp, request foreign key. |
| `stakeholder_feedback` | Session role/date, completion, ratings, notes, interviewer, and creation time. |

`requests` reference `chargers`; schedule and review records reference their requests; blocks reference chargers. SQLite foreign-key checks are enabled for application connections. Schema creation and additive column migrations are handled by `initialize_database()`.

API status/error behavior and unit-test coverage are described in [docs/testing-and-errors.md](docs/testing-and-errors.md).
