# EV FairCharge: Requirements and Evaluation

## Scope and requirements

The prototype serves a shared apartment/workplace charging pool. Each request records user, arrival and departure times, optional departure flexibility, required kWh, priority policy, and charger. Charger records provide kW per port, number of ports, and availability. The site has a configurable shared transformer cap, seeded at 14 kW.

Hard constraints are explicit in both schedulers: charging must fit within the request's departure window plus any explicitly opted-in flexibility; assignments use contiguous 15-minute slots; each port can serve only one request per slot; aggregate charging power cannot exceed the site transformer cap; unavailable chargers cannot serve requests; and outage/overstay/maintenance/grid-curtailment blocks reserve affected ports. An emergency label cannot bypass these physical limits. Soft policy is the FairCharge processing order: emergency, resident, employee, then guest, with arrival time and request ID as deterministic tie-breakers. Optional departure flexibility is bounded to 0-60 minutes in 15-minute increments and is used only when needed. FCFS is the arrival-time baseline.

The Flask API and web screens provide request viewing/import, schedule comparison, metrics, and review. Named reviewers can use distinct server-configured tokens from `FAIRCHARGE_REVIEWERS_JSON`. An authorized reviewer can change a request's priority policy; FairCharge is recomputed and the decision is recorded with reviewer, reason, prior decision/policy, and timestamp. The override changes a soft policy classification; it does not bypass hard feasibility constraints. The older shared `FAIRCHARGE_ADMIN_TOKEN` remains a compatibility fallback.

### Requirements specification

| ID | Requirement | Acceptance evidence |
|---|---|---|
| FR-1 | Store requests with arrival/departure, optional flex, energy, priority, and charger; store charger kW/port, port count, availability, and site cap. | SQLite schema/migration, site configuration API, and 20-row CSV dataset. |
| FR-2 | Produce deterministic FCFS and priority-aware schedules using explicit physical constraints. | 15-minute slots, transformer cap, socket limits, outages/blocks, deadlines, and distinct failure reasons. |
| FR-3 | Compare throughput, wait, kWh fulfilled/unserved, deadline miss rate, Jain fairness, access by priority, and optional cost/emissions. | `/api/metrics` and Schedule screen; impact estimates remain unset until local factors are entered. |
| FR-4 | Flag unserved emergency/resident requests for human review. | `needs_review` and the Human review screen. |
| FR-5 | Let an authorized reviewer change a request's priority and recompute FairCharge. | Server-side shared token, reviewer/reason/timestamp audit record, schedule rerun. |
| FR-6 | Record charger outages, overstays, and grid/maintenance blocks; change the transformer cap. | Token-protected `/api/charger-blocks` and `/api/site/transformer-limit` endpoints recompute both schedules. |
| FR-7 | Allow a small, explicit, optional departure-time preference. | Request API/CSV support 0-60-minute flexibility in 15-minute increments; extensions are labelled in schedule results. |
| FR-8 | Capture short user/operator validation sessions. | Protected feedback form stores role, date, task completion, ratings, confusion, and requested changes. |
| NFR-1 | Make outcomes explainable and repeatable. | Explicit reasons, documented weights/tie-breaks, deterministic regression tests. |
| NFR-2 | Prevent a priority override from violating physical constraints. | Recomputed scheduler still enforces window, port, and slot constraints. |

### Prototype screens

- **Requests (`/`)**: sample CSV import, live request list, headline service metrics.
- **Schedule (`/dashboard.html`)**: run both schedulers; compare slots, status, waits, served kWh, and review flags.
- **Human review (`/admin.html`)**: inspect flagged decisions, enter reviewer identity/key/reason, change priority, and inspect protected audit history.
- **Validation and site factors (`/admin.html`)**: configure operator-provided tariff/grid factors and record real stakeholder sessions.

## Experiment

**Dataset:** Bundled synthetic CSV with 20 requests, two chargers (7 kW per port; one port and two ports), four priority policies, departure windows, and energy needs totaling 89.25 kWh. The seeded site transformer cap is 14 kW. The experiment runs in a temporary SQLite database using the same scheduling and metrics code as the app.

**Objectives:** FCFS is the throughput/arrival-order baseline. FairCharge tests priority-based social access. Reported outcomes are requests served, kWh fulfilled/unserved, average wait among served requests, priority-group service rates, Jain's fairness index over those group service rates, and deadline-miss rate (unserved requests or assignments later than allowed departure).

**Target:** FairCharge should serve at least one more emergency/resident request than FCFS without reducing total service; use 10 minutes as an absolute average-wait guardrail and report any wait increase. These are project evaluation targets, not stakeholder-approved service-level guarantees.

| Measure | FCFS baseline | FairCharge result | Target / outcome |
|---|---:|---:|---|
| Requests served | 13 / 20 (65%) | 13 / 20 (65%) | Report measured baseline; equal |
| Required energy | 89.25 kWh | 89.25 kWh | Same request set |
| Energy fulfilled / unserved | 57.75 / 31.50 kWh (64.71%) | 57.75 / 31.50 kWh (64.71%) | No reduction; met |
| Average wait among served | 4.62 min | 4.62 min | Compare to baseline; equal |
| Jain fairness index | 0.9835 | 0.9835 | Report group access; no gain |
| Deadline misses | 7 / 20 (35.00%) | 7 / 20 (35.00%) | Compare to baseline; equal |
| Emergency requests served | 1 / 2 | 1 / 2 | Improve by at least one; not met |
| Resident requests served | 5 / 7 | 5 / 7 | No regression; equal |
| Employee requests served | 4 / 6 | 4 / 6 | Reported for error analysis |
| Guest requests served | 3 / 5 | 3 / 5 | Reported for error analysis |

