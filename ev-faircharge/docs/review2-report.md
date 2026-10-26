# EV FairCharge — Review 2 Report

**Project:** Transparent shared EV-charging scheduler for apartments and workplaces

**Review milestone:** Review 2

**Report date:** 2 October 2026
**Status:** Working end-to-end prototype; real stakeholder validation remains pending

**Prepared by:** Jaishree

**Audience:** Review 2 evaluator and project stakeholders

**Evidence basis:** Application source, bundled synthetic dataset, isolated automated tests, and live local prototype
**Version:** 1.1

> **Submission note:** Replace or complete institutional details if the course template requires them. This report distinguishes measured prototype results from proposed targets and pending real-world validation.

## 1. Executive Summary

EV FairCharge compares a First-Come-First-Served (FCFS) baseline with a priority-aware scheduler. It stores requests and charger/site constraints in SQLite, exposes Flask APIs, and provides Requests, Schedule, and Human Review screens.

Review 1 asked for explicit hard/soft constraints, authorized human override, failure cases, and direct fairness metrics. Those implementation changes are present with automated regression coverage. The bundled 20-request dataset does not show a FairCharge advantage over FCFS; a separate constructed contention test shows improved emergency access, with a measurable increase in average wait. These results are reported as measured, not as a claim that the policy always improves fairness.

### Problem framing

Apartment and workplace charging pools have a fixed number of charging ports and a finite electrical supply. When multiple vehicles request service for overlapping periods, an operator must decide which vehicles receive energy before they depart. A basic arrival-order policy is easy to explain, but it can leave a high-priority vehicle without service during a conflict. A priority policy can address that concern, but it also introduces questions about fairness, transparency, policy bias, and whether a human should review high-impact decisions.

The project turns that operational problem into a working shared-charging scheduler. Its central question is:

> Under the same port, transformer, time-window, and energy constraints, how does priority-aware scheduling change service access compared with FCFS, and what waiting-time trade-offs does it create?

The project does not assume that every high-priority request can be served. Physical feasibility remains a hard constraint; priority is a soft ordering preference among feasible requests.

### Stakeholders and needs

| Stakeholder | Need represented in the prototype | Evidence or boundary |
|---|---|---|
| EV user | Understand whether a request was served, when, and why it was rejected. | Request and schedule tables expose status, assigned times, and reason. |
| Apartment/workplace operator | Coordinate access to limited ports and site power. | Site transformer limit, charger availability, event blocks, and CSV ingestion. |
| High-priority requester | Have an explicit policy preference and a review path for impactful denial. | Emergency/resident review flags and authorized priority override. |
| Reviewer/admin | Make an attributable decision and explain it later. | Per-reviewer key option, required reason, timestamped audit record. |
| Evaluator | Compare baseline and proposed objective with repeatable evidence. | Isolated dataset tests, metrics, and controlled contention experiment. |

Stakeholder needs above are design assumptions, not interview findings. Actual user validation is pending.

### Objectives, success criteria, and scope

The prototype has four evaluation objectives:

1. Preserve physical feasibility under overlapping requests, port capacity, charger outages/blocks, and a shared transformer limit.
2. Compare FCFS throughput and waiting time with FairCharge's priority-group access.
3. Report requested/served/unserved energy, Jain fairness across priority-group service rates, and deadline misses.
4. Allow an authorized human to review high-impact decisions and record real stakeholder-session feedback.

The controlled contention success criterion is at least one additional emergency request served without reducing total service, while keeping the average wait under the project's 10-minute guardrail. The bundled dataset is evaluated separately and does **not** meet the emergency-improvement target.

**In scope:** one-day time-of-day scheduling in 15-minute slots; CSV/REST request ingestion; two deterministic schedulers; site power limit; port availability and time-bounded blocks; human review; dashboard and audit trail.

**Out of scope:** live charger/OCPP integration, battery/charging curves, multi-day calendars, renewable/real-time grid feeds, individual production identity management, billing settlement, and statistical validation on real operator data.

