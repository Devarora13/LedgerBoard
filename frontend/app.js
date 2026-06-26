// API Config
const API_BASE = ""; // Relative path to work seamlessly locally and on deployed URLs

// DOM Elements
const leaderboardBody = document.getElementById("leaderboard-body");
const autoRefreshToggle = document.getElementById("auto-refresh-toggle");
const refreshLeaderboardBtn = document.getElementById("refresh-leaderboard");
const transactionForm = document.getElementById("transaction-form");
const userIdInput = document.getElementById("userId");
const transactionIdInput = document.getElementById("transactionId");
const generateTxIdBtn = document.getElementById("generate-tx-id");
const amountInput = document.getElementById("amount");
const timestampInput = document.getElementById("timestamp");
const searchUserIdInput = document.getElementById("search-user-id");
const searchUserBtn = document.getElementById("search-user-btn");
const userSummaryDetails = document.getElementById("user-summary-details");
const userSummaryPlaceholder = document.getElementById("user-summary-placeholder");
const terminalLogs = document.getElementById("terminal-logs");
const clearLogsBtn = document.getElementById("clear-logs");

// Concurrency Elements
const simUserIdInput = document.getElementById("sim-user-id");
const runIdempotencySimBtn = document.getElementById("run-idempotency-sim");
const runConcurrencySimBtn = document.getElementById("run-concurrency-sim");
const runRateLimitSimBtn = document.getElementById("run-rate-limit-sim");

// Polling interval tracker
let pollInterval = null;
let healthInterval = null;

// Health check
async function checkHealth() {
    const indicator = document.getElementById("status-indicator");
    const statusText = document.getElementById("status-text");
    if (!indicator || !statusText) return;

    try {
        const res = await fetch(`${API_BASE}/health`);
        if (res.ok) {
            indicator.className = "status-indicator online";
            statusText.textContent = "Backend Connected";
        } else {
            throw new Error(`HTTP ${res.status}`);
        }
    } catch {
        indicator.className = "status-indicator offline";
        statusText.textContent = "Backend Offline";
    }
}

function startHealthPolling() {
    checkHealth();
    healthInterval = setInterval(checkHealth, 10000);
}

// Helper: Generate UUID v4
function generateUUID() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
        var r = Math.random() * 16 | 0, v = c == 'x' ? r : (r & 0x3 | 0x8);
        return v.toString(16);
    });
}

// Helper: Format Date for timestamp field (UTC format)
function updateTimestampField() {
    timestampInput.value = new Date().toISOString();
}

// Helper: Add log to terminal UI
function logEvent(type, message) {
    const timeStr = new Date().toTimeString().split(' ')[0];
    const logDiv = document.createElement("div");
    logDiv.className = `log-entry ${type}`;
    logDiv.innerHTML = `<span class="log-time">[${timeStr}]</span> ${message}`;
    terminalLogs.appendChild(logDiv);
    
    // Auto-scroll to bottom
    terminalLogs.scrollTop = terminalLogs.scrollHeight;
    
    // Keep max 100 logs
    while (terminalLogs.children.length > 100) {
        terminalLogs.removeChild(terminalLogs.firstChild);
    }
}

// Fetch and render Leaderboard
async function fetchLeaderboard() {
    const startTime = Date.now();
    try {
        const res = await fetch(`${API_BASE}/ranking`);
        if (!res.ok) throw new Error(`HTTP Error ${res.status}`);
        const data = await res.json();
        
        renderLeaderboard(data);
    } catch (err) {
        console.error("Leaderboard fetch failed", err);
        logEvent("error", `[API] Failed to fetch leaderboard: ${err.message}`);
    }
}

// Render rankings table
function renderLeaderboard(rankings) {
    if (rankings.length === 0) {
        leaderboardBody.innerHTML = `
            <tr>
                <td colspan="6" class="table-placeholder">
                    <p>No transactions recorded yet.</p>
                </td>
            </tr>
        `;
        return;
    }
    
    leaderboardBody.innerHTML = rankings.map(row => {
        let rankClass = "rank-other";
        if (row.rank === 1) rankClass = "rank-1";
        else if (row.rank === 2) rankClass = "rank-2";
        else if (row.rank === 3) rankClass = "rank-3";
        
        return `
            <tr>
                <td><span class="rank-badge ${rankClass}">${row.rank}</span></td>
                <td><span class="user-id-text">${escapeHtml(row.user_id)}</span></td>
                <td>${row.active_days}</td>
                <td>$${row.total_spent.toFixed(2)}</td>
                <td>${row.transaction_count}</td>
                <td><span class="score-text">${row.score.toFixed(2)}</span></td>
            </tr>
        `;
    }).join("");
}

