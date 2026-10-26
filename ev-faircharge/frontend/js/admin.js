const reviewStatus = document.getElementById("review-status");
const reviewBody = document.getElementById("review-body");
const historyBody = document.getElementById("history-body");
const feedbackBody = document.getElementById("feedback-body");
const reviewForm = document.getElementById("review-form");
const siteImpactForm = document.getElementById("site-impact-form");
const stakeholderFeedbackForm = document.getElementById("stakeholder-feedback-form");

function setReviewStatus(message, isError = false) {
	reviewStatus.textContent = message;
	reviewStatus.classList.toggle("error", isError);
}

async function getJson(url, options) {
	const response = await fetch(url, options);
	const data = await response.json();
	if (!response.ok) {
		throw new Error(data.error || "The API request failed.");
	}
	return data;
}

function addCell(row, value) {
	const cell = document.createElement("td");
	cell.textContent = value ?? "-";
	row.append(cell);
}

function showTableMessage(body, columnCount, message) {
	const row = document.createElement("tr");
	const cell = document.createElement("td");
	cell.colSpan = columnCount;
	cell.className = "empty";
	cell.textContent = message;
	row.append(cell);
	body.replaceChildren(row);
}

function renderReviewQueue(requests, schedules) {
	const requestsById = new Map(requests.map((request) => [request.request_id, request]));
	const flagged = schedules.filter((schedule) => schedule.needs_review && !schedule.overridden);
	if (!flagged.length) {
		showTableMessage(reviewBody, 7, "No requests are waiting for review.");
		return;
	}

	reviewBody.replaceChildren(...flagged.map((schedule) => {
		const request = requestsById.get(schedule.request_id) || {};
		const row = document.createElement("tr");
		addCell(row, schedule.request_id);
		addCell(row, request.ev_user || "Unknown user");
		addCell(row, request.priority_policy || "-");
		addCell(row, schedule.status);
		addCell(row, schedule.reason || "-");
		addCell(row, "Pending");
		const action = document.createElement("td");
		const selectButton = document.createElement("button");
		selectButton.type = "button";
		selectButton.className = "text-button";
		selectButton.textContent = "Review";
		selectButton.addEventListener("click", () => {
			reviewForm.elements.request_id.value = schedule.request_id;
			document.getElementById("review-selection").textContent = `Reviewing request ${schedule.request_id} (${request.ev_user || "unknown user"})`;
			reviewForm.scrollIntoView({ behavior: "smooth", block: "center" });
			reviewForm.elements.new_decision.focus();
		});
		action.append(selectButton);
		row.append(action);
		return row;
	}));
}

function renderHistory(records) {
	if (!records.length) {
		historyBody.innerHTML = '<tr><td colspan="6" class="empty">No reviews recorded.</td></tr>';
		return;
	}
	historyBody.replaceChildren(...records.map((record) => {
		const row = document.createElement("tr");
		addCell(row, new Date(record.timestamp).toLocaleString());
		addCell(row, record.request_id);
		addCell(row, record.original_decision);
		addCell(row, record.new_decision);
		addCell(row, record.admin_name);
		addCell(row, record.reason);
		return row;
	}));
}

function renderFeedback(records) {
	if (!records.length) {
		feedbackBody.innerHTML = '<tr><td colspan="7" class="empty">No stakeholder sessions recorded yet.</td></tr>';
		return;
	}
	feedbackBody.replaceChildren(...records.map((record) => {
		const row = document.createElement("tr");
		addCell(row, record.session_date);
		addCell(row, record.stakeholder_role);
		addCell(row, record.task_completion);
		addCell(row, record.explainability_rating);
		addCell(row, record.priority_acceptance_rating);
		addCell(row, record.recorded_by);
		addCell(row, [record.confusion_points, record.requested_changes].filter(Boolean).join(" | ") || "-");
		return row;
	}));
}