## 2. Review 1 Feedback and Response

| Review 1 request | Review 2 response | Evidence/status |
|---|---|---|
| Explicit hard limits, including transformer and socket capacity | Added a shared 14 kW site transformer limit; both schedulers enforce it in addition to per-port occupancy. | Peak-cap test rejects a third simultaneous 7 kW load. The 14 kW default is illustrative and should be replaced with the site's actual limit. |
| Soft preference and minor departure flexibility | Priority ordering is emergency, resident, employee, guest. Requests may opt into 0–60 minutes of flexibility in 15-minute increments. | API validates increments; schedule reason records when flexibility is used. |
| Human review and authorized override | Unserved emergency/resident requests are flagged. A named reviewer can change priority; FairCharge then recomputes and writes an audit record. | Distinct reviewer keys supported through `FAIRCHARGE_REVIEWERS_JSON`; wrong reviewer-name/token pairing is rejected. |
| At least three failure/edge cases | Added deadline impossibility, socket capacity conflict, transformer peak, charger outage, and overstay-block cases. | Covered in automated tests below. |
| Jain fairness, unserved kWh, deadline-miss rate | Added metrics to `/api/metrics` and the Schedule dashboard, alongside served energy and wait time. | Measures shown separately for FCFS and FairCharge. |
| Environmental/cost trade-off | Added optional operator tariff and grid-emissions inputs; estimated costs/emissions appear only after factors are supplied. | No local factors are configured in the sample run; no values are invented. |
| Short stakeholder validation | Added a protected form and audit list for session role/date, task result, ratings, confusion points, and requested changes. | The form is implemented; actual user/operator sessions are still pending and must not be claimed complete. |

## 3. System and Rules

### Data and prototype screens

- **Requests:** SQLite-backed request list and repeat-safe sample CSV import.
- **Schedule:** run FCFS and FairCharge; compare assignments, reasons, served kWh, unserved energy, Jain index, deadline misses, wait, and transformer cap.
- **Human Review:** flagged queue, reviewer identity/key, reason, priority override, audit history, site impact factors, and stakeholder-session records.

Request data includes arrival/departure time, energy need, priority, charger, and optional departure flexibility. Charger data includes per-port kW, socket count, and availability. Site settings include transformer capacity and optional tariff/emissions factors.

### Hard and soft constraints

**Hard constraints:** a request must fit the available charging window; each connector serves at most one vehicle in a 15-minute slot; a schedule must not exceed the site transformer limit; unavailable chargers cannot serve requests; and time-bounded outage/overstay/maintenance/grid-curtailment blocks reserve their affected ports. Priority cannot override these physical constraints.

**Soft rules:** FairCharge processes emergency, resident, employee, then guest requests, with arrival time and request ID as deterministic tie-breakers. A request may explicitly permit a bounded departure extension. FCFS remains the arrival-order baseline.

### Authorized review

Set individual reviewer credentials in the server environment, for example:

```powershell
$env:FAIRCHARGE_REVIEWERS_JSON = '{"Reviewer One":"unique-local-key-one","Reviewer Two":"unique-local-key-two"}'
python backend/app.py
```

Reviewer identity is matched to the configured key and recorded with the old decision/policy, new policy, reason, and timestamp. The legacy shared `FAIRCHARGE_ADMIN_TOKEN` is retained only as a compatibility fallback. These environment-configured keys are prototype controls, not full production identity management with expiry/revocation.

### Architecture and component responsibilities

| Component | Responsibility | Implementation |
|---|---|---|
| Browser frontend | Request list, schedule comparison, review queue, site-factor inputs, session feedback form. | Static HTML, CSS, and JavaScript served by Flask. |
| Flask application | Validate requests, expose REST endpoints, calculate summaries, enforce reviewer authorization. | `backend/app.py`. |
| Scheduling layer | Build deterministic FCFS and FairCharge schedules using the same physical constraints. | `backend/algorithms/fcfs.py` and `backend/algorithms/faircharge.py`. |
| Data-access layer | Import the CSV, query request records, open SQLite connections. | `backend/models.py` and `backend/database.py`. |
| Local persistence | Store inputs, site settings, blocks, schedules, overrides, and feedback. | `backend/faircharge.db`; additive initialization migrations preserve existing request rows. |
| Evaluation layer | Compare metrics and preserve repeatable behavior with regressions. | `/api/metrics` and `tests/test_scheduler.py`. |

