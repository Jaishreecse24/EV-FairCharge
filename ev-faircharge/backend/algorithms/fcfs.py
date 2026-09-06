"""
fcfs.py
-------
This file implements the BASELINE scheduling algorithm: FCFS
(First-Come-First-Served).

What FCFS does, in plain English:
    - Look at all EV charging requests.
    - Process them in the order they arrived (earliest arrival_time first).
    - For each request, try to find it a free charging port for exactly
      as long as it needs, somewhere inside its arrival->departure window.
    - Give up (mark it "unserved") if that's not physically possible.

FCFS does NOT look at priority_policy at all. That is intentional - it's
supposed to be a "dumb but fair in the naive sense" baseline that our
FairCharge algorithm (Step 6) will later be compared against.

This file does NOT touch the frontend, Flask routes, or metrics.
Its only job is: read from `requests` + `chargers`, compute a schedule,
and save that schedule into the `schedule_fcfs` table.
"""

import os
import sys
import math

# --------------------------------------------------------------------
# Import database.py from the parent folder (backend/).
# This file lives in backend/algorithms/, so we need to tell Python to
# also look one folder up when importing.
# --------------------------------------------------------------------
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BACKEND_DIR)

from database import get_connection, SLOT_MINUTES  # noqa: E402


# ======================================================================
# SMALL HELPER FUNCTIONS (time <-> minutes <-> 15-minute slot numbers)
# ======================================================================

def time_to_minutes(time_str):
    """
    Converts a "HH:MM" string (e.g. "08:30") into minutes since
    midnight (e.g. 510). This makes time math (subtracting, comparing)
    simple integer arithmetic instead of string comparison.
    """
    hours, minutes = map(int, time_str.split(":"))
    return hours * 60 + minutes


def minutes_to_time(total_minutes):
    """
    Converts minutes-since-midnight back into a "HH:MM" string.
    This is the reverse of time_to_minutes(), used when we need to
    store/display the assigned slot times.
    """
    hours = total_minutes // 60
    minutes = total_minutes % 60
    return f"{hours:02d}:{minutes:02d}"


def minutes_to_slot(total_minutes):
    """
    Converts minutes-since-midnight into a "slot number".
    Since SLOT_MINUTES = 15, minute 0 is slot 0, minute 15 is slot 1,
    minute 480 (08:00) is slot 32, and so on.
    Working with slot numbers (plain integers) instead of raw minutes
    makes the "is this 15-minute block free?" checks very simple.
    """
    return total_minutes // SLOT_MINUTES


def slot_to_minutes(slot_number):
    """
    Reverse of minutes_to_slot(): turns a slot number back into
    minutes-since-midnight.
    """
    return slot_number * SLOT_MINUTES


def calculate_duration_slots(energy_required_kwh, capacity_kw_per_port):
    """
    Calculates how many 15-minute slots a request needs to fully charge,
    using the formula agreed in the design review:

        duration_minutes = (energy_required_kwh / capacity_kw_per_port) * 60

    We then ROUND UP to the nearest whole 15-minute slot, because a
    request that needs even 1 extra minute still occupies a full slot
    on the schedule grid (you can't have "half a slot" in this system).
    """
    duration_minutes = (energy_required_kwh / capacity_kw_per_port) * 60
    duration_slots = math.ceil(duration_minutes / SLOT_MINUTES)
    return duration_slots


# ======================================================================
# LOADING DATA FROM THE DATABASE
# ======================================================================

def get_all_chargers(conn):
    """
    Loads every charger into a plain Python dictionary keyed by
    charger_id, e.g.:
        {
            1: {"location": "Apartment Block A", "capacity_kw_per_port": 7.0, "num_ports": 1},
            2: {"location": "Workplace Lot 1",    "capacity_kw_per_port": 7.0, "num_ports": 2},
        }
    Using a dictionary means we can quickly look up "what does charger
    2 look like?" without hitting the database again for every request.
    """
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