// Helper: Escape HTML strings to prevent XSS
function escapeHtml(str) {
    return str.replace(/&/g, "&amp;")
              .replace(/</g, "&lt;")
              .replace(/>/g, "&gt;")
              .replace(/"/g, "&quot;")
              .replace(/'/g, "&#039;");
}

// Fetch user summary
async function fetchUserSummary(userId) {
    if (!userId) return;
    logEvent("sent", `[GET] /summary/${userId} - Fetching stats...`);
    try {
        const res = await fetch(`${API_BASE}/summary/${userId}`);
        const data = await res.json();
        
        if (res.ok) {
            logEvent("success", `[GET] /summary/${userId} - Successfully retrieved summary.`);
            document.getElementById("summary-rank").innerText = `#${data.rank}`;
            document.getElementById("summary-score").innerText = data.score.toFixed(2);
            document.getElementById("summary-spent").innerText = `$${data.total_spent.toFixed(2)}`;
            document.getElementById("summary-count").innerText = data.transaction_count;
            document.getElementById("summary-avg").innerText = `$${data.average_transaction.toFixed(2)}`;
            
            userSummaryDetails.classList.remove("hidden");
            userSummaryPlaceholder.classList.add("hidden");
        } else {
            logEvent("error", `[GET] /summary/${userId} - Failed: ${data.detail || 'Not Found'}`);
            userSummaryDetails.classList.add("hidden");
            userSummaryPlaceholder.classList.remove("hidden");
            userSummaryPlaceholder.innerHTML = `<p class="text-danger">Error: ${data.detail || 'User not found'}</p>`;
        }
    } catch (err) {
        logEvent("error", `[GET] /summary/${userId} - Connection failed: ${err.message}`);
    }
}

// Submit a single transaction via Form
async function submitTransaction(e) {
    e.preventDefault();
    
    const payload = {
        transactionId: transactionIdInput.value.trim(),
        userId: userIdInput.value.trim(),
        amount: parseFloat(amountInput.value),
        timestamp: timestampInput.value.trim()
    };
    
    logEvent("sent", `[POST] /transaction - Payload: ${JSON.stringify(payload)}`);
    
    try {
        const res = await fetch(`${API_BASE}/transaction`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        
        const data = await res.json();
        
        if (res.status === 200) {
            logEvent("success", `[POST] /transaction - Success! ID: ${data.transaction_id} | Points: +${data.points_awarded} | New Score: ${data.current_score}`);
            fetchLeaderboard();
            if (searchUserIdInput.value.trim() === payload.userId) {
                fetchUserSummary(payload.userId);
            }
            // Reset form identifiers
            transactionIdInput.value = generateUUID();
            updateTimestampField();
        } else if (res.status === 409) {
            logEvent("conflict", `[POST] /transaction - 409 Conflict (Duplicate): ${data.detail}`);
        } else if (res.status === 429) {
            logEvent("ratelimit", `[POST] /transaction - 429 Rate Limit: ${data.detail}`);
        } else {
            logEvent("error", `[POST] /transaction - Error ${res.status}: ${data.detail || JSON.stringify(data)}`);
        }
    } catch (err) {
        logEvent("error", `[POST] /transaction - Network error: ${err.message}`);
    }
}

// --- CONCURRENCY SIMULATORS ---

// 1. Idempotency Simulator: fires 5 identical transaction IDs
async function runIdempotencySim() {
    const userId = simUserIdInput.value.trim();
    if (!userId) {
        alert("Please specify a Test User ID.");
        return;
    }
    
    const txId = generateUUID();
    const amount = 50.0;
    const timestamp = new Date().toISOString();
    
    logEvent("system", `[SIMULATOR] Launching Idempotency Test. Sending 5 parallel requests with transactionId: ${txId}...`);
    
    const requests = Array.from({ length: 5 }).map((_, index) => {
        const payload = { transactionId: txId, userId, amount, timestamp };
        return fetch(`${API_BASE}/transaction`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        }).then(async res => ({
            index: index + 1,
            status: res.status,
            data: await res.json()
        }));
    });
    
    try {
        const results = await Promise.all(requests);
        results.forEach(res => {
            if (res.status === 200) {
                logEvent("success", `[SIM Req #${res.index}] SUCCESS (200) - Points: +${res.data.points_awarded} | New Score: ${res.data.current_score}`);
            } else if (res.status === 409) {
                logEvent("conflict", `[SIM Req #${res.index}] BLOCKED (409 Conflict): Duplicate transaction ID prevented.`);
            } else {
                logEvent("error", `[SIM Req #${res.index}] FAILED (${res.status}): ${res.data.detail}`);
            }
        });
        
        fetchLeaderboard();
        fetchUserSummary(userId);
    } catch (err) {
        logEvent("error", `[SIMULATOR] Execution failed: ${err.message}`);
    }
}

// 2. Concurrent Locking Simulator: fires 5 unique transaction IDs for same user concurrently
async function runConcurrencySim() {
    const userId = simUserIdInput.value.trim();
    if (!userId) {
        alert("Please specify a Test User ID.");
        return;
    }
    
    logEvent("system", `[SIMULATOR] Launching Concurrency Lock Test. Sending 5 parallel unique transactions for '${userId}' to verify database consistency...`);
    
    const requests = Array.from({ length: 5 }).map((_, index) => {
        const txId = generateUUID();
        const amount = 100.0; // Total should increase by 500
        const timestamp = new Date().toISOString();
        const payload = { transactionId: txId, userId, amount, timestamp };
        
        return fetch(`${API_BASE}/transaction`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        }).then(async res => ({
            index: index + 1,
            status: res.status,
            data: await res.json()
        }));
    });
    
    try {
        const results = await Promise.all(requests);
        results.forEach(res => {
            if (res.status === 200) {
                logEvent("success", `[SIM Req #${res.index}] SUCCESS (200) - Tx: ${res.data.transaction_id} | Score: ${res.data.current_score}`);
            } else {
                logEvent("error", `[SIM Req #${res.index}] FAILED (${res.status}): ${res.data.detail}`);
            }
        });
        
        fetchLeaderboard();
        fetchUserSummary(userId);
    } catch (err) {
        logEvent("error", `[SIMULATOR] Execution failed: ${err.message}`);
    }
}

// 3. Rate Limiter Simulator: fires 7 requests rapidly to hit the 5 txn / 10s limit
async function runRateLimitSim() {
    const userId = simUserIdInput.value.trim();
    if (!userId) {
        alert("Please specify a Test User ID.");
        return;
    }
    
    logEvent("system", `[SIMULATOR] Launching Rate Limit Abuse Test. Sending 7 unique transactions rapidly within 1 second...`);
    
    // We send them sequentially or parallel. Parallel will arrive almost instantly.
    const requests = Array.from({ length: 7 }).map((_, index) => {
        const txId = generateUUID();
        const amount = 20.0;
        const timestamp = new Date().toISOString();
        const payload = { transactionId: txId, userId, amount, timestamp };
        
        // Stagger requests by 50ms just to ensure order of logs
        return new Promise(resolve => setTimeout(resolve, index * 50)).then(() => {
            return fetch(`${API_BASE}/transaction`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            }).then(async res => ({
                index: index + 1,
                status: res.status,
                data: await res.json()
            }));
        });
    });
    
    try {
        const results = await Promise.all(requests);
        results.forEach(res => {
            if (res.status === 200) {
                logEvent("success", `[SIM Req #${res.index}] SUCCESS (200) - Score: ${res.data.current_score}`);
            } else if (res.status === 429) {
                logEvent("ratelimit", `[SIM Req #${res.index}] BLOCKED (429 Rate Limit): ${res.data.detail}`);
            } else {
                logEvent("error", `[SIM Req #${res.index}] FAILED (${res.status}): ${res.data.detail}`);
            }
        });
        
        fetchLeaderboard();
        fetchUserSummary(userId);
    } catch (err) {
        logEvent("error", `[SIMULATOR] Execution failed: ${err.message}`);
    }
}