The flow is: request/CSV input → validation and SQLite persistence → FCFS and FairCharge computation → persisted schedule rows → API summaries → dashboard comparison. Human review updates the request's soft priority policy, records an audit row, and reruns FairCharge. Site power changes and time-bounded charger blocks trigger both schedules to be recalculated.

### Data model summary

| Entity | Important fields | Why it is needed |
|---|---|---|
| `requests` | ID, user, arrival/departure, flexibility, energy kWh, priority, charger ID | Defines each charging need and its allowable time window. |
| `chargers` | Location, kW/port, number of ports, availability | Defines connector capacity and outage state. |
| `site_limits` | Transformer kW, optional tariff, optional kg CO2e/kWh | Defines the shared site cap and operator-supplied impact factors. |
| `charger_blocks` | Charger, start/end, ports blocked, event reason | Represents overstay, outage, maintenance, and grid-curtailment intervals. |
| `schedule_fcfs` / `schedule_faircharge` | Request, assigned slot, status, wait, reason | Stores competing algorithm outputs for comparison. |
| `overrides` | Original/new decision, reason, reviewer, timestamp | Makes priority changes attributable and auditable. |
| `stakeholder_feedback` | Role/date, task completion, ratings, notes, interviewer | Captures real validation sessions without assuming they occurred. |

### Formal scheduling rules

The model uses a 15-minute slot size. For energy need $E$ kWh and port rate $P$ kW, the required duration is rounded up:

$$
N_{slots} = \left\lceil \frac{E}{P \cdot (15/60)} \right\rceil
$$

An assignment is feasible only if its end is no later than the request's departure plus explicitly opted-in flexibility, the selected port is free for every slot, the charger is available, and site power stays within the transformer limit for every slot:

$$
\sum_{p \in active\ ports(t)} P_p \leq P_{transformer}
$$

The power check uses each active port's rated kW as a conservative slot-level load. It is not a dynamic electrical simulation and does not model tapering charging curves. Unavailable chargers and time-bounded blocks reserve ports but do not consume transformer power. A hard-constraint failure is returned as a reason such as `departure too close`, `insufficient capacity`, `transformer capacity exceeded`, `charger unavailable`, or `charger blocked: overstay`.

FairCharge uses configured relative weights (emergency 100, resident 70, employee 50, guest 20), then arrival time and request ID for deterministic ordering. The numeric values define order only; they are not empirically calibrated utilities or probabilities. FCFS ignores priority and orders by arrival time then request ID.

### API contract overview

| Endpoint | Access | Function |
|---|---|---|
| `GET /api/health` | Public | Check service/database connectivity. |
| `GET|POST /api/requests` | Public prototype API | List/create validated requests; creation accepts optional departure flexibility. |
| `POST /api/load-csv` | Public prototype API | Repeat-safe bundled sample import. |
| `GET|POST /api/schedule/fcfs` | Public prototype API | Read saved FCFS or compute and persist a fresh baseline. |
| `GET|POST /api/schedule/faircharge` | Public prototype API | Read saved FairCharge or compute and persist a fresh priority schedule. |
| `GET /api/metrics` | Public prototype API | Compare service, energy, fairness, deadlines, waits, and configured impact estimates. |
| `GET /api/site` | Public prototype API | Read transformer, chargers, blocks, and configured impact factors. |
| `POST /api/override` | Reviewer credential required | Change priority, audit the decision, and recompute FairCharge. |
| `GET /api/overrides` | Reviewer credential required | Read the override audit trail. |
| `POST /api/site/transformer-limit` | Reviewer credential required | Change site cap and recompute both schedules. |
| `POST /api/charger-blocks` | Reviewer credential required | Add a bounded operational block and recompute schedules. |
| `POST /api/site/impact-factors` | Reviewer credential required | Configure or clear tariff/carbon factors. |
| `GET|POST /api/stakeholder-feedback` | Reviewer credential required | Record and retrieve actual validation sessions. |

