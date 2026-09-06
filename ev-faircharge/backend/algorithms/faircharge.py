"""
faircharge.py
-------------
This file implements our OWN algorithm: FairCharge.

FairCharge solves the same problem as fcfs.py (assign EVs to free
charger ports, inside their arrival->departure window), but instead of
processing requests strictly by arrival time, it processes HIGHER
PRIORITY requests first (emergency > resident > employee > guest).

Important design decision (agreed in the design review):
    FairCharge does NOT "bump" or reschedule a request that has already
    been assigned. Fairness is achieved purely through PROCESSING ORDER:
    because high-priority requests are placed into the schedule before
    low-priority ones, they naturally get first pick of free slots.
    This keeps the algorithm simple, deterministic, and easy to explain
    on paper - there is no cascading reassignment logic to reason about.

This file does NOT touch the frontend, Flask routes, or metrics.
Its only job is: read from `requests` + `chargers`, compute a
priority-aware schedule, and save it into `schedule_faircharge`.
"""

import os
import sys
import math

# --------------------------------------------------------------------
# Import database.py from the parent folder (backend/), same trick
# used in fcfs.py, since this file lives in backend/algorithms/.
# --------------------------------------------------------------------
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BACKEND_DIR)

from database import get_connection, SLOT_MINUTES  # noqa: E402


# ======================================================================
# PRIORITY WEIGHTS (soft constraint - decided in the design review)
# ======================================================================
# Higher weight = processed earlier = better chance of getting a slot.
# This dictionary is the ONLY thing that makes FairCharge different
# from FCFS in terms of ordering logic.
PRIORITY_WEIGHTS = {
    "emergency": 100,
    "resident": 70,
    "employee": 50,
    "guest": 20,
}


# ======================================================================
# SMALL HELPER FUNCTIONS (identical logic to fcfs.py, kept local to
# this file so faircharge.py can be read/graded on its own without
# needing to cross-reference fcfs.py)
# ======================================================================

def time_to_minutes(time_str):
    """Converts "HH:MM" into minutes since midnight, e.g. "08:30" -> 510."""
    hours, minutes = map(int, time_str.split(":"))
    return hours * 60 + minutes


def minutes_to_time(total_minutes):
    """Converts minutes-since-midnight back into a "HH:MM" string."""
    hours = total_minutes // 60
    minutes = total_minutes % 60
    return f"{hours:02d}:{minutes:02d}"


def minutes_to_slot(total_minutes):
    """Converts minutes-since-midnight into a 15-minute slot number."""
    return total_minutes // SLOT_MINUTES


def slot_to_minutes(slot_number):
    """Converts a slot number back into minutes-since-midnight."""
    return slot_number * SLOT_MINUTES


def calculate_duration_slots(energy_required_kwh, capacity_kw_per_port):
    """
    duration_minutes = (energy_required_kwh / capacity_kw_per_port) * 60
    Rounded UP to the nearest whole 15-minute slot - identical formula
    and rounding rule as FCFS, so both algorithms are compared fairly
    on the same physical assumptions.
    """
    duration_minutes = (energy_required_kwh / capacity_kw_per_port) * 60
    duration_slots = math.ceil(duration_minutes / SLOT_MINUTES)
    return duration_slots


# ======================================================================
# LOADING DATA FROM THE DATABASE
# ======================================================================

def get_all_chargers(conn):
    """Loads every charger into a dict keyed by charger_id (same as FCFS)."""
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM chargers")
    chargers = {}
    for row in cursor.fetchall():
        chargers[row["charger_id"]] = {
            "location": row["location"],
            "capacity_kw_per_port": row["capacity_kw_per_port"],
            "num_ports": row["num_ports"],
        }
    return chargers


def get_requests_faircharge_order(conn):
    """
    Loads every request, sorted EXACTLY as required for FairCharge:
        1. priority_weight DESCENDING (emergency first, guest last)
        2. arrival_time ASCENDING     (earlier arrival wins ties)
        3. request_id ASCENDING       (final tie-breaker, for 100%
           determinism - two requests with identical priority AND
           identical arrival_time will always be ordered the same way)

    SQLite doesn't know about our PRIORITY_WEIGHTS dictionary, so we
    use a CASE expression to translate priority_policy into a number
    directly inside the SQL query, then sort by that number.
    """
    cursor = conn.cursor()
    cursor.execute("""
        SELECT *,
            CASE priority_policy
                WHEN 'emergency' THEN 100
                WHEN 'resident'  THEN 70
                WHEN 'employee'  THEN 50
                WHEN 'guest'     THEN 20
                ELSE 0
            END AS priority_weight
        FROM requests
        ORDER BY priority_weight DESC, arrival_time ASC, request_id ASC
    """)
    return cursor.fetchall()


