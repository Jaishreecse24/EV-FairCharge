# EV FairCharge — Review 3 Submission Report

**Review milestone:** Review 3

**Report date:** 26 October 2026

**Project status:** Working prototype; automated verification complete; real stakeholder validation pending
**Prepared by:** Jaishree

> This report presents implemented work and measured evidence, including negative results and unfinished real-world validation. It does not claim evaluator marks or stakeholder outcomes that have not been observed.

## 1. Executive summary

EV FairCharge is a working prototype for comparing first-come-first-served (FCFS) and priority-aware EV charging schedules under shared charger and site-power constraints. It includes a Flask API, SQLite persistence, a browser-based request dashboard, schedule comparison, and an authenticated human-review workflow.

The implementation and automated evaluation are ready to demonstrate. The current suite passes **23 automated tests**. On the bundled synthetic dataset, both algorithms serve 13 of 20 requests and have the same energy, wait, fairness, and deadline metrics. A separately constructed contention case demonstrates a FairCharge trade-off: it serves one more emergency request and one more request overall, with a higher average wait. The prototype does not claim that this synthetic case predicts real-site performance.

Real user/operator validation has **not** been conducted. The app contains a protected form for recording actual sessions, but no user feedback or validation result is claimed in this report.

## 2. What is implemented

- Request storage, validated API creation, and repeat-safe import of 20 bundled synthetic requests.
- Deterministic FCFS and FairCharge scheduling in 15-minute slots.
- Charger-port availability, site transformer capacity, charger availability, and time-bounded outage/overstay/maintenance/grid-curtailment blocks.
- Bounded, optional departure flexibility and explicit unserved reasons.
- Schedule comparison and metrics for served requests, wait, energy, priority-group service, Jain fairness, deadline misses, and optional site-factor-based cost/emissions.
- Protected reviewer workflow for priority overrides, audit history, site settings, and stakeholder-feedback recording.
- Input checks for non-finite numeric values and regression coverage for off-grid arrival times.

An override changes a soft priority policy only; it cannot bypass physical schedule constraints. Reviewer keys are prototype controls, not production identity management.

## 3. Requirements and review-feedback traceability

| Problem-statement / review criterion | Implementation and evidence | Status |
|---|---|---|
| Deployable student prototype, not only a concept or notebook | Flask app, SQLite persistence, static browser screens, setup/run instructions. | Implemented for local demonstration; not production deployed. |
| Vehicle requests, charger capacity, deadlines, energy, and priority | Request/charger/site schema and bundled 20-request CSV. | Implemented; dataset is synthetic. |
| Baseline and competing objectives | FCFS arrival-order baseline compared with priority-aware FairCharge; both use the same feasibility rules. | Implemented and measured. |
| Explicit hard and soft constraints | Port occupancy, transformer cap, availability, time window, and blocks are hard; priority order and opted-in bounded flexibility are soft. | Implemented and tested. |
| Authorized human review of high-impact outcomes | Unserved emergency/resident decisions are flagged; reviewer identity, reason, timestamp, and changed policy are audited. | Implemented and tested; reviewer-token controls are prototype-grade. |
| At least three failure/edge cases | Deadline infeasibility, socket contention, transformer overload, outage, overstay, invalid flexibility, and off-grid arrival are covered. | Implemented and tested. |
| Measurable baseline, target, result, and error analysis | Sample and controlled-contention metrics are reported with group-level service, energy, wait, Jain index, and deadline misses. | Synthetic experiment complete; bundled sample does not meet the priority-improvement target. |
| Social/environmental benefit against cost, maintenance, and unintended consequences | Emergency access and fairness metrics quantify selected social outcomes; cost/emissions are optional operator-factor estimates; operational burden and risks are discussed below. | Prototype comparison documented; real-world cost and maintenance measurements unavailable. |
| Metric dashboard and limitations | Schedule screen shows request-level comparison and aggregate metrics; limitations are recorded in the evaluation and this report. | Implemented and documented. |
| Review 2: API/schema documentation and testing/error boundaries | README documents endpoints and tables; a separate note describes test coverage and error behavior. | Addressed; 23 automated tests pass. |
| Short user/stakeholder validation | Protected session form is available for recording actual participants' task results and feedback. | **Not yet conducted**; cannot be claimed complete until real sessions occur. |

## 4. Evaluation results

### Bundled sample (20 synthetic requests)

| Measure | FCFS | FairCharge |
|---|---:|---:|
| Requests served | 13 / 20 (65%) | 13 / 20 (65%) |
| Energy required | 89.25 kWh | 89.25 kWh |
| Energy served / unserved | 57.75 / 31.50 kWh | 57.75 / 31.50 kWh |
| Average wait among served | 4.62 min | 4.62 min |
| Jain fairness index | 0.9835 | 0.9835 |
| Deadline-miss rate | 35.00% | 35.00% |
| Emergency requests served | 1 / 2 | 1 / 2 |