This is a student prototype API, not a public production service. In particular, request-ingestion endpoints and CORS policy would need deployment-specific access controls before external exposure.

### End-to-end data flow and API surface

1. `POST /api/load-csv` imports the bundled request records. Duplicate request IDs are skipped, allowing a repeatable demo without duplicate data.
2. `GET /api/requests` supplies request records to the Requests and Schedule screens. `POST /api/requests` accepts validated new requests, including optional departure flexibility.
3. `POST /api/schedule/fcfs` and `POST /api/schedule/faircharge` calculate and persist schedules. Their `GET` forms return the saved results.
4. `GET /api/metrics` summarizes both saved schedules and the comparison dashboard reads those results.
5. Reviewers use `POST /api/override` to update a request's priority policy and trigger a FairCharge rerun. `GET /api/overrides` returns the audit trail to an authenticated reviewer.
6. `GET /api/site` shows site settings. Authorized `POST /api/site/transformer-limit`, `POST /api/site/impact-factors`, and `POST /api/charger-blocks` update operational assumptions and recompute schedules where relevant.
7. Authorized `GET|POST /api/stakeholder-feedback` stores actual validation session observations. No session is present until a real session is submitted.

The browser UI calls these same Flask routes; there is no separate notebook-only implementation. SQLite is local to the backend and stores requests, schedules, site constraints, blocks, override history, and stakeholder session records. Database initialization applies additive migrations and preserves existing request data.

### Metric definitions

- **Served requests:** count of schedule rows with status `SERVED`; the service rate is served / total requests.
- **Energy served / unserved:** sum of requested kWh for served requests, and total requested kWh minus served kWh. The prototype assumes a served request receives its full requested energy.
- **Jain fairness index:** calculate each priority group's service rate $r_i = served_i / requests_i$, then $J = (\sum r_i)^2 / (n\sum r_i^2)$. It ranges from $1/n$ to 1 for nonzero rates; 1 means equal group service rates, not necessarily adequate service for every group.
- **Deadline miss:** every unserved request counts as a miss; a served request also counts as a miss if its slot ends after departure plus its explicitly allowed flexibility. The rate is misses / total requests.
- **Average wait:** arithmetic mean of scheduled start minus request arrival for served requests only. It does not measure the experienced delay of unserved requests.
- **Estimated electricity cost:** served kWh multiplied by the site tariff entered by an operator. It is `null` until a tariff is configured.
- **Estimated grid emissions:** served kWh multiplied by the site carbon-intensity factor entered by an operator. It is `null` until a factor is configured and does not represent lifecycle emissions.

## 4. Experiment and Results

### Dataset and method

The bundled synthetic CSV contains 20 requests across two chargers, four priority classes, departure windows, and energy needs totaling 89.25 kWh. Each charger port is 7 kW; one charger has one port and the other has two. The sample site transformer cap is 14 kW. The experiments run the actual scheduling and metric code using an isolated temporary SQLite database.

**Primary objective:** meet more emergency/resident charging needs without reducing overall service. **Guardrail:** report the wait-time change; the project target is an average wait below 10 minutes in the controlled contention case. These are evaluation targets, not stakeholder-approved service levels.

### Experimental method and questions

The bundled experiment loads the same request rows and charger/site settings for each algorithm. FCFS processes by earliest arrival and request ID. FairCharge processes by priority weight, then arrival and request ID. Both use the same slot duration, port capacity, 14 kW transformer limit, availability state, and block events; only the request processing order differs. This makes the comparison focus on scheduling policy rather than different physical assumptions.