def get_requests_fcfs_order(conn):
    """
    Loads every request from the `requests` table, sorted EXACTLY as
    required for FCFS:
        1. arrival_time ascending (earliest arrival goes first)
        2. request_id ascending (tie-breaker, so ordering never depends
           on database internals - always identical every run)

    This ORDER BY clause is what makes the whole algorithm deterministic.
    """
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM requests
        ORDER BY arrival_time ASC, request_id ASC
    """)
    return cursor.fetchall()


# ======================================================================
# THE CORE FCFS ALGORITHM
# ======================================================================

def run_fcfs():
    """
    Runs the full FCFS algorithm and returns a list of result
    dictionaries (one per request). Does NOT save to the database -
    saving is a separate step (see save_fcfs_results below) so that the
    algorithm logic and the database logic stay cleanly separated.
    """
    conn = get_connection()
    chargers = get_all_chargers(conn)
    requests = get_requests_fcfs_order(conn)
    conn.close()

    # ------------------------------------------------------------------
    # occupied_slots keeps track of which 15-minute slots are already
    # taken, PER PORT, PER CHARGER. Structure:
    #   occupied_slots[charger_id] = [set_for_port_1, set_for_port_2, ...]
    # Each set contains slot NUMBERS that are already booked on that port.
    # We start every port with an empty set (nothing booked yet).
    # ------------------------------------------------------------------
    occupied_slots = {}
    for charger_id, info in chargers.items():
        occupied_slots[charger_id] = [set() for _ in range(info["num_ports"])]

    results = []

    for req in requests:
        request_id = req["request_id"]
        charger_id = req["charger_id"]
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

        # --------------------------------------------------------------
        # HARD CONSTRAINT CHECK #1: does the required charging duration
        # even fit inside the arrival->departure window, ignoring
        # capacity entirely? If not, this is physically impossible no
        # matter how many free ports exist - reason = "departure too close".
        # --------------------------------------------------------------
        if duration_slots > window_slots:
            results.append({
                "request_id": request_id,
                "status": "UNSERVED",
                "assigned_slot_start": None,
                "assigned_slot_end": None,
                "wait_time_min": None,
                "reason": "departure too close",
            })
            continue

        # --------------------------------------------------------------
        # HARD CONSTRAINT CHECK #2: try to find a free contiguous block
        # of `duration_slots` slots, within [arrival_slot, departure_slot],
        # on the requested charger.
        #
        # As specified: scan ports IN ORDER (port 1 first, then port 2,
        # etc). For each port, scan every possible start slot from
        # arrival_slot forward, and use the FIRST free block found on
        # that port. If a port has no valid block at all, move on to
        # the next port. If NO port has room, the request is unserved.
        # --------------------------------------------------------------
        assigned_port_index = None
        assigned_start_slot = None

        num_ports = charger["num_ports"]
        last_possible_start = departure_slot - duration_slots  # inclusive

        for port_index in range(num_ports):
            port_busy_slots = occupied_slots[charger_id][port_index]

            for candidate_start in range(arrival_slot, last_possible_start + 1):
                candidate_block = range(candidate_start, candidate_start + duration_slots)

                # Check every slot in this candidate block is free on this port.
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
            # No port, at any start time within the window, had a free block.
            results.append({
                "request_id": request_id,
                "status": "UNSERVED",
                "assigned_slot_start": None,
                "assigned_slot_end": None,
                "wait_time_min": None,
                "reason": "insufficient capacity",
            })
            continue

        # --------------------------------------------------------------
        # A valid block was found - book it (mark those slots as busy on
        # that specific port) and record the SERVED result.
        # --------------------------------------------------------------
        assigned_end_slot = assigned_start_slot + duration_slots
        for slot in range(assigned_start_slot, assigned_end_slot):
            occupied_slots[charger_id][assigned_port_index].add(slot)

        wait_time_min = slot_to_minutes(assigned_start_slot) - arrival_minutes

        results.append({
            "request_id": request_id,
            "status": "SERVED",
            "assigned_slot_start": minutes_to_time(slot_to_minutes(assigned_start_slot)),
            "assigned_slot_end": minutes_to_time(slot_to_minutes(assigned_end_slot)),
            "wait_time_min": wait_time_min,
            "reason": None,
        })

    return results


# ======================================================================
# SAVING RESULTS TO THE DATABASE (safe to re-run)
# ======================================================================

def save_fcfs_results(results):
    """
    Saves the FCFS results into the `schedule_fcfs` table.

    To make this SAFE TO RE-RUN (requirement #9), we first DELETE all
    existing rows in schedule_fcfs, then insert the fresh results.
    This means running fcfs.py twice in a row will always REPLACE the
    old schedule with a newly recalculated one - never duplicate it.
    """
    conn = get_connection()
    cursor = conn.cursor()

    # Clear out any previous FCFS run's results first.
    cursor.execute("DELETE FROM schedule_fcfs")

    for r in results:
        cursor.execute("""
            INSERT INTO schedule_fcfs (
                request_id, assigned_slot_start, assigned_slot_end,
                status, wait_time_min, reason
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, (
            r["request_id"],
            r["assigned_slot_start"],
            r["assigned_slot_end"],
            r["status"],
            r["wait_time_min"],
            r["reason"],
        ))

    conn.commit()
    conn.close()


# ======================================================================
# RUNNABLE TEST - lets you run `python algorithms/fcfs.py` directly
# ======================================================================

if __name__ == "__main__":
    print("Running FCFS baseline algorithm...\n")

    results = run_fcfs()
    save_fcfs_results(results)

    # Print one line per request, sorted by request_id for easy reading.
    results_by_id = sorted(results, key=lambda r: r["request_id"])

    print(f"{'ID':>3} {'STATUS':9} {'START':6} {'END':6} {'WAIT(min)':10} REASON")
    print("-" * 60)
    for r in results_by_id:
        start = r["assigned_slot_start"] or "-"
        end = r["assigned_slot_end"] or "-"
        wait = r["wait_time_min"] if r["wait_time_min"] is not None else "-"
        reason = r["reason"] or "-"
        print(f"{r['request_id']:>3} {r['status']:9} {start:6} {end:6} {str(wait):10} {reason}")

    served_count = sum(1 for r in results if r["status"] == "SERVED")
    unserved_count = sum(1 for r in results if r["status"] == "UNSERVED")

    print("-" * 60)
    print(f"Total SERVED:   {served_count}")
    print(f"Total UNSERVED: {unserved_count}")

    # ------------------------------------------------------------------
    # Explicit verification of the required edge cases (requirement #12).
    # This does not affect the schedule - it's just a readable check so
    # you can confirm, at a glance, that the known edge cases behaved
    # exactly as designed.
    # ------------------------------------------------------------------
    print("\nEdge case verification:")

    lookup = {r["request_id"]: r for r in results}

    def check(request_id, expected_status, expected_reason=None):
        r = lookup[request_id]
        ok = (r["status"] == expected_status and
              (expected_reason is None or r["reason"] == expected_reason))
        mark = "PASS" if ok else "FAIL"
        detail = f"status={r['status']}, reason={r['reason']}"
        print(f"  [{mark}] Request {request_id}: {detail}")

    check(6, "UNSERVED", "departure too close")
    check(7, "UNSERVED", "departure too close")
    check(16, "UNSERVED", "insufficient capacity")

    # Charger 1 has 1 port -> at no point should more than 1 request be
    # "active" on charger 1 at the same time. We just visually confirm
    # via the printed schedule above (requests 3, 4, 5 compete for the
    # single port; only one of them can be SERVED at a time).
    print("  Charger 1 (1 port) and Charger 2 (2 ports) limits are")
    print("  enforced by the port-occupancy logic - see SERVED rows")
    print("  above to confirm no port is double-booked.")
