const scheduleStatus = document.getElementById("schedule-status");
const scheduleBody = document.getElementById("schedule-body");

function setScheduleStatus(message, isError = false) {
	scheduleStatus.textContent = message;
	scheduleStatus.classList.toggle("error", isError);
}

async function getJson(url, options) {
	const response = await fetch(url, options);
	const data = await response.json();
	if (!response.ok) {
		throw new Error(data.error || "The API request failed.");
	}
	return data;
}

function slotLabel(row) {
	return row.assigned_slot_start && row.assigned_slot_end
		? `${row.assigned_slot_start} - ${row.assigned_slot_end}`
		: "-";
}

function renderSchedules(requests, fcfs, faircharge) {
	const fcfsById = new Map(fcfs.schedule.map((row) => [row.request_id, row]));
	const fairchargeById = new Map(faircharge.schedule.map((row) => [row.request_id, row]));
	if (requests.length === 0) {
		scheduleBody.innerHTML = '<tr><td colspan="10" class="empty">No requests are loaded.</td></tr>';
		return;
	}

	scheduleBody.replaceChildren(...requests.map((request) => {
		const firstCome = fcfsById.get(request.request_id);
		const fair = fairchargeById.get(request.request_id);
		const row = document.createElement("tr");
		const values = [
			request.request_id,
			request.ev_user,
			request.priority_policy,
			firstCome?.status || "Not run",
			slotLabel(firstCome || {}),
			fair?.status || "Not run",
			slotLabel(fair || {}),
			fair?.reason || "-",
			fair?.wait_time_min == null ? "-" : `${fair.wait_time_min} min`,
			fair?.needs_review ? (fair.overridden ? "Reviewed" : "Needs review") : "-",
		];
		for (const value of values) {
			const cell = document.createElement("td");
			cell.textContent = value;
			row.append(cell);
		}
		return row;
	}));
}

async function loadSchedules() {
	setScheduleStatus("Loading saved schedules...");
	try {
		const [requests, fcfs, faircharge, metrics] = await Promise.all([
			getJson("/api/requests"),
			getJson("/api/schedule/fcfs"),
			getJson("/api/schedule/faircharge"),
			getJson("/api/metrics"),
		]);
		document.getElementById("total-requests").textContent = requests.length;
		document.getElementById("fcfs-served").textContent = `${metrics.fcfs.served} / ${metrics.fcfs.total_requests}`;
		document.getElementById("faircharge-served").textContent = `${metrics.faircharge.served} / ${metrics.faircharge.total_requests}`;
		document.getElementById("fcfs-energy").textContent = `${metrics.fcfs.energy_served_kwh} / ${metrics.fcfs.energy_required_kwh} kWh (${metrics.fcfs.energy_fulfillment_percent}%)`;
		document.getElementById("faircharge-energy").textContent = `${metrics.faircharge.energy_served_kwh} / ${metrics.faircharge.energy_required_kwh} kWh (${metrics.faircharge.energy_fulfillment_percent}%)`;
		document.getElementById("jain-index").textContent =
			`FCFS ${metrics.fcfs.jain_fairness_index} / FairCharge ${metrics.faircharge.jain_fairness_index}`;
		document.getElementById("unserved-energy").textContent =
			`FCFS ${metrics.fcfs.unserved_energy_kwh} / FairCharge ${metrics.faircharge.unserved_energy_kwh} kWh`;
		document.getElementById("deadline-miss-rate").textContent =
			`FCFS ${metrics.fcfs.deadline_miss_rate_percent}% / FairCharge ${metrics.faircharge.deadline_miss_rate_percent}%`;
		document.getElementById("deadline-miss-count").textContent =
			`FCFS ${metrics.fcfs.deadline_miss_count} / FairCharge ${metrics.faircharge.deadline_miss_count}`;
		document.getElementById("transformer-cap").textContent = `${metrics.fcfs.transformer_capacity_kw} kW`;
		document.getElementById("estimated-cost").textContent = metrics.fcfs.estimated_electricity_cost == null
			? "Not configured"
			: `FCFS ${metrics.fcfs.estimated_electricity_cost} / FairCharge ${metrics.faircharge.estimated_electricity_cost}`;
		document.getElementById("estimated-emissions").textContent = metrics.fcfs.estimated_grid_emissions_kg == null
			? "Not configured"
			: `FCFS ${metrics.fcfs.estimated_grid_emissions_kg} / FairCharge ${metrics.faircharge.estimated_grid_emissions_kg}`;
		document.getElementById("served-difference").textContent = metrics.comparison.served_difference > 0
			? `+${metrics.comparison.served_difference}`
			: metrics.comparison.served_difference;
		document.getElementById("wait-comparison").textContent =
			`Average wait: FCFS ${metrics.fcfs.average_wait_time_min} min / FairCharge ${metrics.faircharge.average_wait_time_min} min`;
		renderSchedules(requests, fcfs, faircharge);
		setScheduleStatus("Schedules loaded.");
	} catch (error) {
		setScheduleStatus(error.message, true);
		scheduleBody.innerHTML = '<tr><td colspan="10" class="empty">Could not load schedules.</td></tr>';
	}
}

document.getElementById("run-schedules").addEventListener("click", async (event) => {
	const button = event.currentTarget;
	button.disabled = true;
	setScheduleStatus("Running FCFS and FairCharge...");
	try {
		await Promise.all([
			getJson("/api/schedule/fcfs", { method: "POST" }),
			getJson("/api/schedule/faircharge", { method: "POST" }),
		]);
		await loadSchedules();
	} catch (error) {
		setScheduleStatus(error.message, true);
	} finally {
		button.disabled = false;
	}
});

loadSchedules();
