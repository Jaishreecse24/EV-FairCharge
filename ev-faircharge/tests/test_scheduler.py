import json
import os
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

import database
import models
from app import app, schedule_summary
from algorithms.fcfs import run_fcfs
from algorithms.faircharge import run_faircharge


class SchedulerEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = database.DB_PATH
        database.DB_PATH = os.path.join(self.temp_dir.name, "evaluation.db")
        self.original_admin_token = os.environ.get("FAIRCHARGE_ADMIN_TOKEN")
        os.environ["FAIRCHARGE_ADMIN_TOKEN"] = "test-review-key"
        self.client = app.test_client()
        database.initialize_database()
        self.load_summary = models.load_requests_from_csv()
        self.fcfs = run_fcfs()
        self.faircharge = run_faircharge()

    def tearDown(self):
        database.DB_PATH = self.original_db_path
        if self.original_admin_token is None:
            os.environ.pop("FAIRCHARGE_ADMIN_TOKEN", None)
        else:
            os.environ["FAIRCHARGE_ADMIN_TOKEN"] = self.original_admin_token
        self.temp_dir.cleanup()

    def test_sample_dataset_loads_idempotently(self):
        self.assertEqual(self.load_summary["inserted_count"], 20)
        repeated_load = models.load_requests_from_csv()
        self.assertEqual(repeated_load["inserted_count"], 0)
        self.assertEqual(repeated_load["skipped_count"], 20)

    def test_baseline_and_faircharge_measured_metrics(self):
        self.assertEqual(len(self.fcfs), 20)
        self.assertEqual(len(self.faircharge), 20)
        for results in (self.fcfs, self.faircharge):
            served = [row for row in results if row["status"] == "SERVED"]
            waits = [row["wait_time_min"] for row in served]
            self.assertEqual(len(served), 13)
            self.assertAlmostEqual(sum(waits) / len(waits), 4.62, places=2)

    def test_metrics_report_energy_fulfillment(self):
        self.client.post("/api/schedule/fcfs")
        self.client.post("/api/schedule/faircharge")
        metrics = self.client.get("/api/metrics").get_json()
        for algorithm in ("fcfs", "faircharge"):
            self.assertEqual(metrics[algorithm]["energy_required_kwh"], 89.25)
            self.assertEqual(metrics[algorithm]["energy_served_kwh"], 57.75)
            self.assertEqual(metrics[algorithm]["unserved_energy_kwh"], 31.5)
            self.assertEqual(metrics[algorithm]["energy_fulfillment_percent"], 64.71)
            self.assertEqual(metrics[algorithm]["jain_fairness_index"], 0.9835)
            self.assertEqual(metrics[algorithm]["deadline_miss_rate_percent"], 35.0)
            self.assertEqual(metrics[algorithm]["transformer_capacity_kw"], 14.0)

    def test_operator_impact_factors_drive_cost_and_emissions_estimates(self):
        response = self.client.post("/api/site/impact-factors", json={
            "electricity_cost_per_kwh": 0.25,
            "grid_emission_kg_per_kwh": 0.4,
            "admin_token": "test-review-key",
        })
        self.assertEqual(response.status_code, 200)
        self.client.post("/api/schedule/fcfs")
        self.client.post("/api/schedule/faircharge")
        metrics = self.client.get("/api/metrics").get_json()
        for algorithm in ("fcfs", "faircharge"):
            self.assertEqual(metrics[algorithm]["estimated_electricity_cost"], 14.44)
            self.assertEqual(metrics[algorithm]["estimated_grid_emissions_kg"], 23.1)

    def test_stakeholder_feedback_is_saved_and_retrievable(self):
        response = self.client.post("/api/stakeholder-feedback", json={
            "stakeholder_role": "Apartment EV driver",
            "session_date": "2026-10-02",
            "task_completion": "partial",
            "explainability_rating": 4,
            "priority_acceptance_rating": 3,
            "recorded_by": "Test Reviewer",
            "confusion_points": "Unserved reason needs more detail",
            "requested_changes": "Show the charger location",
            "admin_token": "test-review-key",
        })
        self.assertEqual(response.status_code, 201)
        records = self.client.get(
            "/api/stakeholder-feedback",
            headers={"X-Admin-Token": "test-review-key"},
        ).get_json()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["stakeholder_role"], "Apartment EV driver")
        self.assertEqual(records[0]["task_completion"], "partial")
        self.assertEqual(records[0]["recorded_by"], "Test Reviewer")

    def test_named_reviewer_token_binds_audit_identity(self):
        previous_config = os.environ.get("FAIRCHARGE_REVIEWERS_JSON")
        os.environ["FAIRCHARGE_REVIEWERS_JSON"] = json.dumps({
            "Reviewer One": "individual-token-one",
            "Reviewer Two": "individual-token-two",
        })
        try:
            self.client.post("/api/schedule/faircharge")
            payload = {
                "request_id": 6,
                "new_decision": "emergency",
                "reason": "Verified by reviewer",
                "admin_name": "Reviewer Two",
                "admin_token": "individual-token-one",
            }
            self.assertEqual(self.client.post("/api/override", json=payload).status_code, 403)
            payload["admin_name"] = "Reviewer One"
            self.assertEqual(self.client.post("/api/override", json=payload).status_code, 201)
            history = self.client.get(
                "/api/overrides",
                headers={"X-Admin-Token": "individual-token-one"},
            ).get_json()
            self.assertEqual(history[0]["admin_name"], "Reviewer One")
        finally:
            if previous_config is None:
                os.environ.pop("FAIRCHARGE_REVIEWERS_JSON", None)
            else:
                os.environ["FAIRCHARGE_REVIEWERS_JSON"] = previous_config

    def test_override_submission_requires_reviewer_token(self):
        response = self.client.post("/api/override", json={
            "request_id": 6,
            "new_decision": "emergency",
            "reason": "Test reason",
            "admin_name": "Test Reviewer",
        })
        self.assertEqual(response.status_code, 401)

    def test_request_api_accepts_only_bounded_slot_flexibility(self):
        payload = {
            "request_id": 90,
            "ev_user": "Flexible_User",
            "arrival_time": "16:00",
            "departure_time": "17:00",
            "departure_flexibility_min": 15,
            "energy_required_kwh": 1.75,
            "priority_policy": "guest",
            "charger_id": 1,
        }
        response = self.client.post("/api/requests", json=payload)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["request"]["departure_flexibility_min"], 15)

        payload["request_id"] = 91
        payload["departure_flexibility_min"] = 10
        self.assertEqual(self.client.post("/api/requests", json=payload).status_code, 400)

        payload["request_id"] = 92
        payload["departure_flexibility_min"] = 15.5
        self.assertEqual(self.client.post("/api/requests", json=payload).status_code, 400)

    def test_schedulers_never_assign_before_a_non_aligned_arrival(self):
        conn = database.get_connection()
        conn.execute(
            "INSERT INTO requests (request_id, ev_user, arrival_time, departure_time, "
            "energy_required_kwh, priority_policy, charger_id) VALUES "
            "(90, 'Late_Arrival', '16:10', '16:30', 1.75, 'guest', 1)"
        )
        conn.commit()
        conn.close()

        for results in (run_fcfs(), run_faircharge()):
            request = next(row for row in results if row["request_id"] == 90)
            self.assertEqual(request["status"], "SERVED")
            self.assertEqual(request["assigned_slot_start"], "16:15")
            self.assertEqual(request["assigned_slot_end"], "16:30")

    def test_api_rejects_non_finite_numeric_values(self):
        request_payload = {
            "request_id": 90,
            "ev_user": "Finite_User",
            "arrival_time": "16:00",
            "departure_time": "17:00",
            "energy_required_kwh": float("inf"),
            "priority_policy": "guest",
            "charger_id": 1,
        }
        self.assertEqual(self.client.post("/api/requests", json=request_payload).status_code, 400)

        impact_response = self.client.post("/api/site/impact-factors", json={
            "electricity_cost_per_kwh": float("nan"),
            "grid_emission_kg_per_kwh": 0.4,
            "admin_token": "test-review-key",
        })
        self.assertEqual(impact_response.status_code, 400)

        transformer_response = self.client.post("/api/site/transformer-limit", json={
            "transformer_capacity_kw": float("inf"),
            "admin_token": "test-review-key",
        })
        self.assertEqual(transformer_response.status_code, 400)

    def test_transformer_limit_endpoint_requires_auth_and_recomputes(self):
        payload = {
            "transformer_capacity_kw": 10,
            "admin_token": "test-review-key",
        }
        self.assertEqual(self.client.post("/api/site/transformer-limit", json={
            "transformer_capacity_kw": 10,
        }).status_code, 401)
        response = self.client.post("/api/site/transformer-limit", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/api/site").get_json()["transformer_capacity_kw"], 10)
        metrics = self.client.get("/api/metrics").get_json()
        self.assertEqual(metrics["fcfs"]["transformer_capacity_kw"], 10)

    def test_authorized_overstay_block_endpoint_recomputes_schedule(self):
        conn = database.get_connection()
        conn.execute(
            "INSERT INTO requests (request_id, ev_user, arrival_time, departure_time, "
            "energy_required_kwh, priority_policy, charger_id) VALUES "
            "(23, 'Late_EV', '16:00', '16:15', 1.75, 'resident', 1)"
        )
        conn.commit()
        conn.close()
        response = self.client.post("/api/charger-blocks", json={
            "charger_id": 1,
            "start_time": "16:00",
            "end_time": "16:15",
            "ports_blocked": 1,
            "reason": "overstay",
            "admin_token": "test-review-key",
        })
        self.assertEqual(response.status_code, 201)
        schedule = self.client.get("/api/schedule/faircharge").get_json()["schedule"]
        late_request = next(row for row in schedule if row["request_id"] == 23)
        self.assertEqual(late_request["reason"], "charger blocked: overstay")

    def test_departure_window_hard_constraint_and_review_flags(self):
        fcfs_by_id = {row["request_id"]: row for row in self.fcfs}
        faircharge_by_id = {row["request_id"]: row for row in self.faircharge}
        for request_id in (6, 7):
            self.assertEqual(fcfs_by_id[request_id]["reason"], "departure too close")
            self.assertEqual(faircharge_by_id[request_id]["reason"], "departure too close")
            self.assertEqual(faircharge_by_id[request_id]["needs_review"], 1)

    def test_capacity_conflicts_are_reported(self):
        fcfs_by_id = {row["request_id"]: row for row in self.fcfs}
        faircharge_by_id = {row["request_id"]: row for row in self.faircharge}
        expected_reasons = {
            4: "insufficient capacity",
            5: "insufficient capacity",
            16: "transformer capacity exceeded",
        }
        for request_id, expected_reason in expected_reasons.items():
            self.assertEqual(fcfs_by_id[request_id]["status"], "UNSERVED")
            self.assertEqual(fcfs_by_id[request_id]["reason"], expected_reason)
            self.assertEqual(faircharge_by_id[request_id]["status"], "UNSERVED")
            self.assertEqual(faircharge_by_id[request_id]["reason"], expected_reason)

    def test_priority_policy_service_counts_are_reported(self):
        requests = {row["request_id"]: row["priority_policy"] for row in models.get_all_requests()}
        expected = Counter({
            ("emergency", "SERVED"): 1,
            ("emergency", "UNSERVED"): 1,
            ("resident", "SERVED"): 5,
            ("resident", "UNSERVED"): 2,
            ("employee", "SERVED"): 4,
            ("employee", "UNSERVED"): 2,
            ("guest", "SERVED"): 3,
            ("guest", "UNSERVED"): 2,
        })
        for results in (self.fcfs, self.faircharge):
            actual = Counter((requests[row["request_id"]], row["status"]) for row in results)
            self.assertEqual(actual, expected)

    def test_controlled_priority_conflict_trades_wait_for_emergency_access(self):
        conn = database.get_connection()
        conn.executemany(
            """
            INSERT INTO requests (
                request_id, ev_user, arrival_time, departure_time,
                energy_required_kwh, priority_policy, charger_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (21, "EV_User_21", "16:00", "18:15", 7.0, "guest", 1),
                (22, "EV_User_22", "16:15", "17:15", 7.0, "emergency", 1),
            ],
        )
        conn.commit()
        conn.close()

        fcfs = run_fcfs()
        faircharge = run_faircharge()
        fcfs_summary = schedule_summary(fcfs)
        faircharge_summary = schedule_summary(faircharge)
        fcfs_by_id = {row["request_id"]: row for row in fcfs}
        faircharge_by_id = {row["request_id"]: row for row in faircharge}

        self.assertEqual(fcfs_by_id[22]["status"], "UNSERVED")
        self.assertEqual(faircharge_by_id[22]["status"], "SERVED")
        self.assertEqual(fcfs_summary["served"], 14)
        self.assertEqual(faircharge_summary["served"], 15)
        self.assertEqual(fcfs_summary["energy_served_kwh"], 64.75)
        self.assertEqual(faircharge_summary["energy_served_kwh"], 71.75)
        self.assertEqual(fcfs_summary["average_wait_time_min"], 4.29)
        self.assertEqual(faircharge_summary["average_wait_time_min"], 9.0)
        self.assertEqual(fcfs_summary["jain_fairness_index"], 0.9384)
        self.assertEqual(faircharge_summary["jain_fairness_index"], 0.9991)

    def test_transformer_cap_blocks_third_simultaneous_port(self):
        conn = database.get_connection()
        conn.executemany(
            "INSERT INTO requests (request_id, ev_user, arrival_time, departure_time, "
            "energy_required_kwh, priority_policy, charger_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (30, "Peak_1", "16:00", "16:15", 1.75, "employee", 1),
                (31, "Peak_2", "16:00", "16:15", 1.75, "employee", 2),
                (32, "Peak_3", "16:00", "16:15", 1.75, "employee", 2),
            ],
        )
        conn.commit()
        conn.close()

        for results in (run_fcfs(), run_faircharge()):
            peak_request = next(row for row in results if row["request_id"] == 32)
            self.assertEqual(peak_request["reason"], "transformer capacity exceeded")

    def test_charger_outage_marks_requests_unserved(self):
        conn = database.get_connection()
        conn.execute("UPDATE chargers SET is_available = 0 WHERE charger_id = 1")
        conn.commit()
        conn.close()

        for results in (run_fcfs(), run_faircharge()):
            outage_requests = [row for row in results if row["request_id"] <= 10]
            self.assertTrue(all(row["status"] == "UNSERVED" for row in outage_requests))
            self.assertTrue(all(row["reason"] == "charger unavailable" for row in outage_requests))

    def test_overstay_block_reserves_a_port(self):
        conn = database.get_connection()
        conn.execute(
            "INSERT INTO requests (request_id, ev_user, arrival_time, departure_time, "
            "energy_required_kwh, priority_policy, charger_id) VALUES "
            "(23, 'Late_EV', '16:00', '16:15', 1.75, 'resident', 1)"
        )
        conn.execute(
            "INSERT INTO charger_blocks (charger_id, start_time, end_time, ports_blocked, reason) "
            "VALUES (1, '16:00', '16:15', 1, 'overstay')"
        )
        conn.commit()
        conn.close()

        for results in (run_fcfs(), run_faircharge()):
            overstay_request = next(row for row in results if row["request_id"] == 23)
            self.assertEqual(overstay_request["status"], "UNSERVED")
            self.assertEqual(overstay_request["reason"], "charger blocked: overstay")

    def test_departure_flexibility_is_bounded_and_recorded(self):
        conn = database.get_connection()
        conn.execute(
            "INSERT INTO requests (request_id, ev_user, arrival_time, departure_time, "
            "departure_flexibility_min, energy_required_kwh, priority_policy, charger_id) "
            "VALUES (24, 'Flexible_EV', '16:00', '16:45', 15, 7.0, 'resident', 1)"
        )
        conn.commit()
        conn.close()

        flexible_request = next(row for row in run_faircharge() if row["request_id"] == 24)
        self.assertEqual(flexible_request["status"], "SERVED")
        self.assertEqual(flexible_request["assigned_slot_end"], "17:00")
        self.assertEqual(flexible_request["reason"], "served using 15 min departure flexibility")

    def test_review_endpoints_require_reviewer_token(self):
        self.assertEqual(self.client.get("/api/overrides").status_code, 401)
        response = self.client.get(
            "/api/overrides",
            headers={"X-Admin-Token": "test-review-key"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), [])

    def test_authorized_review_is_saved_in_audit_log(self):
        self.client.post("/api/schedule/faircharge")
        response = self.client.post("/api/override", json={
            "request_id": 6,
            "new_decision": "emergency",
            "reason": "Reviewer verified the emergency classification",
            "admin_name": "Test Reviewer",
            "admin_token": "test-review-key",
        })
        self.assertEqual(response.status_code, 201)

        history = self.client.get(
            "/api/overrides",
            headers={"X-Admin-Token": "test-review-key"},
        ).get_json()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["request_id"], 6)
        self.assertEqual(history[0]["new_decision"], "priority_policy=emergency")
        request = self.client.get("/api/requests").get_json()
        self.assertEqual(next(row for row in request if row["request_id"] == 6)["priority_policy"], "emergency")
        schedule = self.client.get("/api/schedule/faircharge").get_json()["schedule"]
        self.assertEqual(next(row for row in schedule if row["request_id"] == 6)["overridden"], 1)
        self.client.post("/api/schedule/faircharge")
        rescheduled = self.client.get("/api/schedule/faircharge").get_json()["schedule"]
        self.assertEqual(next(row for row in rescheduled if row["request_id"] == 6)["overridden"], 1)

    def test_unrecognized_review_decision_is_rejected(self):
        response = self.client.post("/api/override", json={
            "request_id": 6,
            "new_decision": "MAYBE",
            "reason": "Test reason",
            "admin_name": "Test Reviewer",
            "admin_token": "test-review-key",
        })
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
