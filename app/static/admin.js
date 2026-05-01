const page = document.body;
const statusEndpoint = page.dataset.statusEndpoint;
const watchUpdate = page.dataset.watchUpdate === "true";
const initialLastAttempt = page.dataset.initialLastAttempt || "";
const initialActiveRelease = page.dataset.initialActiveRelease || "";
const initialUpdateInProgress = page.dataset.initialUpdateInProgress === "true";
const UPDATE_SUCCESS_LOG_MARKER = "Update completed successfully.";

const POLL_INTERVAL_MS = 3000;
const updateNotice = document.getElementById("updateNotice");
const updateNoticeMessage = document.getElementById("updateNoticeMessage");
const updateNoticeProgress = document.getElementById("updateNoticeProgress");

let pollTimer = null;
let observedAttempt = initialUpdateInProgress;

function formatFieldValue(field, value) {
    if (field === "update_in_progress") {
        return value ? "Updating software" : "Ready";
    }

    if (value === null || value === undefined || value === "") {
        if (
            field === "active_release" ||
            field === "last_known_good" ||
            field === "previous_release"
        ) {
            return "Not available yet";
        }
        if (field === "last_attempt") {
            return "No updates run yet";
        }
        if (field === "last_error") {
            return "No problems reported";
        }
        if (field === "latest_log") {
            return "No logs yet";
        }
    }

    return value;
}

function renderNotice(kind, message, showProgress) {
    if (!updateNotice || !updateNoticeMessage || !updateNoticeProgress) {
        return;
    }

    updateNotice.className = `notice notice--${kind}`;
    updateNotice.classList.remove("hidden");
    updateNoticeMessage.textContent = message;
    updateNoticeProgress.classList.toggle("hidden", !showProgress);
}

function hideNotice() {
    if (!updateNotice || !updateNoticeMessage || !updateNoticeProgress) {
        return;
    }

    updateNotice.className = "notice hidden";
    updateNoticeMessage.textContent = "";
    updateNoticeProgress.classList.add("hidden");
}

function updateStatusFields(data) {
    const fields = [
        "update_in_progress",
        "active_release",
        "last_known_good",
        "previous_release",
        "last_attempt",
        "last_error",
        "latest_log",
    ];

    fields.forEach((field) => {
        const element = document.getElementById(field);
        if (!element) {
            return;
        }

        element.textContent = formatFieldValue(field, data[field]);
    });

    const logTail = document.getElementById("log_tail");
    if (logTail) {
        logTail.textContent =
            (data.log_tail || []).join("\n") || "No updater log output available yet.";
    }
}

function updateObservedAttempt(data) {
    if (data.update_in_progress) {
        observedAttempt = true;
        return;
    }

    if (watchUpdate && data.last_attempt && data.last_attempt !== initialLastAttempt) {
        observedAttempt = true;
    }
}

function hasSuccessSignal(data) {
    const logTail = data.log_tail || [];
    if (logTail.some((line) => line.includes(UPDATE_SUCCESS_LOG_MARKER))) {
        return true;
    }

    if (data.active_release && data.active_release !== initialActiveRelease) {
        return true;
    }
    return false;
}

function shouldKeepPolling(data) {
    if (!watchUpdate) {
        return false;
    }

    if (data.update_in_progress) {
        return true;
    }

    if (data.last_error) {
        return false;
    }

    if (hasSuccessSignal(data)) {
        return false;
    }

    return true;
}

function renderUpdateState(data) {
    const hasAttempt = Boolean(data.last_attempt);

    if (data.update_in_progress || (watchUpdate && !observedAttempt)) {
        renderNotice("info", "Updating software", true);
        return;
    }

    if (hasAttempt && data.last_error) {
        renderNotice(
            "error",
            "Update failed. Please contact SBCTS@gov.bc.ca for assistance",
            false,
        );
        return;
    }

    if (hasAttempt && hasSuccessSignal(data) && (observedAttempt || !watchUpdate)) {
        renderNotice("success", "Update successful", false);
        return;
    }

    if (hasAttempt && watchUpdate) {
        renderNotice("info", "Updating software", true);
        return;
    }

    if (hasAttempt && !watchUpdate) {
        if (data.last_error) {
            renderNotice(
                "error",
                "Update failed. Please contact SBCTS@gov.bc.ca for assistance",
                false,
            );
            return;
        }
    }

    hideNotice();
}

async function refreshStatus() {
    try {
        const response = await fetch(statusEndpoint, { cache: "no-store" });
        if (!response.ok) {
            return true;
        }

        const data = await response.json();
        updateObservedAttempt(data);
        updateStatusFields(data);
        renderUpdateState(data);
        return shouldKeepPolling(data);
    } catch (error) {
        console.warn("Could not refresh updater status", error);
        return true;
    }
}

function stopPolling() {
    if (pollTimer !== null) {
        window.clearInterval(pollTimer);
        pollTimer = null;
    }
}

function startPolling() {
    if (pollTimer !== null) {
        return;
    }

    pollTimer = window.setInterval(async () => {
        const keepPolling = await refreshStatus();
        if (!keepPolling) {
            stopPolling();
        }
    }, POLL_INTERVAL_MS);
}

if (watchUpdate) {
    renderNotice("info", "Updating software", true);
    startPolling();
    void refreshStatus().then((keepPolling) => {
        if (!keepPolling) {
            stopPolling();
        }
    });
}