FairCharge changes processing order, but this bundled dataset produces the same served set, energy result, Jain index, and wait result as FCFS. The priority-improvement target is **not achieved** on this dataset. The stricter transformer cap reduces both algorithms' service compared with earlier, uncapped experiment numbers; all figures in this report use the 14 kW cap.

### Controlled contention case

To check whether the policy can change access when priorities actually conflict, the automated experiment adds two requests on the one-port charger: guest request 21 (16:00-18:15, 7 kWh) and emergency request 22 (16:15-17:15, 7 kWh). FCFS schedules the guest first and cannot fit the emergency request before departure. FairCharge schedules the emergency first and then fits the guest before its later departure.

| Measure | FCFS | FairCharge | Result |
|---|---:|---:|---|
| Requests served | 14 / 22 | 15 / 22 | FairCharge +1 |
| Energy fulfilled / unserved | 64.75 / 38.50 kWh (62.71%) | 71.75 / 31.50 kWh (69.49%) | FairCharge +7 kWh |
| Emergency requests served | 1 / 3 | 2 / 3 | FairCharge +1 |
| Jain fairness index | 0.9384 | 0.9991 | FairCharge +0.0607 |
| Deadline miss rate | 36.36% | 31.82% | FairCharge -4.54 points |
| Average wait among served | 4.29 min | 9.00 min | FairCharge +4.71 min |

The controlled case meets the priority-access target and stays below the 10-minute wait guardrail, but makes the wait-time trade-off visible. It is a deliberately constructed contention scenario, not evidence of typical real-site performance.

## Edge and failure cases

Automated tests cover the following cases against an isolated database:

- Requests 6 (resident) and 7 (emergency) need more charging time than their departure windows permit. Both are marked `departure too close`; FairCharge flags them for human review without violating feasibility.
- Requests 4, 5, and 16 cannot obtain a contiguous slot because of charger capacity conflicts. They are marked `insufficient capacity`.
- Simultaneous 7 kW loads on three ports exceed the 14 kW site transformer cap; the third request is marked `transformer capacity exceeded`.
- Setting charger 1 unavailable makes its requests unserved with `charger unavailable`.
- An authorized 16:00-16:15 overstay block reserves charger 1's port; a request in that interval is marked `charger blocked: overstay`.
- A request with 15 minutes of opted-in flexibility can use a later slot and records the flexibility used; invalid 10-minute increments are rejected by the API.
- Loading the sample CSV a second time inserts zero duplicate requests and reports all 20 existing IDs as skipped.
- Reviewer history access without a valid token is rejected; invalid policy overrides are rejected. Authorized outage blocks and transformer-cap changes reschedule both algorithms.

Run the tests with `python -m unittest discover -s tests -v` from the project directory.

## Cost, benefit, and unintended consequences

- **Potential social benefit:** explicit priority rules make allocation explainable and auditable; high-impact emergency/resident outcomes are reviewable. This dataset did not show better priority-group service rates than FCFS.
- **Environmental benefit:** estimated grid emissions are computed only when the operator supplies a local kg CO2e/kWh factor. Delivered kWh alone is not an emissions measure; no default grid mix or renewable share is assumed.
- **Cost and maintenance:** estimated electricity cost uses only an operator-supplied tariff. The prototype uses Flask and SQLite, but real operating cost, deployment operations, charger integration, maintenance burden, and staff time remain unmeasured.
- **Unintended consequences:** fixed priority classes can encode policy bias; a high-priority queue may disadvantage guests; individual environment-configured tokens improve attribution but do not provide enterprise account lifecycle controls; and manual overrides affect later allocations. The 15-minute model ignores charging curves, connector compatibility, real-time arrivals, and energy losses.

## Stakeholder validation

Stakeholder validation has **not yet been conducted**. The app now has a protected form to record real sessions, but do not report validation as complete until apartment/workplace users or an operator have tried the prototype. Suggested short session: ask at least one operator and two EV users to review the rules and dashboard, then record their role, date, task completion, ratings, confusion points, and requested changes.

Questions to ask:

1. Can you explain why a request was served or left unserved from the displayed result?
2. Does the priority ordering match an acceptable apartment/workplace policy? Who should approve changes?
3. Is a human review flag useful, and what evidence should a reviewer see before changing a request's priority?
4. Which missing real-world constraint could make this schedule unsafe or unfair?

Record actual observations and changes here before final submission; no user feedback is assumed in this report.

## Limitations and next experiment

The sample contains only 20 synthetic requests and two chargers; there is no statistical or real-site validation. Average wait is calculated only for served requests, so it does not represent delay for unserved users. Priority-classification rates should be reported alongside aggregate service and energy metrics. The experiment found no FairCharge service advantage; tune neither weights nor claims to imply otherwise. A next experiment should add larger, varied contention scenarios where priority ordering can affect who is served, compare multiple seeds, and include a fairness measure such as group service-rate gaps. Validate the revised policy with stakeholders before deployment.
