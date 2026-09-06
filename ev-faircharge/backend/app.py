import os
import sqlite3
from datetime import datetime, timezone

from flask import Flask, jsonify, request, send_from_directory

from database import get_connection
from models import get_all_requests, load_requests_from_csv
from algorithms.fcfs import run_fcfs, save_fcfs_results
from algorithms.faircharge import run_faircharge, save_faircharge_results


BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(os.path.dirname(BACKEND_DIR), "frontend")

app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="")


def row_to_dict(row):
	return dict(row)


def json_error(message, status_code=400):
	return jsonify({"error": message}), status_code


def get_json_body():
	body = request.get_json(silent=True)
	if not isinstance(body, dict):
		raise ValueError("Request body must be a JSON object")
	return body


def validate_time(value, field_name):
	if not isinstance(value, str):
		raise ValueError(f"{field_name} must be a time in HH:MM format")
	try:
		datetime.strptime(value, "%H:%M")
	except ValueError as exc:
		raise ValueError(f"{field_name} must be a time in HH:MM format") from exc
	return value


def validate_request_payload(body):
	required = (
		"request_id",
		"ev_user",
		"arrival_time",
		"departure_time",
		"energy_required_kwh",
		"priority_policy",
		"charger_id",
	)
	missing = [field for field in required if field not in body]
	if missing:
		raise ValueError(f"Missing required field(s): {', '.join(missing)}")

	try:
		request_id = int(body["request_id"])
		charger_id = int(body["charger_id"])
		energy_required_kwh = float(body["energy_required_kwh"])
	except (TypeError, ValueError) as exc:
		raise ValueError("request_id, charger_id, and energy_required_kwh must be numeric") from exc

	if request_id <= 0 or charger_id <= 0:
		raise ValueError("request_id and charger_id must be positive")
	if energy_required_kwh <= 0:
		raise ValueError("energy_required_kwh must be greater than zero")

	ev_user = body["ev_user"]
	priority_policy = body["priority_policy"]
	if not isinstance(ev_user, str) or not ev_user.strip():
		raise ValueError("ev_user must be a non-empty string")
	if priority_policy not in {"emergency", "resident", "employee", "guest"}:
		raise ValueError("priority_policy must be emergency, resident, employee, or guest")

	arrival_time = validate_time(body["arrival_time"], "arrival_time")
	departure_time = validate_time(body["departure_time"], "departure_time")
	if departure_time <= arrival_time:
		raise ValueError("departure_time must be later than arrival_time")

	return (
		request_id,
		ev_user.strip(),
		arrival_time,
		departure_time,
		energy_required_kwh,
		priority_policy,
		charger_id,
	)


def read_schedule(table_name):
	if table_name == "schedule_fcfs":
		order = "request_id ASC"
	else:
		order = "request_id ASC"

	conn = get_connection()
	try:
		rows = conn.execute(f"SELECT * FROM {table_name} ORDER BY {order}").fetchall()
		return [row_to_dict(row) for row in rows]
	finally:
		conn.close()


def schedule_summary(rows):
	served = [row for row in rows if row["status"] == "SERVED"]
	waits = [row["wait_time_min"] for row in served if row["wait_time_min"] is not None]
	return {
		"total_requests": len(rows),
		"served": len(served),
		"unserved": len(rows) - len(served),
		"average_wait_time_min": round(sum(waits) / len(waits), 2) if waits else 0,
	}


@app.after_request
def add_cors_headers(response):
	response.headers["Access-Control-Allow-Origin"] = "*"
	response.headers["Access-Control-Allow-Headers"] = "Content-Type"
	response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
	return response


@app.route("/", methods=["GET"])
def index():
	return send_from_directory(FRONTEND_DIR, "index.html")


@app.route("/api/health", methods=["GET"])
def health():
	conn = get_connection()
	try:
		conn.execute("SELECT 1")
	finally:
		conn.close()
	return jsonify({"status": "ok", "service": "EV FairCharge API"})