# ======================================================================
# THE CORE FAIRCHARGE ALGORITHM
# ======================================================================

def run_faircharge():
    """
    Runs the full FairCharge algorithm and returns a list of result
    dictionaries (one per request), in the order they were PROCESSED
    (i.e. priority order) - this list also doubles as our "processing
    order" printout in the test block below.
    """
    conn = get_connection()
    chargers = get_all_chargers(conn)
    requests = get_requests_faircharge_order(conn)
    conn.close()

    # Same port-occupancy tracking idea as FCFS: one set of booked slot
    # numbers per port, per charger. Starts empty.
    occupied_slots = {}
    for charger_id, info in chargers.items():
        occupied_slots[charger_id] = [set() for _ in range(info["num_ports"])]

    results = []

    for req in requests:
        request_id = req["request_id"]
        charger_id = req["charger_id"]
        priority_policy = req["priority_policy"]
        priority_weight = PRIORITY_WEIGHTS.get(priority_policy, 0)
        charger = chargers[charger_id]

        arrival_minutes = time_to_minutes(req["arrival_time"])
        departure_minutes = time_to_minutes(req["departure_time"])

        arrival_slot = minutes_to_slot(arrival_minutes)
        departure_slot = minutes_to_slot(departure_minutes)
        window_slots = departure_slot - arrival_slot

        duration_slots = calculate_duration_slots(
            req["energy_required_kwh"],
            charger["capacity_kw_per_port"]
        )

        # ----------------------------------------------------------
        # HARD CONSTRAINT CHECK #1: physically impossible regardless
        # of priority. Even "emergency" cannot override physics - if
        # the charging duration doesn't fit in the window, no amount
        # of priority weight can fix that. This is intentional and is
        # exactly what request 7 (emergency) is designed to prove.
        # ----------------------------------------------------------
        if duration_slots > window_slots:
            needs_review = 1 if priority_policy in ("resident", "emergency") else 0
            results.append({
                "request_id": request_id,
                "priority_policy": priority_policy,
                "status": "UNSERVED",
                "assigned_slot_start": None,
                "assigned_slot_end": None,
                "wait_time_min": None,
                "reason": "departure too close",
                "fairness_weight_used": priority_weight,
                "needs_review": needs_review,
            })
            continue

        # ----------------------------------------------------------
        # HARD CONSTRAINT CHECK #2: find a free contiguous block.
        # Identical scanning logic to FCFS (ports in order, earliest
        # free block per port) - the ONLY difference from FCFS is the
        # ORDER in which requests reach this point (priority first).
        # No bumping: whatever is already booked stays booked.
        # ----------------------------------------------------------
        assigned_port_index = None
        assigned_start_slot = None

        num_ports = charger["num_ports"]
        last_possible_start = departure_slot - duration_slots  # inclusive

        for port_index in range(num_ports):
            port_busy_slots = occupied_slots[charger_id][port_index]

            for candidate_start in range(arrival_slot, last_possible_start + 1):
                candidate_block = range(candidate_start, candidate_start + duration_slots)

                block_is_free = all(
                    slot not in port_busy_slots for slot in candidate_block
                )

                if block_is_free:
                    assigned_port_index = port_index
                    assigned_start_slot = candidate_start
                    break  # earliest block found on this port - stop scanning

            if assigned_start_slot is not None:
                break  # a port worked - stop trying further ports

        if assigned_start_slot is None:
            needs_review = 1 if priority_policy in ("resident", "emergency") else 0
            results.append({
                "request_id": request_id,
                "priority_policy": priority_policy,
                "status": "UNSERVED",
                "assigned_slot_start": None,
                "assigned_slot_end": None,
                "wait_time_min": None,
                "reason": "insufficient capacity",
                "fairness_weight_used": priority_weight,
                "needs_review": needs_review,
            })
            continue

        # ----------------------------------------------------------
        # A valid block was found - book it and record SERVED.
        # SERVED requests are never flagged for review: needs_review
        # only applies to UNSERVED resident/emergency requests, as
        # per the design (that is the "high-impact decision" case).
        # ----------------------------------------------------------
        assigned_end_slot = assigned_start_slot + duration_slots
        for slot in range(assigned_start_slot, assigned_end_slot):
            occupied_slots[charger_id][assigned_port_index].add(slot)

        wait_time_min = slot_to_minutes(assigned_start_slot) - arrival_minutes

        results.append({
            "request_id": request_id,
            "priority_policy": priority_policy,
            "status": "SERVED",
            "assigned_slot_start": minutes_to_time(slot_to_minutes(assigned_start_slot)),
            "assigned_slot_end": minutes_to_time(slot_to_minutes(assigned_end_slot)),
            "wait_time_min": wait_time_min,
            "reason": None,
            "fairness_weight_used": priority_weight,
            "needs_review": 0,
        })

    return results


