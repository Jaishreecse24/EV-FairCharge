const statusElement = document.getElementById("status");
const requestsBody = document.getElementById("requests-body");

function setStatus(message, isError = false) {
	statusElement.textContent = message;
	statusElement.classList.toggle("error", isError);
}

function updateMetrics(metrics, requestCount) {
	if (!metrics || !metrics.fcfs || !metrics.faircharge) {
		throw new Error("The metrics response has an unexpected format.");
	}
	document.getElementById("request-count").textContent = requestCount;
	document.getElementById("fcfs-served").textContent = metrics.fcfs.served;
	document.getElementById("faircharge-served").textContent = metrics.faircharge.served;
	document.getElementById("faircharge-wait").textContent = `${metrics.faircharge.average_wait_time_min} min`;
}

function renderRequests(requests) {
	if (requests.length === 0) {
		requestsBody.innerHTML = '<tr><td colspan="6" class="empty">No requests found.</td></tr>';
		return;
	}

	requestsBody.innerHTML = requests.map((request) => `
		<tr>
			<td>${request.request_id}</td>
			<td>${request.ev_user}</td>
			<td>${request.arrival_time} - ${request.departure_time}</td>
			<td>${request.energy_required_kwh} kWh</td>
			<td class="priority">${request.priority_policy}</td>
			<td>Charger ${request.charger_id}</td>
		</tr>
	`).join("");
}

async function loadDashboard() {
	setStatus("Loading current requests...");
	try {
		const [requestsResponse, metricsResponse] = await Promise.all([
			fetch("/api/requests"),
			fetch("/api/metrics"),
		]);
		if (!requestsResponse.ok || !metricsResponse.ok) {
			throw new Error("The API returned an error while loading dashboard data.");
		}

		const requests = await requestsResponse.json();
		const metrics = await metricsResponse.json();
		if (!Array.isArray(requests)) {
			throw new Error("The requests response has an unexpected format.");
		}
		renderRequests(requests);
		updateMetrics(metrics, requests.length);
		document.getElementById("last-updated").textContent = `Updated ${new Date().toLocaleTimeString()}`;
		setStatus("Connected to the FairCharge API.");
	} catch (error) {
		requestsBody.innerHTML = '<tr><td colspan="6" class="empty">Could not load requests.</td></tr>';
		setStatus(error.message, true);
	}
}

document.getElementById("refresh-button").addEventListener("click", loadDashboard);

document.getElementById("load-csv-button").addEventListener("click", async (event) => {
	const button = event.currentTarget;
	button.disabled = true;
	setStatus("Loading sample requests...");
	try {
		const response = await fetch("/api/load-csv", { method: "POST" });
		const summary = await response.json();
		if (!response.ok) {
			throw new Error(summary.error || "Could not load the sample CSV.");
		}
		await loadDashboard();
		setStatus(`Sample CSV loaded: ${summary.inserted_count} added, ${summary.skipped_count} already present.`);
	} catch (error) {
		setStatus(error.message, true);
	} finally {
		button.disabled = false;
	}
});

loadDashboard();
