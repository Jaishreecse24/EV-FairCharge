import hmac
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone

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


def configured_reviewer_name(token):
	reviewer_config = os.environ.get("FAIRCHARGE_REVIEWERS_JSON")
	if not reviewer_config or not isinstance(token, str):
		return None
	try:
		reviewers = json.loads(reviewer_config)
	except json.JSONDecodeError:
		return None
	for reviewer_name, expected in reviewers.items():
		if isinstance(expected, str) and hmac.compare_digest(
			token.encode("utf-8"), expected.encode("utf-8")
		):
			return reviewer_name
	return None


def review_authorization_error(token):
	reviewer_config = os.environ.get("FAIRCHARGE_REVIEWERS_JSON")
	if reviewer_config:
		try:
			reviewers = json.loads(reviewer_config)
		except json.JSONDecodeError:
			return json_error("Reviewer configuration is invalid", 503)
		if not isinstance(reviewers, dict) or not reviewers:
			return json_error("Reviewer configuration is invalid", 503)
		if isinstance(token, str) and any(
			isinstance(expected, str)
			and hmac.compare_digest(token.encode("utf-8"), expected.encode("utf-8"))
			for expected in reviewers.values()
		):
			return None
		return json_error("Valid reviewer access is required", 401)

	expected_token = os.environ.get("FAIRCHARGE_ADMIN_TOKEN")
	if not expected_token:
		return json_error("Review access is not configured on the server", 503)
	if not isinstance(token, str) or not hmac.compare_digest(
		token.encode("utf-8"), expected_token.encode("utf-8")
	):
		return json_error("Valid reviewer access is required", 401)
	return None


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
		departure_flexibility_min = int(body.get("departure_flexibility_min", 0))
		energy_required_kwh = float(body["energy_required_kwh"])
	except (TypeError, ValueError) as exc:
		raise ValueError("request_id, charger_id, and energy_required_kwh must be numeric") from exc

	if request_id <= 0 or charger_id <= 0:
		raise ValueError("request_id and charger_id must be positive")
	if departure_flexibility_min < 0 or departure_flexibility_min > 60 or departure_flexibility_min % 15:
		raise ValueError("departure_flexibility_min must be 0, 15, 30, 45, or 60")
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
		departure_flexibility_min,
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
	request_ids = [row["request_id"] for row in rows]
	conn = get_connection()
	try:
		request_data = {
			row["request_id"]: dict(row)
			for row in conn.execute(
				"SELECT request_id, energy_required_kwh, priority_policy, departure_time, departure_flexibility_min FROM requests"
			).fetchall()
		}
		site = conn.execute(
			"SELECT transformer_capacity_kw, electricity_cost_per_kwh, "
			"grid_emission_kg_per_kwh FROM site_limits WHERE limit_id = 1"
		).fetchone()
	finally:
		conn.close()
	energy_required = sum(request_data.get(request_id, {}).get("energy_required_kwh", 0) for request_id in request_ids)
	energy_served = sum(request_data.get(row["request_id"], {}).get("energy_required_kwh", 0) for row in served)
	priority_totals = {}
	for request_id in request_ids:
		request = request_data.get(request_id)
		if request:
			priority_totals.setdefault(request["priority_policy"], [0, 0])[0] += 1
	for row in served:
		request = request_data.get(row["request_id"])
		if request:
			priority_totals[request["priority_policy"]][1] += 1
	priority_rates = [served_count / total for total, served_count in priority_totals.values() if total]
	jain_index = (
		sum(priority_rates) ** 2 / (len(priority_rates) * sum(rate ** 2 for rate in priority_rates))
		if priority_rates and any(priority_rates)
		else 0
	)
	request_by_id = {row["request_id"]: row for row in rows}
	deadline_misses = 0
	for request_id in request_ids:
		row = request_by_id[request_id]
		request = request_data.get(request_id)
		if request is None or row["status"] != "SERVED":
			deadline_misses += 1
			continue
		allowed_deadline = datetime.strptime(request["departure_time"], "%H:%M") + timedelta(
			minutes=request["departure_flexibility_min"]
		)
		assigned_end = datetime.strptime(row["assigned_slot_end"], "%H:%M")
		if assigned_end > allowed_deadline:
			deadline_misses += 1
	cost_rate = site["electricity_cost_per_kwh"]
	emissions_rate = site["grid_emission_kg_per_kwh"]
	return {
		"total_requests": len(rows),
		"served": len(served),
		"unserved": len(rows) - len(served),
		"average_wait_time_min": round(sum(waits) / len(waits), 2) if waits else 0,
		"energy_required_kwh": round(energy_required, 2),
		"energy_served_kwh": round(energy_served, 2),
		"unserved_energy_kwh": round(energy_required - energy_served, 2),
		"energy_fulfillment_percent": round(energy_served / energy_required * 100, 2) if energy_required else 0,
		"jain_fairness_index": round(jain_index, 4),
		"deadline_miss_count": deadline_misses,
		"deadline_miss_rate_percent": round(deadline_misses / len(rows) * 100, 2) if rows else 0,
		"transformer_capacity_kw": site["transformer_capacity_kw"],
		"estimated_electricity_cost": round(energy_served * cost_rate, 2) if cost_rate is not None else None,
		"estimated_grid_emissions_kg": round(energy_served * emissions_rate, 3) if emissions_rate is not None else None,
		"priority_service_rates": {
			priority: round(served_count / total, 4)
			for priority, (total, served_count) in priority_totals.items()
		},
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
				request_id, ev_user, arrival_time, departure_time, departure_flexibility_min,
				energy_required_kwh, priority_policy, charger_id
			) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
			""",
			values,
		)
		conn.commit()
	except sqlite3.IntegrityError:
		return json_error("request_id already exists", 409)
	finally:
		conn.close()

	return jsonify({"message": "Request created", "request": dict(zip(
		("request_id", "ev_user", "arrival_time", "departure_time", "departure_flexibility_min",
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


def recompute_schedules():
	save_fcfs_results(run_fcfs())
	save_faircharge_results(run_faircharge())


@app.route("/api/site", methods=["GET"])
def site_configuration():
	conn = get_connection()
	try:
		limit = conn.execute(
			"SELECT transformer_capacity_kw, electricity_cost_per_kwh, "
			"grid_emission_kg_per_kwh FROM site_limits WHERE limit_id = 1"
		).fetchone()
		chargers = conn.execute("SELECT * FROM chargers ORDER BY charger_id").fetchall()
		blocks = conn.execute("SELECT * FROM charger_blocks ORDER BY start_time, block_id").fetchall()
		return jsonify({
			"transformer_capacity_kw": limit["transformer_capacity_kw"],
			"electricity_cost_per_kwh": limit["electricity_cost_per_kwh"],
			"grid_emission_kg_per_kwh": limit["grid_emission_kg_per_kwh"],
			"chargers": [row_to_dict(row) for row in chargers],
			"charger_blocks": [row_to_dict(row) for row in blocks],
		})
	finally:
		conn.close()


@app.route("/api/site/impact-factors", methods=["POST"])
def update_impact_factors():
	try:
		body = get_json_body()
		authorization_error = review_authorization_error(body.get("admin_token"))
		if authorization_error:
			return authorization_error
		cost_rate = body.get("electricity_cost_per_kwh")
		emissions_rate = body.get("grid_emission_kg_per_kwh")
		cost_rate = None if cost_rate is None else float(cost_rate)
		emissions_rate = None if emissions_rate is None else float(emissions_rate)
	except (TypeError, ValueError):
		return json_error("Impact factors must be non-negative numbers or null")
	if (cost_rate is not None and cost_rate < 0) or (emissions_rate is not None and emissions_rate < 0):
		return json_error("Impact factors must be non-negative numbers or null")
	conn = get_connection()
	try:
		conn.execute(
			"UPDATE site_limits SET electricity_cost_per_kwh = ?, grid_emission_kg_per_kwh = ? "
			"WHERE limit_id = 1",
			(cost_rate, emissions_rate),
		)
		conn.commit()
	finally:
		conn.close()
	return jsonify({
		"electricity_cost_per_kwh": cost_rate,
		"grid_emission_kg_per_kwh": emissions_rate,
		"message": "Impact factors saved; estimates use the configured site values",
	})


@app.route("/api/site/transformer-limit", methods=["POST"])
def update_transformer_limit():
	try:
		body = get_json_body()
		authorization_error = review_authorization_error(body.get("admin_token"))
		if authorization_error:
			return authorization_error
		capacity_kw = float(body["transformer_capacity_kw"])
	except (KeyError, TypeError, ValueError):
		return json_error("A positive transformer_capacity_kw is required")
	if capacity_kw <= 0:
		return json_error("transformer_capacity_kw must be greater than zero")
	conn = get_connection()
	try:
		conn.execute(
			"UPDATE site_limits SET transformer_capacity_kw = ? WHERE limit_id = 1",
			(capacity_kw,),
		)
		conn.commit()
	finally:
		conn.close()
	recompute_schedules()
	return jsonify({"transformer_capacity_kw": capacity_kw, "message": "Schedules recomputed"})


@app.route("/api/charger-blocks", methods=["POST"])
def create_charger_block():
	try:
		body = get_json_body()
		authorization_error = review_authorization_error(body.get("admin_token"))
		if authorization_error:
			return authorization_error
		charger_id = int(body["charger_id"])
		start_time = validate_time(body["start_time"], "start_time")
		end_time = validate_time(body["end_time"], "end_time")
		ports_blocked = int(body.get("ports_blocked", 1))
		reason = body["reason"]
	except (KeyError, TypeError, ValueError) as exc:
		return json_error(str(exc) or "charger_id, start_time, end_time, and reason are required")
	if end_time <= start_time:
		return json_error("end_time must be later than start_time")
	if reason not in {"outage", "overstay", "maintenance", "grid curtailment"}:
		return json_error("reason must be outage, overstay, maintenance, or grid curtailment")

	conn = get_connection()
	try:
		charger = conn.execute(
			"SELECT num_ports FROM chargers WHERE charger_id = ?", (charger_id,)
		).fetchone()
		if charger is None:
			return json_error("charger_id does not exist", 404)
		if ports_blocked < 1 or ports_blocked > charger["num_ports"]:
			return json_error("ports_blocked must be between 1 and this charger's port count")
		cursor = conn.execute(
			"INSERT INTO charger_blocks (charger_id, start_time, end_time, ports_blocked, reason) "
			"VALUES (?, ?, ?, ?, ?)",
			(charger_id, start_time, end_time, ports_blocked, reason),
		)
		block_id = cursor.lastrowid
		conn.commit()
	finally:
		conn.close()
	recompute_schedules()
	return jsonify({"block_id": block_id, "message": "Charger block recorded; schedules recomputed"}), 201


@app.route("/api/metrics", methods=["GET"])
def metrics():
	fcfs_rows = read_schedule("schedule_fcfs")
	faircharge_rows = read_schedule("schedule_faircharge")
	fcfs = schedule_summary(fcfs_rows)
	faircharge = schedule_summary(faircharge_rows)
	return jsonify({
		"fcfs": fcfs,
		"faircharge": faircharge,
		"comparison": {
			"served_difference": faircharge["served"] - fcfs["served"],
			"unserved_energy_difference_kwh": round(faircharge["unserved_energy_kwh"] - fcfs["unserved_energy_kwh"], 2),
			"jain_fairness_difference": round(faircharge["jain_fairness_index"] - fcfs["jain_fairness_index"], 4),
			"deadline_miss_rate_difference_percent": round(faircharge["deadline_miss_rate_percent"] - fcfs["deadline_miss_rate_percent"], 2),
			"average_wait_difference_min": round(
				faircharge["average_wait_time_min"] - fcfs["average_wait_time_min"], 2
			),
		},
	})


@app.route("/api/override", methods=["POST"])
def override():
	try:
		body = get_json_body()
		admin_token = body.get("admin_token")
		authorization_error = review_authorization_error(admin_token)
		if authorization_error:
			return authorization_error
		request_id = int(body["request_id"])
		new_decision = body["new_decision"]
		reason = body["reason"]
		admin_name = body["admin_name"].strip()
	except (KeyError, TypeError, ValueError):
		return json_error("request_id, new_decision, reason, and admin_name are required")
	configured_name = configured_reviewer_name(admin_token)
	if configured_name and admin_name.casefold() != configured_name.casefold():
		return json_error("Reviewer name must match the authenticated account", 403)

	if not isinstance(new_decision, str) or not new_decision.strip():
		return json_error("new_decision must be a non-empty string")
	if not isinstance(reason, str) or not reason.strip():
		return json_error("reason must be a non-empty string")
	if not isinstance(admin_name, str) or not admin_name.strip():
		return json_error("admin_name must be a non-empty string")
	if new_decision not in {"emergency", "resident", "employee", "guest"}:
		return json_error("new_decision must be emergency, resident, employee, or guest")

	conn = get_connection()
	try:
		schedule = conn.execute(
			"SELECT * FROM schedule_faircharge WHERE request_id = ? ORDER BY id DESC LIMIT 1",
			(request_id,),
		).fetchone()
		if schedule is None:
			return json_error("No FairCharge schedule exists for request_id", 404)
		request_row = conn.execute(
			"SELECT priority_policy FROM requests WHERE request_id = ?",
			(request_id,),
		).fetchone()
		if request_row is None:
			return json_error("Request does not exist", 404)

		original_decision = f'{schedule["status"]}; priority_policy={request_row["priority_policy"]}'
		timestamp = datetime.now(timezone.utc).isoformat()
		conn.execute(
			"""
			INSERT INTO overrides (
				request_id, original_decision, new_decision,
				reason, admin_name, timestamp
			) VALUES (?, ?, ?, ?, ?, ?)
			""",
			(request_id, original_decision, f"priority_policy={new_decision}", reason.strip(), configured_name or admin_name, timestamp),
		)
		conn.execute("UPDATE requests SET priority_policy = ? WHERE request_id = ?", (new_decision, request_id))
		conn.commit()
	finally:
		conn.close()

	results = run_faircharge()
	save_faircharge_results(results)

	return jsonify({
		"message": "Priority override recorded and FairCharge rescheduled",
		"request_id": request_id,
		"priority_policy": new_decision,
	}), 201


@app.route("/api/overrides", methods=["GET"])
def get_overrides():
	authorization_error = review_authorization_error(request.headers.get("X-Admin-Token"))
	if authorization_error:
		return authorization_error
	conn = get_connection()
	try:
		rows = conn.execute(
			"SELECT * FROM overrides ORDER BY timestamp DESC, override_id DESC"
		).fetchall()
		return jsonify([row_to_dict(row) for row in rows])
	finally:
		conn.close()


@app.route("/api/stakeholder-feedback", methods=["GET", "POST"])
def stakeholder_feedback():
	if request.method == "GET":
		authorization_error = review_authorization_error(request.headers.get("X-Admin-Token"))
		if authorization_error:
			return authorization_error
		conn = get_connection()
		try:
			rows = conn.execute(
				"SELECT * FROM stakeholder_feedback ORDER BY session_date DESC, feedback_id DESC"
			).fetchall()
			return jsonify([row_to_dict(row) for row in rows])
		finally:
			conn.close()

	try:
		body = get_json_body()
		authorization_error = review_authorization_error(body.get("admin_token"))
		if authorization_error:
			return authorization_error
		stakeholder_role = body["stakeholder_role"].strip()
		session_date = body["session_date"]
		task_completion = body["task_completion"]
		explainability_rating = int(body["explainability_rating"])
		priority_acceptance_rating = int(body["priority_acceptance_rating"])
		recorded_by = body.get("recorded_by", "").strip()
		confusion_points = body.get("confusion_points", "").strip()
		requested_changes = body.get("requested_changes", "").strip()
		datetime.strptime(session_date, "%Y-%m-%d")
	except (KeyError, TypeError, ValueError, AttributeError):
		return json_error("Role, date, task result, and 1-5 ratings are required")
	if not stakeholder_role or task_completion not in {"completed", "partial", "failed"}:
		return json_error("Provide a stakeholder role and a valid task result")
	configured_name = configured_reviewer_name(body.get("admin_token"))
	if configured_name and recorded_by.casefold() != configured_name.casefold():
		return json_error("Interviewer name must match the authenticated account", 403)
	if configured_name:
		recorded_by = configured_name
	if not 1 <= explainability_rating <= 5 or not 1 <= priority_acceptance_rating <= 5:
		return json_error("Ratings must be between 1 and 5")
	if len(confusion_points) > 2000 or len(requested_changes) > 2000:
		return json_error("Feedback fields must be 2000 characters or fewer")
	if len(stakeholder_role) > 100 or len(recorded_by) > 100:
		return json_error("Role and interviewer name must be 100 characters or fewer")

	conn = get_connection()
	try:
		cursor = conn.execute(
			"INSERT INTO stakeholder_feedback (stakeholder_role, session_date, task_completion, "
			"explainability_rating, priority_acceptance_rating, recorded_by, confusion_points, requested_changes, created_at) "
			"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
			(stakeholder_role, session_date, task_completion, explainability_rating,
			 priority_acceptance_rating, recorded_by, confusion_points, requested_changes,
			 datetime.now(timezone.utc).isoformat()),
		)
		feedback_id = cursor.lastrowid
		conn.commit()
	finally:
		conn.close()
	return jsonify({"feedback_id": feedback_id, "recorded_by": recorded_by}), 201


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
