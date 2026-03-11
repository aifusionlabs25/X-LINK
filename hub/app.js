/** 
 * X-LINK Hub v2.5 - Command-In-Chief Protocol
 * Handles real-time polling and tool orchestration.
 */

const API_BASE = "http://127.0.0.1:5001";

async function fetchStatus() {
    try {
        const response = await fetch(`${API_BASE}/api/data`);
        if (!response.ok) throw new Error("Bridge response error");
        const data = await response.json();
        updateUI(data);
    } catch (e) {
        console.error("📡 Bridge Sync Failed:", e);
        document.getElementById('hub-status-text').innerText = "Bridge Offline";
        document.getElementById('hub-status-btn').style.color = "var(--danger)";
    }
}

function updateUI(data) {
    const { audit, briefing, subscriptions } = data;

    // Update Sync Time
    if (data.server_time) {
        const time = new Date(data.server_time);
        document.getElementById('sync-time').innerText = time.toLocaleTimeString();
    }

    // Update Pulse
    const pulse = document.getElementById('system-pulse');
    pulse.innerText = "ACTIVE";
    pulse.className = "meta-value pulse-green";

    document.getElementById('hub-status-text').innerText = "Bridge Online";
    document.getElementById('hub-status-btn').style.color = "var(--success)";

    // 1. Update Sloane's Summary
    if (briefing && briefing.sloane) {
        document.getElementById('sloane-summary').innerText = `"${briefing.sloane.summary}"`;

        // Update Departments
        const depts = briefing.departments;
        if (depts) {
            updateDept("rd", depts.rd);
            updateDept("sales", depts.sales);
            updateDept("ops", depts.ops);
        }
    }

    // 2. Update Audit Grid
    if (audit) {
        renderAuditGrid(audit, subscriptions);
    }

    // 3. Update Renewal Timeline
    if (subscriptions) {
        renderRenewalTimeline(subscriptions);
    }
}

function updateDept(id, data) {
    const summary = document.getElementById(`${id}-summary`);
    const list = document.getElementById(`${id}-priorities`);
    if (summary && data) {
        summary.innerText = data.summary;
        list.innerHTML = (data.priorities || []).map(p => `<li>${p}</li>`).join('');
    }
}

function renderAuditGrid(audit, subscriptions) {
    const grid = document.getElementById('audit-grid');
    const hero = document.getElementById('stats-hero');
    grid.innerHTML = "";

    let totalSpend = 0;
    let totalMonthlyCost = 0;
    let activeNodes = 0;

    // Build lookup from subscription registry
    const subLookup = {};
    if (subscriptions && subscriptions.subscriptions) {
        subscriptions.subscriptions.forEach(s => {
            subLookup[s.platform] = s;
        });
    }

    const nameMap = {
        'Tavus Usage': 'Tavus', 'Tavus Billing': 'Tavus',
        'Anam Lab Dashboard': 'Anam AI', 'Anam Lab Sessions': 'Anam AI',
        'Vercel Usage': 'Vercel', 'Resend Billing': 'Resend',
        'Cartesia Console': 'Cartesia', 'Elevenlabs Usage': 'ElevenLabs'
    };

    Object.entries(audit).forEach(([name, result]) => {
        activeNodes++;
        const card = document.createElement('div');
        card.className = "platform-card";

        const data = result.data || {};
        let mainMetric = result.metric_type || "TELEMETRY...";

        const subKey = nameMap[name] || name;
        const sub = subLookup[subKey] || {};
        const plan = sub.plan || '—';
        const cost = sub.cost || '—';
        const renewalDate = sub.renewal_date || null;

        if (cost && cost !== '—') {
            const costVal = parseFloat(cost.replace(/[^0-9.]/g, ''));
            if (!isNaN(costVal)) totalMonthlyCost += costVal;
        }

        if (result.status === "blocked") {
            card.style.borderColor = "var(--danger)";
            mainMetric = "AUTH WALL";
            showSecurityAlert(name, result.issue);
        }

        if (data.total_spend) {
            const val = parseFloat(data.total_spend.replace('$', ''));
            if (!isNaN(val)) totalSpend += val;
        }

        let renewalHtml = '';
        if (renewalDate) {
            const diff = Math.ceil((new Date(renewalDate) - new Date()) / 86400000);
            const cls = diff <= 3 ? 'renewal-urgent' : diff <= 7 ? 'renewal-soon' : 'renewal-ok';
            renewalHtml = `<div class="renewal-countdown ${cls}">🗓 Renews in ${diff}d</div>`;
        }

        let extraHtml = '';
        if (sub.bandwidth) extraHtml += `<span class="data-pill">📡 ${sub.bandwidth}</span>`;
        if (sub.email_quota) extraHtml += `<span class="data-pill">📧 ${sub.email_quota}</span>`;
        if (sub.character_quota) extraHtml += `<span class="data-pill">🔤 ${sub.character_quota}</span>`;
        if (sub.credits_remaining) extraHtml += `<span class="data-pill">🎫 ${sub.credits_remaining}</span>`;

        card.innerHTML = `
            <div class="card-top-row">
                <span class="plan-badge">${plan}</span>
                <span class="cost-badge">${cost}</span>
            </div>
            <h3 class="platform-name">${name}</h3>
            <div class="metric-value">${mainMetric}</div>
            ${extraHtml ? `<div class="extra-pills">${extraHtml}</div>` : ''}
            ${renewalHtml}
            <div class="card-footer">
                <span class="timestamp">${new Date(result.timestamp).toLocaleTimeString()}</span>
            </div>
        `;
        grid.appendChild(card);
    });

    hero.innerHTML = `
        <div class="stat-box"><h4>Monthly Burn</h4><div class="value">$${totalMonthlyCost.toFixed(2)}</div></div>
        <div class="stat-box"><h4>Active Nodes</h4><div class="value">${activeNodes}</div></div>
        <div class="stat-box"><h4>Persona Phase</h4><div class="value" style="color:var(--gold)">Chief of Staff</div></div>
    `;
}