// --- SETUP EVENT LISTENERS ---

// Generate UUID button click
generateTxIdBtn.addEventListener("click", () => {
    transactionIdInput.value = generateUUID();
});

// Form Submit
transactionForm.addEventListener("submit", submitTransaction);

// Refresh leaderboard manually
refreshLeaderboardBtn.addEventListener("click", () => {
    logEvent("system", "[SYSTEM] Refreshing Leaderboard...");
    fetchLeaderboard();
});

// Toggle auto polling
autoRefreshToggle.addEventListener("change", (e) => {
    if (e.target.checked) {
        startPolling();
        logEvent("system", "[SYSTEM] Auto-polling enabled (every 3s).");
    } else {
        stopPolling();
        logEvent("system", "[SYSTEM] Auto-polling disabled.");
    }
});

// Search User
searchUserBtn.addEventListener("click", () => {
    const searchId = searchUserIdInput.value.trim();
    if (searchId) {
        fetchUserSummary(searchId);
    }
});

searchUserIdInput.addEventListener("keypress", (e) => {
    if (e.key === "Enter") {
        const searchId = searchUserIdInput.value.trim();
        if (searchId) fetchUserSummary(searchId);
    }
});

// Clear Logs button
clearLogsBtn.addEventListener("click", () => {
    terminalLogs.innerHTML = "";
    logEvent("system", "[SYSTEM] Event feed cleared.");
});

// Simulator click events
runIdempotencySimBtn.addEventListener("click", runIdempotencySim);
runConcurrencySimBtn.addEventListener("click", runConcurrencySim);
runRateLimitSimBtn.addEventListener("click", runRateLimitSim);

// Polling helpers
function startPolling() {
    stopPolling();
    pollInterval = setInterval(fetchLeaderboard, 3000);
}

function stopPolling() {
    if (pollInterval) {
        clearInterval(pollInterval);
        pollInterval = null;
    }
}

// Page initialization
window.addEventListener("DOMContentLoaded", () => {
    transactionIdInput.value = generateUUID();
    updateTimestampField();
    fetchLeaderboard();
    startPolling();
    startHealthPolling();
});