**Finding:** the bundled sample does not show improved access from priority ordering. This is a measured negative result and should be presented as such.

### Controlled contention experiment

A separate two-request conflict on the one-port charger results in FCFS serving 14/22 requests and FairCharge serving 15/22. FairCharge serves one additional emergency request and 7 kWh more, while average wait rises from 4.29 to 9.00 minutes. This is a constructed test case, not real-world validation.

Detailed assumptions, group-level results, edge cases, and limitations are in [evaluation.md](./evaluation.md).

### Objective trade-offs and error analysis

The project compares two scheduling objectives over identical physical constraints: FCFS favors arrival order, while FairCharge favors the declared priority order. The bundled sample is a counterexample to assuming that priority ordering always improves outcomes: the served set and reported metrics are equal. The constructed contention case demonstrates that priority can change who receives service, but it also increases average wait by 4.71 minutes. Both results are reported so the evaluation does not overstate the benefit.

| Impact area | Evidence in this prototype | What is not established |
|---|---|---|
| Social/access benefit | Priority-group rates and emergency service are measured; the controlled case serves one additional emergency request. | Whether the policy is acceptable or equitable to actual residents, employees, guests, or operators. |
| Electricity cost | Dashboard can estimate served-kWh cost when an operator supplies a tariff. | No verified local tariff or operating-cost study is supplied; no cost saving is claimed. |
| Environmental impact | Dashboard can estimate emissions from served kWh when an operator supplies a grid factor. | No verified site factor, lifecycle analysis, or emissions reduction is established. |
| Maintenance/operations burden | Prototype uses local Flask/SQLite and supports manual block/review operations. | Staff time, charger servicing, deployment, training, and integration burden have not been measured. |
| Unintended consequences | Priority rules may disadvantage lower-priority groups; overrides and group rates are visible. | Synthetic tests cannot determine real policy bias or long-term distributional effects. |

## 5. Verification

Run the automated suite from the `ev-faircharge` project directory:

```powershell
python -m unittest discover -s tests -v
```

**Latest verification:** 23 tests passed. Python syntax compilation passed for the changed backend and test modules. Tests use temporary SQLite databases rather than the local project database. The README now documents the API surface and database tables; detailed test coverage and API error boundaries are in [testing-and-errors.md](./testing-and-errors.md).

The suite covers scheduler outcomes and edge cases, metrics, CSV idempotency, request validation, reviewer authorization and audit, site settings, and stakeholder-feedback storage.

## 6. Live demo sequence

From the `ev-faircharge` project directory in PowerShell:

```powershell
python -m pip install -r requirements.txt
python backend/database.py
python backend/models.py
$env:FAIRCHARGE_REVIEWERS_JSON = '{"Jaishree":"replace-with-a-local-demo-key"}'
python backend/app.py
```

Open `http://127.0.0.1:5000`.

1. On **Requests**, load the sample CSV and show the 20 requests.
2. On **Schedule**, run both schedules and compare the results and metrics.
3. Explain that the bundled sample ties, then describe the separate controlled contention result and its waiting-time trade-off.
4. On **Human review**, show the flagged queue and explain that changes require reviewer authorization and an audit reason.
5. Do not enter estimated tariff or emissions factors unless a reliable local source is available.

Use a unique local demo key and do not commit real reviewer credentials.

## 7. Stakeholder validation — still to do

This is the remaining real-world evidence task. The feedback form is implemented, but validation is not complete until real participants try the prototype. Do not fill this section with invented observations.

**Suggested short session (about 10 minutes per participant):**

1. Invite an apartment/workplace EV user or operator; explain that this is a prototype and ask permission to record their feedback.
2. Ask them to find a request, compare the two schedules, and explain one served or unserved result.
3. Ask whether the displayed priority order seems acceptable and what important constraint is missing.
4. Record the actual stakeholder role, date, task outcome, ratings, confusion points, and requested changes in **Human review → Stakeholder sessions**.
5. Summarize only observed feedback below. If no participant is available before submission, state that validation is pending.

| Session | Participant role | Date | Task outcome | Main observed feedback |
|---|---|---|---|---|
| Not conducted yet | — | — | — | Do not report results until a real session occurs. |

## 8. Limitations and next steps

- The workload is a small synthetic dataset; the controlled contention result is not representative site evidence.
- Actual stakeholder sessions and site-approved transformer, tariff, and emissions inputs have not been supplied.
- Live charger/OCPP integration, production accounts, deployment hardening, billing, multi-day calendars, and electrical/charger telemetry validation are outside this student prototype's implemented scope.
- Before operational deployment, validate site limits with a qualified operator, test with representative data and users, and replace prototype reviewer-token controls with an appropriate production identity and security design.

**Review 3 conclusion:** the prototype, tests, and synthetic evaluation are ready to present. User validation and production deployment are not complete and are explicitly identified as follow-up work.