function renderRenewalTimeline(subscriptions) {
    const tl = document.getElementById('renewal-timeline');
    if (!subscriptions || !subscriptions.subscriptions) { tl.innerHTML = ''; return; }

    const withDates = subscriptions.subscriptions
        .filter(s => s.renewal_date)
        .sort((a, b) => new Date(a.renewal_date) - new Date(b.renewal_date));

    if (!withDates.length) { tl.innerHTML = ''; return; }

    let html = '<h3 class="timeline-header">📅 Upcoming Renewals</h3><div class="timeline-items">';
    withDates.forEach(s => {
        const diff = Math.ceil((new Date(s.renewal_date) - new Date()) / 86400000);
        const cls = diff <= 3 ? 'tl-urgent' : diff <= 7 ? 'tl-soon' : 'tl-ok';
        const dateStr = new Date(s.renewal_date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
        html += `<div class="timeline-item ${cls}">
            <div class="tl-date">${dateStr}</div>
            <div class="tl-name">${s.platform}</div>
            <div class="tl-cost">${s.cost || '—'}</div>
            <div class="tl-days">${diff}d</div>
        </div>`;
    });
    html += '</div>';
    tl.innerHTML = html;
}


function showSecurityAlert(platform, issue) {
    const banner = document.getElementById('security-alert-banner');
    const text = document.getElementById('security-alert-text');
    banner.style.display = 'flex';
    text.innerText = `Sloane is blocked at ${platform}: ${issue}. Founder intervention required.`;
}

async function triggerTool(name) {
    showToast(`Initiating ${name.toUpperCase()} Protocol...`);
    try {
        const response = await fetch(`${API_BASE}/trigger/${name}`, { method: 'POST' });
        if (response.ok) {
            showToast(`🚀 ${name.toUpperCase()} Launched Successfully.`, false);
        } else {
            showToast(`❌ Failed to launch ${name}.`, true);
        }
    } catch (e) {
        showToast("❌ Connection to Synapse Bridge lost.", true);
    }
}

function showToast(message, isError = false) {
    const toast = document.getElementById('toast');
    toast.innerText = message;
    toast.style.background = isError ? "var(--danger)" : "var(--accent)";
    toast.classList.add('show');
    setTimeout(() => toast.classList.remove('show'), 3000);
}

// --- CHAT LOGIC ---
function toggleChat() {
    const chat = document.getElementById('chat-container');
    chat.classList.toggle('active');
    if (chat.classList.contains('active')) {
        document.getElementById('chat-input').focus();
    }
}

async function sendMessage() {
    const input = document.getElementById('chat-input');
    const msgText = input.value.trim();
    if (!msgText) return;

    appendMessage('user', msgText);
    input.value = "";

    try {
        const response = await fetch(`${API_BASE}/api/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: msgText })
        });
        const data = await response.json();
        appendMessage('sloane', data.reply);
    } catch (e) {
        appendMessage('sloane', "I've lost connection to the Bridge, Founder. Check the console.");
    }
}

function appendMessage(role, text) {
    const container = document.getElementById('chat-messages');
    const msgDiv = document.createElement('div');
    msgDiv.className = `message ${role}`;
    msgDiv.innerText = text;
    container.appendChild(msgDiv);
    container.scrollTop = container.scrollHeight;
}

// --- INTERVENTION SYSTEM ---
async function checkIntervention() {
    try {
        const response = await fetch(`${API_BASE}/api/intervention`);
        const data = await response.json();
        const overlay = document.getElementById('intervention-overlay');

        if (data.active) {
            document.getElementById('intervention-service').innerText = data.service || 'Unknown';
            document.getElementById('intervention-issue').innerText = data.issue || 'Unknown';
            document.getElementById('intervention-message').innerText = data.message || 'Sloane needs help.';
            document.getElementById('intervention-url').innerText = data.url || '';
            overlay.style.display = 'flex';
        } else {
            overlay.style.display = 'none';
        }
    } catch (e) {
        // Silent — bridge may be offline
    }
}

async function clearIntervention() {
    try {
        await fetch(`${API_BASE}/api/intervention/clear`, { method: 'POST' });
        document.getElementById('intervention-overlay').style.display = 'none';
        showToast('✅ Mission Resumed. Sloane is back on track.', false);
    } catch (e) {
        showToast('❌ Failed to clear intervention.', true);
    }
}

// Initial Boot & Polling
fetchStatus();
checkIntervention();
setInterval(fetchStatus, 30000);      // Pulse every 30 seconds
setInterval(checkIntervention, 5000);  // Check intervention every 5 seconds