async function loadReviewData() {
	setReviewStatus("Loading review queue...");
	try {
		const [requests, schedule, site] = await Promise.all([
			getJson("/api/requests"),
			getJson("/api/schedule/faircharge"),
			getJson("/api/site"),
		]);
		renderReviewQueue(requests, schedule.schedule);
		siteImpactForm.elements.electricity_cost_per_kwh.value = site.electricity_cost_per_kwh ?? "";
		siteImpactForm.elements.grid_emission_kg_per_kwh.value = site.grid_emission_kg_per_kwh ?? "";
		const adminToken = reviewForm.elements.admin_token.value;
		if (!adminToken) {
			showTableMessage(historyBody, 6, "Enter reviewer access key to view review history.");
			showTableMessage(feedbackBody, 7, "Enter reviewer access key to view session records.");
		} else {
			const options = { headers: { "X-Admin-Token": adminToken } };
			const [overrides, feedback] = await Promise.all([
				getJson("/api/overrides", options),
				getJson("/api/stakeholder-feedback", options),
			]);
			renderHistory(overrides);
			renderFeedback(feedback);
		}
		setReviewStatus("Review queue is up to date.");
	} catch (error) {
		setReviewStatus(error.message, true);
		showTableMessage(historyBody, 6, error.message);
		showTableMessage(feedbackBody, 7, error.message);
	}
}

reviewForm.addEventListener("submit", async (event) => {
	event.preventDefault();
	const payload = Object.fromEntries(new FormData(reviewForm).entries());
	if (!payload.request_id) {
		setReviewStatus("Select a request from the queue before submitting a review.", true);
		return;
	}
	try {
		await getJson("/api/override", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ ...payload, request_id: Number(payload.request_id) }),
		});
		const reviewerName = payload.admin_name;
		const adminToken = payload.admin_token;
		reviewForm.reset();
		reviewForm.elements.admin_name.value = reviewerName;
		reviewForm.elements.admin_token.value = adminToken;
		document.getElementById("review-selection").textContent = "Select a decision below to review a request.";
		setReviewStatus("Review decision recorded.");
		await loadReviewData();
	} catch (error) {
		setReviewStatus(error.message, true);
	}
});

siteImpactForm.addEventListener("submit", async (event) => {
	event.preventDefault();
	const adminToken = reviewForm.elements.admin_token.value;
	if (!adminToken) {
		setReviewStatus("Enter reviewer access before saving site factors.", true);
		return;
	}
	const values = Object.fromEntries(new FormData(siteImpactForm).entries());
	try {
		await getJson("/api/site/impact-factors", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({
				admin_token: adminToken,
				electricity_cost_per_kwh: values.electricity_cost_per_kwh === "" ? null : Number(values.electricity_cost_per_kwh),
				grid_emission_kg_per_kwh: values.grid_emission_kg_per_kwh === "" ? null : Number(values.grid_emission_kg_per_kwh),
			}),
		});
		setReviewStatus("Site factors saved. Refresh Schedule to see the estimates.");
	} catch (error) {
		setReviewStatus(error.message, true);
	}
});

stakeholderFeedbackForm.addEventListener("submit", async (event) => {
	event.preventDefault();
	const adminToken = reviewForm.elements.admin_token.value;
	if (!adminToken) {
		setReviewStatus("Enter reviewer access before recording a session.", true);
		return;
	}
	const payload = Object.fromEntries(new FormData(stakeholderFeedbackForm).entries());
	payload.admin_token = adminToken;
	payload.recorded_by = reviewForm.elements.admin_name.value;
	try {
		await getJson("/api/stakeholder-feedback", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify(payload),
		});
		stakeholderFeedbackForm.reset();
		setReviewStatus("Stakeholder session recorded.");
		await loadReviewData();
	} catch (error) {
		setReviewStatus(error.message, true);
	}
});

document.getElementById("refresh-review").addEventListener("click", loadReviewData);
loadReviewData();