The test suite creates a temporary database per test, initializes the same schema, imports the bundled CSV, runs the real functions/API routes, and discards the temporary database afterward. The schedule is deterministic; this experiment does not use random sampling or claim statistical significance.

Evaluation questions:

1. Does either policy serve more requests or more requested kWh under the same physical limits?
2. Does FairCharge improve emergency/resident access in the main data and the explicitly identified contention case?
3. How much does service-priority ordering change average wait and deadline misses?
4. Do failure reasons remain transparent when constraints make a request infeasible?

The key measures are calculated as follows:

- Service rate = served requests / total requests.
- Energy fulfillment = served requested kWh / total requested kWh; unserved kWh = total requested kWh − served requested kWh.
- Priority-group rate $r_i$ = served requests in group $i$ / total requests in group $i$.
- Jain index $J = (\sum_i r_i)^2 / (n \sum_i r_i^2)$ for the $n$ priority groups present in the schedule.
- Deadline-miss rate = unserved requests plus served requests ending after the allowed deadline, divided by total requests.
- Average wait = mean(assigned start − arrival) among served requests only.

### Bundled sample result

| Metric | FCFS | FairCharge |
|---|---:|---:|
| Requests served | 13 / 20 (65%) | 13 / 20 (65%) |
| Energy required | 89.25 kWh | 89.25 kWh |
| Energy served / unserved | 57.75 / 31.50 kWh (64.71% fulfilled) | 57.75 / 31.50 kWh (64.71% fulfilled) |
| Average wait among served | 4.62 min | 4.62 min |
| Jain fairness index across priority-group service rates | 0.9835 | 0.9835 |
| Deadline misses | 7 / 20 (35.00%) | 7 / 20 (35.00%) |
| Emergency served | 1 / 2 | 1 / 2 |
| Resident served | 5 / 7 | 5 / 7 |
| Employee served | 4 / 6 | 4 / 6 |
| Guest served | 3 / 5 | 3 / 5 |

**Interpretation:** this bundled dataset produces the same served set and summary metrics for both algorithms. The target of improving priority-group access is not met on the bundled sample; priority ordering alone is not evidence of a fairness gain.

### Primary-dataset error analysis

Both algorithms reject the same seven requests under the 14 kW cap: requests 6 and 7 are infeasible within their departure windows; requests 4 and 5 have no contiguous free port slot; and requests 15, 16, and 18 exceed the transformer limit in the attempted windows. Accordingly, aggregate service, served energy, deadline misses, group service rates, and wait match in this dataset. This is a useful negative result: FairCharge reorders the search, but the available windows and site cap do not create a different feasible served set for this sample.

The group rates are resident 5/7 (0.7143), employee 4/6 (0.6667), guest 3/5 (0.6000), and emergency 1/2 (0.5000). Jain's 0.9835 indicates similar service rates across groups, but does not mean that all demand is met: 31.5 kWh remains unserved and seven of twenty requests miss their deadline under the report's definition.

### Controlled contention result

A reproducible stress case adds guest request 21 (16:00–18:15, 7 kWh) and emergency request 22 (16:15–17:15, 7 kWh) on the one-port charger. FCFS schedules the guest first and cannot fit the emergency request before its departure. FairCharge schedules the emergency first, then fits the guest before its later departure.

| Metric | FCFS | FairCharge | Change |
|---|---:|---:|---:|
| Requests served | 14 / 22 | 15 / 22 | +1 request |
| Energy served / unserved | 64.75 / 38.50 kWh | 71.75 / 31.50 kWh | +7 kWh served |
| Energy fulfillment | 62.71% | 69.49% | +6.78 percentage points |
| Emergency served | 1 / 3 | 2 / 3 | +1 emergency request |
| Jain fairness index | 0.9384 | 0.9991 | +0.0607 |
| Deadline-miss rate | 36.36% | 31.82% | -4.54 percentage points |
| Average wait among served | 4.29 min | 9.00 min | +4.71 min |

