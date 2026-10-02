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

The measured sample-dataset results, targets, edge cases, limitations, and stakeholder-validation checklist are in [docs/evaluation.md](docs/evaluation.md). Stakeholder validation is still a real-world task and must not be claimed complete until performed.

The database is stored in `backend/faircharge.db`. The sample data is in `backend/data/ev_requests.csv`.

## API

- `GET /api/health`
- `GET|POST /api/requests`
- `GET|POST /api/schedule/fcfs`
- `GET|POST /api/schedule/faircharge`
- `GET /api/metrics`
- `POST /api/override`
- `GET /api/overrides`
- `POST /api/load-csv`
- `GET /api/site`
- `POST /api/site/transformer-limit` (reviewer token required)
- `POST /api/site/impact-factors` (reviewer token required)
- `POST /api/charger-blocks` (reviewer token required; outage, overstay, maintenance, or grid curtailment)
- `GET|POST /api/stakeholder-feedback` (reviewer token required)

Request creation accepts optional `departure_flexibility_min` values of `0`, `15`, `30`, `45`, or `60`. The flexibility extends the departure window only when necessary and is recorded in the schedule reason.