@app.route("/api/requests", methods=["GET", "POST"])
def requests_endpoint():
	if request.method == "GET":
		return jsonify([row_to_dict(row) for row in get_all_requests()])

	try:
		values = validate_request_payload(get_json_body())
	except ValueError as exc:
		return json_error(str(exc))

	conn = get_connection()
	try:
		charger = conn.execute(
			"SELECT 1 FROM chargers WHERE charger_id = ?", (values[-1],)
		).fetchone()
		if charger is None:
			return json_error("charger_id does not exist", 400)
		conn.execute(
			"""
			INSERT INTO requests (
				request_id, ev_user, arrival_time, departure_time,
				energy_required_kwh, priority_policy, charger_id
			) VALUES (?, ?, ?, ?, ?, ?, ?)
			""",
			values,
		)
		conn.commit()
	except sqlite3.IntegrityError:
		return json_error("request_id already exists", 409)
	finally:
		conn.close()

	return jsonify({"message": "Request created", "request": dict(zip(
		("request_id", "ev_user", "arrival_time", "departure_time",
		 "energy_required_kwh", "priority_policy", "charger_id"), values
	))}), 201


@app.route("/api/schedule/fcfs", methods=["GET", "POST"])
def fcfs_schedule():
	if request.method == "POST":
		results = run_fcfs()
		save_fcfs_results(results)
	rows = read_schedule("schedule_fcfs")
	return jsonify({"algorithm": "fcfs", "summary": schedule_summary(rows), "schedule": rows})


@app.route("/api/schedule/faircharge", methods=["GET", "POST"])
def faircharge_schedule():
	if request.method == "POST":
		results = run_faircharge()
		save_faircharge_results(results)
	rows = read_schedule("schedule_faircharge")
	return jsonify({"algorithm": "faircharge", "summary": schedule_summary(rows), "schedule": rows})


@app.route("/api/metrics", methods=["GET"])
def metrics():
	fcfs_rows = read_schedule("schedule_fcfs")
	faircharge_rows = read_schedule("schedule_faircharge")
	return jsonify({
		"fcfs": schedule_summary(fcfs_rows),
		"faircharge": schedule_summary(faircharge_rows),
		"comparison": {
			"served_difference": schedule_summary(faircharge_rows)["served"] - schedule_summary(fcfs_rows)["served"],
			"average_wait_difference_min": round(
				schedule_summary(faircharge_rows)["average_wait_time_min"] -
				schedule_summary(fcfs_rows)["average_wait_time_min"], 2
			),
		},
	})


@app.route("/api/override", methods=["POST"])
def override():
	try:
		body = get_json_body()
		request_id = int(body["request_id"])
		new_decision = body["new_decision"]
		reason = body["reason"]
		admin_name = body["admin_name"]
	except (KeyError, TypeError, ValueError):
		return json_error("request_id, new_decision, reason, and admin_name are required")

	if not isinstance(new_decision, str) or not new_decision.strip():
		return json_error("new_decision must be a non-empty string")
	if not isinstance(reason, str) or not reason.strip():
		return json_error("reason must be a non-empty string")
	if not isinstance(admin_name, str) or not admin_name.strip():
		return json_error("admin_name must be a non-empty string")

	conn = get_connection()
	try:
		schedule = conn.execute(
			"SELECT * FROM schedule_faircharge WHERE request_id = ? ORDER BY id DESC LIMIT 1",
			(request_id,),
		).fetchone()
		if schedule is None:
			return json_error("No FairCharge schedule exists for request_id", 404)

		original_decision = schedule["status"]
		timestamp = datetime.now(timezone.utc).isoformat()
		conn.execute(
			"""
			INSERT INTO overrides (
				request_id, original_decision, new_decision,
				reason, admin_name, timestamp
			) VALUES (?, ?, ?, ?, ?, ?)
			""",
			(request_id, original_decision, new_decision.strip(), reason.strip(), admin_name.strip(), timestamp),
		)
		conn.execute(
			"UPDATE schedule_faircharge SET overridden = 1 WHERE id = ?",
			(schedule["id"],),
		)
		conn.commit()
	finally:
		conn.close()

	return jsonify({"message": "Override recorded", "request_id": request_id}), 201


@app.route("/api/load-csv", methods=["POST"])
def load_csv():
	try:
		summary = load_requests_from_csv()
	except (OSError, ValueError, sqlite3.Error) as exc:
		return json_error(f"Could not load CSV: {exc}", 500)
	return jsonify(summary)


@app.errorhandler(404)
def handle_not_found(error):
	return json_error("Endpoint not found", 404)


@app.errorhandler(405)
def handle_method_not_allowed(error):
	return json_error("Method not allowed", 405)


@app.errorhandler(400)
def handle_bad_request(error):
	return json_error("Bad request", 400)


if __name__ == "__main__":
	app.run(debug=True)