**Interpretation:** FairCharge improves emergency access in this deliberately constructed case and remains under the 10-minute guardrail, but increases average wait. The result illustrates a trade-off; it does not predict typical site performance.

In the controlled case, FairCharge gives the emergency request a feasible 16:15–17:15 slot, then places the later-departing guest from 17:15–18:15. That gives the guest a 75-minute wait. FCFS instead starts the guest at 16:00, after which the emergency request cannot fit before its 17:15 departure. The result supports the proposed priority mechanism for this conflict, while exposing the direct cost paid by the lower-priority request.

### Failure and edge cases

1. **Departure deadline impossible:** requests 6 and 7 need more charge time than their windows allow; FairCharge flags the resident/emergency outcomes for review but cannot bypass the deadline.
2. **Socket conflict:** requests 4 and 5 cannot obtain a contiguous slot on their requested charger.
3. **Transformer peak:** three concurrent 7 kW requests exceed the 14 kW transformer cap; the third request is rejected with `transformer capacity exceeded`.
4. **Charger outage:** marking charger 1 unavailable rejects its requests with `charger unavailable`.
5. **Vehicle overstay:** a time-bounded overstay block reserves a port and prevents another assignment during the block.
6. **Optional departure flexibility:** a 15-minute opt-in can enable a later slot and is recorded; unsupported increments such as 10 minutes are rejected.

The automated suite also checks CSV idempotency, authenticated configuration, named reviewer identity, audit persistence after rescheduling, and stakeholder feedback storage.

### Test coverage map

| Test area | What is verified |
|---|---|
| Baseline sample | Both schedulers return one result per request; expected served count and wait are stable under the transformer cap. |
| Hard constraints | Departure infeasibility, socket contention, transformer overload, unavailable charger, and overstay port reservation produce explicit outcomes. |
| Soft preference | Valid departure flexibility is honored and reported; unsupported increments are rejected by the request API. |
| Fairness and metrics | Primary and controlled contention results assert energy, Jain index, deadline misses, wait, and group service counts. |
| Human review | Missing credentials and invalid decisions are rejected; authorized reviewer identity must match the supplied token; overrides persist after rescheduling. |
| Evaluation inputs | Cost/emissions estimates use configured factors; stakeholder feedback is persisted and retrievable only with reviewer authorization. |
| Persistence | CSV loading is idempotent, and schema initialization is safe for an existing database. |

The test suite uses a temporary SQLite database for each test, so sample experiments do not overwrite the user's working database.

### Stakeholder validation protocol

The form supports recording a session, but the validation activity itself remains an outstanding human task. A short, honest pilot can be run as follows:

1. Invite one apartment/workplace charging operator and at least two EV users with different priority roles. Explain that the prototype is a student demo, not an operational allocation service.
2. Ask each participant to inspect a sample request and identify the status, assigned time or failure reason, and the reason for any human-review flag.
3. Show the FCFS and FairCharge comparison, including the controlled emergency/guest conflict. Ask whether the priority order is acceptable and what trade-off they notice.
4. Ask the operator to review the transformer cap, outage/overstay handling, and proposed tariff/carbon fields. Do not enter estimated local values unless the operator can source them.
5. Record role (not personal name unless separately consented), date, task outcome, explainability rating, policy-acceptance rating, confusion points, and requested changes using the protected form.
6. Summarize participant count, completion outcomes, themes, and resulting changes. Preserve dissenting views; do not convert a small convenience sample into a broad claim of fairness or user acceptance.

Suggested interview prompts:

- “Can you explain why this request was served or left unserved?”
- “Is this priority order acceptable for your setting? Which group might be disadvantaged?”
- “What would you expect a reviewer to consider before changing a request's priority?”
- “What real-world event or constraint is missing from this screen?”

No participant data is present in the sample database or this report. Do not populate the form with invented responses.

## 5. Cost, Environment, and Risks

