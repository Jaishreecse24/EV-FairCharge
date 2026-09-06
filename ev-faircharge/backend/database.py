"""
database.py
------------
This file is responsible for ONE thing only: setting up the SQLite database
for the EV FairCharge project.

What it does when you run it:
1. Creates a file called `faircharge.db` (if it doesn't already exist).
2. Creates all 5 tables required by the project (chargers, requests,
   schedule_fcfs, schedule_faircharge, overrides).
3. Seeds (inserts) the two starting chargers so we have something to
   schedule against later.

We are NOT writing any scheduling logic here. This file's only job is to
prepare the database so that later steps (CSV loading, FCFS algorithm,
FairCharge algorithm, Flask routes) have a database to work with.

Beginner note: SQLite stores the whole database in a single file
(faircharge.db). No separate database server needs to be installed or
running — Python's built-in `sqlite3` module talks to that file directly.
"""

import sqlite3
import os

# ---------------------------------------------------------------------------
# PROJECT-WIDE CONSTANTS
# ---------------------------------------------------------------------------
# SLOT_MINUTES defines how finely we divide time when scheduling.
# We decided on 15-minute slots (like an exam timetable grid) so that
# scheduling becomes a simple "which 15-minute boxes are free?" problem
# instead of dealing with messy continuous time.
# This constant will be imported later by the FCFS and FairCharge algorithms.
SLOT_MINUTES = 15

# The database file will live in the same folder as this script
# (backend/faircharge.db), regardless of where you run the script from.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "faircharge.db")


def get_connection():
    """
    Opens and returns a connection to the SQLite database file.
    Every other file (models.py, app.py, algorithms) will reuse this
    function so that we always connect to the same faircharge.db file
    in the same way.
    """
    conn = sqlite3.connect(DB_PATH)
    # This makes query results behave like dictionaries (access by column
    # name) instead of plain tuples (access by index). Much easier to read.
    conn.row_factory = sqlite3.Row
    # Enforce foreign key constraints (SQLite has this OFF by default).
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_tables(conn):
    """
    Creates all 5 tables if they do not already exist.
    Using "CREATE TABLE IF NOT EXISTS" means it is safe to run this
    function multiple times without wiping or duplicating data.
    """
    cursor = conn.cursor()

    # -----------------------------------------------------------------
    # Table 1: chargers
    # Represents a physical charging location (e.g. "Apartment Block A").
    # capacity_kw_per_port = charging speed of ONE connector.
    # num_ports = how many EVs can charge at that location AT THE SAME TIME.
    # -----------------------------------------------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chargers (
            charger_id INTEGER PRIMARY KEY,
            location TEXT NOT NULL,
            capacity_kw_per_port REAL NOT NULL,
            num_ports INTEGER NOT NULL
        )
    """)

    # -----------------------------------------------------------------
    # Table 2: requests
    # One row = one EV asking to be charged. This table is filled by
    # importing our sample CSV dataset in a later step.
    # -----------------------------------------------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS requests (
            request_id INTEGER PRIMARY KEY,
            ev_user TEXT NOT NULL,
            arrival_time TEXT NOT NULL,
            departure_time TEXT NOT NULL,
            energy_required_kwh REAL NOT NULL,
            priority_policy TEXT NOT NULL,
            charger_id INTEGER NOT NULL,
            FOREIGN KEY (charger_id) REFERENCES chargers (charger_id)
        )
    """)

    # -----------------------------------------------------------------
    # Table 3: schedule_fcfs
    # Stores the output of the baseline FCFS (First-Come-First-Served)
    # algorithm. One row per request, after the algorithm has run.
    # 'reason' explains WHY a request was marked unserved (e.g.
    # "departure too close" or "insufficient capacity") — this is what
    # lets us clearly demonstrate the 3 required edge cases.
    # -----------------------------------------------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS schedule_fcfs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id INTEGER,
            assigned_slot_start TEXT,
            assigned_slot_end TEXT,
            status TEXT,
            wait_time_min REAL,
            reason TEXT,
            FOREIGN KEY (request_id) REFERENCES requests (request_id)
        )
    """)

    # -----------------------------------------------------------------
    # Table 4: schedule_faircharge
    # Same idea as schedule_fcfs, but for our FairCharge algorithm.
    # Extra columns:
    #   fairness_weight_used -> the priority weight applied to this
    #                           request when scheduling (e.g. resident=70)
    #   overridden            -> 1 if an admin manually changed this
    #                           decision later, 0 otherwise
    #   needs_review          -> 1 if this decision was auto-flagged for
    #                           human review (high-impact / unserved
    #                           resident or emergency request)
    # -----------------------------------------------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS schedule_faircharge (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id INTEGER,
            assigned_slot_start TEXT,
            assigned_slot_end TEXT,
            status TEXT,
            wait_time_min REAL,
            reason TEXT,
            fairness_weight_used REAL,
            overridden INTEGER DEFAULT 0,
            needs_review INTEGER DEFAULT 0,
            FOREIGN KEY (request_id) REFERENCES requests (request_id)
        )
    """)

    # -----------------------------------------------------------------
    # Table 5: overrides
    # A log of every manual admin decision made through the human-review
    # step. This is what proves "human review for high-impact decisions"
    # actually exists in the system, not just on paper.
    # -----------------------------------------------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS overrides (
            override_id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id INTEGER,
            original_decision TEXT,
            new_decision TEXT,
            reason TEXT,
            admin_name TEXT,
            timestamp TEXT,
            FOREIGN KEY (request_id) REFERENCES requests (request_id)
        )
    """)

    conn.commit()
    print("All 5 tables created (or already existed).")


def seed_chargers(conn):
    """
    Inserts the two starting chargers described in the project design:
      1 -> Apartment Block A, 7 kW per port, 1 port
      2 -> Workplace Lot 1,    7 kW per port, 2 ports

    We check first whether chargers already exist, so that running this
    script twice does NOT create duplicate rows or crash on a primary
    key conflict.
    """
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) AS total FROM chargers")
    existing_count = cursor.fetchone()["total"]

    if existing_count > 0:
        print(f"Chargers table already has {existing_count} row(s) — skipping seed.")
        return

    chargers_to_insert = [
        (1, "Apartment Block A", 7.0, 1),
        (2, "Workplace Lot 1", 7.0, 2),
    ]

    cursor.executemany("""
        INSERT INTO chargers (charger_id, location, capacity_kw_per_port, num_ports)
        VALUES (?, ?, ?, ?)
    """, chargers_to_insert)

    conn.commit()
    print(f"Seeded {len(chargers_to_insert)} chargers.")


def initialize_database():
    """
    Main entry point: opens a connection, creates tables, seeds chargers,
    then closes the connection. This is the function that runs when you
    execute this file directly.
    """
    print(f"Using database file: {DB_PATH}")
    conn = get_connection()
    try:
        create_tables(conn)
        seed_chargers(conn)
    finally:
        conn.close()
    print("Database initialization complete.")


# This block only runs when you execute `python database.py` directly.
# It will NOT run if this file is imported by another file (like app.py) —
# that is standard Python practice so that importing a module doesn't
# accidentally trigger side effects.
if __name__ == "__main__":
    initialize_database()