# ======================================================================
# SAVING RESULTS TO THE DATABASE (safe to re-run)
# ======================================================================

def save_faircharge_results(results):
    """
    Saves FairCharge results into `schedule_faircharge`.

    Same safety rule as FCFS: DELETE all existing rows first, then
    insert the fresh results. Running this file twice in a row always
    REPLACES the previous schedule instead of duplicating it.

    `overridden` is always saved as 0 here - it only becomes 1 later,
    in a future step, when an admin manually changes a decision through
    the (not-yet-built) override feature.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM schedule_faircharge")

    for r in results:
        cursor.execute("""
            INSERT INTO schedule_faircharge (
                request_id, assigned_slot_start, assigned_slot_end,
                status, wait_time_min, reason,
                fairness_weight_used, overridden, needs_review
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
        """, (
            r["request_id"],
            r["assigned_slot_start"],
            r["assigned_slot_end"],
            r["status"],
            r["wait_time_min"],
            r["reason"],
            r["fairness_weight_used"],
            r["needs_review"],
        ))

    conn.commit()
    conn.close()


# ======================================================================
# RUNNABLE TEST - lets you run `python algorithms/faircharge.py` directly
# ======================================================================

if __name__ == "__main__":
    print("Running FairCharge algorithm...\n")

    results = run_faircharge()
    save_faircharge_results(results)

    # ------------------------------------------------------------------
    # First: show the PROCESSING ORDER (priority order), so it's easy
    # to see, at a glance, that this is NOT arrival-time order like
    # FCFS. This is requirement #16.
    # ------------------------------------------------------------------
    print("Processing order (priority_weight DESC, arrival ASC, id ASC):")
    order_ids = [str(r["request_id"]) for r in results]
    print("  " + " -> ".join(order_ids))
    print()

    # ------------------------------------------------------------------
    # Now print the results table, sorted by request_id for easy
    # side-by-side comparison against the FCFS printout from Step 5.
    # ------------------------------------------------------------------
    results_by_id = sorted(results, key=lambda r: r["request_id"])

    header = (f"{'ID':>3} {'PRIORITY':10} {'STATUS':9} {'START':6} {'END':6} "
              f"{'WAIT':6} {'WEIGHT':6} {'REVIEW':6} REASON")
    print(header)
    print("-" * len(header))
    for r in results_by_id:
        start = r["assigned_slot_start"] or "-"
        end = r["assigned_slot_end"] or "-"
        wait = r["wait_time_min"] if r["wait_time_min"] is not None else "-"
        reason = r["reason"] or "-"
        print(
            f"{r['request_id']:>3} {r['priority_policy']:10} {r['status']:9} "
            f"{start:6} {end:6} {str(wait):6} {r['fairness_weight_used']:6} "
            f"{r['needs_review']:6} {reason}"
        )

    served_count = sum(1 for r in results if r["status"] == "SERVED")
    unserved_count = sum(1 for r in results if r["status"] == "UNSERVED")
    review_ids = [r["request_id"] for r in results if r["needs_review"] == 1]

    print("-" * len(header))
    print(f"Total SERVED:   {served_count}")
    print(f"Total UNSERVED: {unserved_count}")
    print(f"Needs review (needs_review=1): {review_ids}")

    # ------------------------------------------------------------------
    # Explicit verification of the required edge cases (requirements
    # #17 and #18). This confirms that priority does NOT override
    # physically impossible requests, and that capacity limits still
    # apply correctly under FairCharge too.
    # ------------------------------------------------------------------
    print("\nEdge case verification:")

    lookup = {r["request_id"]: r for r in results}

    def check(request_id, expected_status, expected_reason=None):
        r = lookup[request_id]
        ok = (r["status"] == expected_status and
              (expected_reason is None or r["reason"] == expected_reason))
        mark = "PASS" if ok else "FAIL"
        detail = (f"priority={r['priority_policy']}, status={r['status']}, "
                  f"reason={r['reason']}")
        print(f"  [{mark}] Request {request_id}: {detail}")

    check(6, "UNSERVED", "departure too close")
    check(7, "UNSERVED", "departure too close")  # emergency, still fails - hard constraint
    check(16, "UNSERVED", "insufficient capacity")