- Electricity-cost estimate = served kWh × operator-provided tariff per kWh.
- Grid-emissions estimate = served kWh × operator-provided kg CO2e per kWh.
- The sample report does not contain site tariff or carbon-intensity inputs, so it reports neither as a real-world result. Configure them on Human Review only from an operator/source you can cite.
- Flask + SQLite keep the student prototype lightweight, but actual hosting, operational, maintenance, charger-integration, and staff-review costs were not measured.
- Fixed priority categories can encode policy bias or disadvantage guests. Overrides affect future FairCharge runs, so all changes require a stated reason and audit record.
- Prototype keys improve attribution but do not replace a production identity provider, secure key rotation, or role-based access control.

### Risk register

| Risk | Possible consequence | Current mitigation | Remaining action |
|---|---|---|---|
| Incorrect transformer cap | False rejection or unsafe over-allocation against the actual electrical limit. | Configurable authenticated site limit; cap is shown on dashboard. | Obtain and record the operator-approved site value before operational use. |
| Priority policy encodes bias | Some users may repeatedly receive lower access. | Visible weights/order, per-group rates, reviewer override, audit reason. | Co-design policy with affected users and monitor group rates over larger real datasets. |
| Shared/compromised credentials | Unauthorized priority changes or disclosure of review history. | Distinct environment-configured reviewer tokens and identity matching. | Use production identity, role controls, key rotation/revocation, HTTPS, and security review. |
| Synthetic/short dataset | Metrics may not generalize to actual demand. | Claims are limited; separate constructed stress case is labelled. | Validate over multiple real or representative demand periods and sites. |
| Incorrect tariff/carbon factor | Misleading cost/environment comparison. | Inputs are optional; estimates remain unset if missing. | Record factor, source, unit, and effective date before comparing impacts. |
| Simplified power model | Slot-level rated load may differ from charger draw or charging taper. | Explicit conservative port kW accounting and stated model limitation. | Validate assumptions against charger telemetry and electrical engineering review. |
| Misinterpreted fairness index | High aggregate equality can hide poor service for every group. | Show group rates and unserved kWh beside Jain index. | Review multiple fairness metrics and participant feedback; do not treat one index as a policy verdict. |

## 6. Verification and Remaining Work

**Automated verification:** `python -m unittest discover -s tests -v` — all 23 tests passed, including regression coverage for off-grid arrival handling and invalid numeric input. Python syntax compilation also succeeds. The existing project database was migrated without deleting request rows; the live dashboard was checked with the transformer-limited schedule and new metric cards.

**Still required before claiming full validation:**

1. Conduct the short session with real apartment/workplace EV users and an operator; enter only their actual observations in Human Review.
2. Obtain a source-backed local electricity tariff and grid-emissions factor; enter them if available, otherwise leave impact estimates unset.
3. For deployment beyond a local student demo, replace environment-token authentication with a production identity/access solution and verify privacy/security requirements.

The stakeholder validation form is ready, but feedback has not been collected. This report makes no claim that human validation, site economics, or emissions benefits have been proven.

## 7. Review Demo Procedure

1. From the project directory, install dependencies and apply database migrations with `python -m pip install -r requirements.txt` and `python backend/database.py`.
2. Configure named reviewer identities in the local process environment, then start the app using the commands shown in Section 3. Do not commit real reviewer keys.
3. Open Requests and load the sample CSV. Open Schedule and run both schedulers; discuss the served count, energy fulfilled/unserved, Jain index, deadline misses, and 14 kW cap.
4. Point out that the bundled dataset ties FCFS; then describe the separate controlled contention test and its wait-time trade-off rather than implying the sample improved fairness.
5. Open Human Review and explain the flagged infeasible high-impact requests. For an authorized operational demo, configure the named reviewer key and explain that a priority override cannot bypass physical limits.
6. Enter only source-backed site tariff/carbon factors. If these are unavailable, leave the inputs unset and explain that environmental/cost estimates are unavailable.
7. Conduct and record actual stakeholder sessions before presenting user-validation results. Until then, state validation is pending.
