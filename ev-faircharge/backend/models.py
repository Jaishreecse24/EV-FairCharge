"""
models.py
---------
This file contains simple "data access" functions - code that reads or
writes to the database on behalf of the rest of the project.

For Step 3, its only job is:
    - Read the sample dataset (data/ev_requests.csv)
    - Insert each row into the `requests` table
    - Skip any row whose request_id already exists in the table, so that
      running the loader twice does NOT create duplicates or crash.

We are NOT writing any scheduling logic (FCFS / FairCharge) here yet -
that comes in later steps. This file only gets data INTO the database.
"""

import csv
import os
from database import get_connection

# Path to the sample CSV dataset, relative to this file's location.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(BASE_DIR, "data", "ev_requests.csv")


def request_id_exists(conn, request_id):
    """
    Checks whether a given request_id is already present in the
    `requests` table. Returns True/False.

    This is what makes our CSV loading "duplicate-safe" - before
    inserting any row, we check if it's already there.
    """
    cursor = conn.cursor()
    cursor.execute(
        "SELECT 1 FROM requests WHERE request_id = ?",
        (request_id,)
    )
    return cursor.fetchone() is not None


def load_requests_from_csv(csv_path=CSV_PATH):
    """
    Reads the CSV file at csv_path and inserts each row into the
    `requests` table.

    Duplicate-safety rule:
        If a request_id from the CSV already exists in the database,
        that row is SKIPPED (not inserted again, not overwritten).
        This means you can run this function as many times as you want
        and it will never create duplicate or conflicting rows.

    Returns a small summary dictionary so the caller (or the script
    below) can print out what happened.
    """
    conn = get_connection()
    cursor = conn.cursor()

    inserted_count = 0
    skipped_count = 0
    skipped_ids = []

    with open(csv_path, newline="") as csv_file:
        reader = csv.DictReader(csv_file)

        for row in reader:
            request_id = int(row["request_id"])

            # --- Duplicate check ---
            if request_id_exists(conn, request_id):
                skipped_count += 1
                skipped_ids.append(request_id)
                continue

            # --- Insert this row ---
            cursor.execute("""
                INSERT INTO requests (
                    request_id,
                    ev_user,
                    arrival_time,
                    departure_time,
                    energy_required_kwh,
                    priority_policy,
                    charger_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                request_id,
                row["ev_user"],
                row["arrival_time"],
                row["departure_time"],
                float(row["energy_required_kwh"]),
                row["priority_policy"],
                int(row["charger_id"]),
            ))
            inserted_count += 1

    conn.commit()
    conn.close()

    return {
        "inserted_count": inserted_count,
        "skipped_count": skipped_count,
        "skipped_ids": skipped_ids,
    }


def get_all_requests():
    """
    Returns every row currently in the `requests` table, as a list of
    dictionary-like rows. Useful later for the Flask API and for
    quickly checking what was loaded.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM requests ORDER BY request_id")
    rows = cursor.fetchall()
    conn.close()
    return rows


# This block runs only when you execute `python models.py` directly.
# It loads the CSV and prints a clear summary - this is how you will
# actually load the dataset into the database for this step.
if __name__ == "__main__":
    print(f"Loading requests from: {CSV_PATH}")
    summary = load_requests_from_csv()

    print(f"Inserted: {summary['inserted_count']} new request(s).")
    print(f"Skipped (already existed): {summary['skipped_count']} request(s).")
    if summary["skipped_ids"]:
        print(f"Skipped IDs: {summary['skipped_ids']}")

    print("\nCurrent contents of the requests table:")
    for row in get_all_requests():
        print(
            f"  id={row['request_id']:2} "
            f"user={row['ev_user']:12} "
            f"{row['arrival_time']}-{row['departure_time']} "
            f"energy={row['energy_required_kwh']:>5} kWh "
            f"priority={row['priority_policy']:9} "
            f"charger={row['charger_id']}"
        )
