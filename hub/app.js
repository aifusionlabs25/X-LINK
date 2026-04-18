/** 
 * X-LINK Hub v3.0 — Command Center Protocol
 * Config-driven menu, explicit tool routing, separated status layer.
 */

const API_BASE = "";
const PRIMARY_OPERATOR_NAME = 'Hermes';
let activeHermesJobId = null;
let activeHermesJobSignature = null;
let latestMissionSnapshot = null;
let latestResultsSummary = null;
let lastUserChatMessage = "";
let lastResearchMessage = "";
let lastArchiveMessage = "";
let voiceSupported = false;
let voiceListening = false;
let chatPending = false;
let researchPending = false;
let researchProgressTimers = [];
let micPermissionDenied = false;
let voiceTranscribing = false;
let mediaRecorder = null;
let mediaStream = null;
let voiceChunks = [];
let activeRecordingMimeType = 'audio/webm';
let researchAbortController = null;
let chatUploads = [];
let researchUploads = [];
let archiveUploads = [];
let archivePending = false;
let archiveRunId = null;
let archiveStatusPoller = null;
let archiveStatusSignature = null;
let lastArchivePhase = null;
let lastArchiveFolderName = '';
let latestArchiveArtifacts = {
    summaryPath: '',
    statePath: '',
    folderPath: '',
};
let melPoller = null;
let lastMelTimelineSignature = null;
let micPermissionState = 'unknown';
let lastMicDiagnostics = {
    deviceCount: 0,
    deviceNames: [],
};
let telemetryRefreshInFlight = false;

function captureContainerScrollState(container, threshold = 56) {
    if (!container) {
        return { followLive: true, distanceFromBottom: 0 };
    }
    const distanceFromBottom = Math.max(
        0,
        container.scrollHeight - container.clientHeight - container.scrollTop,
    );
    return {
        followLive: distanceFromBottom <= threshold,
        distanceFromBottom,
    };
}

function restoreContainerScrollState(container, scrollState) {
    if (!container || !scrollState) return;
    if (scrollState.followLive) {
        container.scrollTop = container.scrollHeight;
        return;
    }
    container.scrollTop = Math.max(
        0,
        container.scrollHeight - container.clientHeight - scrollState.distanceFromBottom,
    );
}

// ── Status Polling ────────────────────────────────────────────

async function refreshStatus() {
    try {
        const response = await fetch(`${API_BASE}/api/data`);
        if (!response.ok) throw new Error("Bridge response error");
        const data = await response.json();
        updateUI(data);
        refreshTelemetryPanel();
        refreshMissionTheater();
        refreshLatestResultsCenter();
        setBridgeStatus(true);
    } catch (e) {
        console.warn("📡 Bridge Sync Failed:", e.message);
        setBridgeStatus(false);
    }
}

// ── Workspace Routing ───────────────────────────────────────────

async function switchWorkspace(id) {
    console.log(`[Hub] Switching workspace to: ${id}`);
    
    // Toggle Workspace Panes
    document.querySelectorAll('.workspace-pane').forEach(pane => {
        pane.classList.remove('active');
        pane.style.display = 'none';
    });

    const workspaceMap = {
        home: 'workspace-desk',
        usage_auditor: 'workspace-usage-auditor',
        dojo: 'workspace-dojo',
        mel: 'workspace-mel',
        direct_line: 'chat-container',
        multi_model_research: 'research-container',
        archive_intel: 'archive-container',
    };
    const targetId = workspaceMap[id] || 'workspace-desk';
    const target = document.getElementById(targetId);
    if (target) {
        target.classList.add('active');
        target.style.display = 'block';
    }
    updateHomeSurfaceVisibility(targetId === 'workspace-desk');

    // Toggle Sidebar Active State
    document.querySelectorAll('.sidebar-item').forEach(item => {
        item.classList.remove('active-tool');
    });
    const sideItem = document.getElementById(`side-${id}`);
    if (sideItem) sideItem.classList.add('active-tool');

    document.querySelectorAll('.hero-action').forEach(btn => {
        btn.classList.remove('active-launch');
    });
    const heroMap = {
        mel: '.hero-action[data-workspace=\"mel\"]',
        dojo: '.hero-action[data-workspace=\"dojo\"]',
        direct_line: '.hero-action[data-workspace=\"direct_line\"]',
    };
    const heroBtn = heroMap[id] ? document.querySelector(heroMap[id]) : null;
    if (heroBtn) heroBtn.classList.add('active-launch');

    // Run-specific logic
    if (id === 'dojo') {
        if (typeof initDojo === 'function') {
            await initDojo();
        }
    } else if (id === 'mel') {
        initMel();
    } else if (id === 'direct_line') {
        const input = document.getElementById('chat-input');
        if (input) {
            input.focus();
            autoResizeChatInput(input);
        }
        refreshVaultFeed('chat');
    } else if (id === 'multi_model_research') {
        const input = document.getElementById('research-input');
        if (input) {
            input.focus();
            autoResizeChatInput(input);
        }
        refreshVaultFeed('research');
    } else if (id === 'archive_intel') {
        const input = document.getElementById('archive-input');
        if (input) {
            input.focus();
            autoResizeChatInput(input);
        }
        refreshVaultFeed('archive');
        refreshArchiveStatus();
    } else if (id === 'usage_auditor') {
        refreshStatus();
    } else {
        // Trigger generic backend tools (Usage Auditor, Scout)
        triggerTool(id);
    }
}
window.switchWorkspace = switchWorkspace;

function updateHomeSurfaceVisibility(isHomeActive) {
    document.querySelectorAll('.home-surface').forEach((section) => {
        section.style.display = isHomeActive ? '' : 'none';
    });
}

function setBridgeStatus(online) {
    const text = document.getElementById('bridge-status-text');
    const btn = document.getElementById('bridge-status-btn');
    const pulse = document.getElementById('system-pulse');

    if (online) {
        text.innerText = "Bridge Online";
        btn.style.color = "var(--success)";
        pulse.innerText = "ACTIVE";
        pulse.className = "meta-value pulse-green";
    } else {
        text.innerText = "Bridge Offline";
        btn.style.color = "var(--danger)";
        pulse.innerText = "OFFLINE";
        pulse.className = "meta-value";
    }
}

function updateUI(data) {
    const { audit, briefing, subscriptions } = data;

    if (data.server_time) {
        const time = new Date(data.server_time);
        document.getElementById('sync-time').innerText = time.toLocaleTimeString();
        document.getElementById('sync-status-text').innerText = `Synced ${time.toLocaleTimeString()}`;
    }

    if (data.ollama) {
        const oPulse = document.getElementById('ollama-pulse');
        const oModel = document.getElementById('ollama-model');
        if (oPulse) {
            if (data.ollama.status === 'online') {
                oPulse.innerText = `v${data.ollama.version}`;
                oPulse.className = "meta-value pulse-green";
                oPulse.style.color = "";
                if (oModel) oModel.innerText = data.ollama.model || '';
            } else {
                oPulse.innerText = "OFFLINE";
                oPulse.className = "meta-value";
                oPulse.style.color = "var(--danger)";
                if (oModel) oModel.innerText = '';
            }
        }
    }

    if (data.hermes_operator) {
        const hPulse = document.getElementById('hermes-pulse');
        const hSub = document.getElementById('hermes-subvalue');
        const recentMission = (data.hermes_operator.recent_missions || [])[0] || null;
        if (hPulse) {
            hPulse.innerText = "ONLINE";
            hPulse.className = "meta-value pulse-green";
        }
        if (hSub) {
            hSub.innerText = recentMission
                ? `${String(recentMission.intent || 'general_chat').replace(/_/g, ' ')} • ${recentMission.status || 'active'}`
                : "Planning and mission memory active";
        }
    }

    // Hermes command summary
    if (briefing && briefing.sloane) {
        document.getElementById('sloane-summary').innerText = `"${briefing.sloane.summary}"`;
        const depts = briefing.departments;
        if (depts) {
            updateDept("rd", depts.rd);
            updateDept("sales", depts.sales);
            updateDept("ops", depts.ops);
        }
        if (briefing.sloane.agent_evals) {
            renderEvalGrid(briefing.sloane.agent_evals, data.agents || []);
        }
    }

    // Audit Grid
    if (audit) renderAuditGrid(audit, subscriptions);

    // Renewal Timeline
    if (subscriptions) renderRenewalTimeline(subscriptions);

    // Agent Sync Metadata
    if (data.agents) {
        window.agents_metadata = data.agents;
        updateAgentSyncUI(data.agents);
    }
}

async function refreshMissionTheater() {
    try {
        const jobsRes = await fetch(`${API_BASE}/api/hermes/jobs`);
        if (!jobsRes.ok) throw new Error("Mission jobs unavailable");
        const jobsData = await jobsRes.json();
        const jobs = jobsData.jobs || [];
        const job = activeHermesJobId
            ? jobs.find(j => j.job_id === activeHermesJobId) || jobs[0]
            : jobs[0];

        if (!job) {
            renderMissionTheater(null, null, null);
            return;
        }

        activeHermesJobId = job.job_id;
        const evalBatchId = job.spec?.eval?.batch_id;
        const [melRes, dojoRes] = await Promise.all([
            fetch(`${API_BASE}/api/mel/progress`).catch(() => null),
            fetch(`${API_BASE}/api/dojo/session${evalBatchId ? `?batch_id=${encodeURIComponent(evalBatchId)}` : ""}`).catch(() => null),
        ]);

        const mel = melRes && melRes.ok ? await melRes.json() : null;
        const dojo = dojoRes && dojoRes.ok ? await dojoRes.json() : null;
        renderMissionTheater(job, mel, dojo);
        maybeStreamHermesMissionUpdate(job);
    } catch (e) {
        console.warn("[Mission Theater] refresh failed:", e.message);
    }
}

function renderMissionTheater(job, mel, dojo) {
    const pill = document.getElementById('mission-status-pill');
    const jobIdEl = document.getElementById('mission-job-id');
    const targetEl = document.getElementById('mission-target');
    const familyEl = document.getElementById('mission-family');
    const detailEl = document.getElementById('mission-detail');
    const subdetailEl = document.getElementById('mission-subdetail');
    const signalList = document.getElementById('mission-signal-list');
    const pulse = document.getElementById('mission-pulse');
    const bars = document.getElementById('signal-bars');
    const ownerEl = document.getElementById('mission-owner');
    const intentEl = document.getElementById('mission-intent');
    const rollbackEl = document.getElementById('mission-rollback');
    if (!pill || !jobIdEl || !targetEl || !familyEl || !detailEl || !subdetailEl || !signalList) return;

    document.querySelectorAll('.mission-node').forEach(node => {
        node.classList.remove('is-active', 'is-done', 'is-error', 'is-waiting');
    });

    if (!job) {
        pill.innerText = "Idle";
        pill.className = "mission-status-pill";
        jobIdEl.innerText = "No mission yet";
        targetEl.innerText = "Awaiting dispatch";
        familyEl.innerText = "Validation idle";
        detailEl.innerText = "Dispatch a Hermes mission from the console to watch the workflow move through the system.";
        subdetailEl.innerText = "No active telemetry.";
        if (ownerEl) ownerEl.innerText = "Hermes awaiting mission";
        if (intentEl) intentEl.innerText = "No active intent";
        if (rollbackEl) rollbackEl.innerText = "No checkpoint";
        signalList.innerHTML = '<div class="signal-line">No live mission heartbeat yet.</div>';
        if (pulse) pulse.style.left = '0%';
        if (bars) bars.classList.remove('bars-live');
        return;
    }

    latestMissionSnapshot = { job, mel, dojo };
    const steps = job.steps || {};
    const order = ['preflight', 'sh_lab', 'xagent_eval', 'report', 'email'];
    const statuses = order.map(key => ({
        key,
        status: steps[key]?.status || 'pending'
    }));
    let activeIndex = statuses.findIndex(s => s.status === 'running');
    if (activeIndex < 0) activeIndex = statuses.findIndex(s => s.status === 'waiting_for_approval');

    statuses.forEach(({ key, status }, idx) => {
        const node = document.querySelector(`.mission-node[data-step="${key}"]`);
        if (!node) return;
        if (status === 'done') node.classList.add('is-done');
        else if (status === 'running') node.classList.add('is-active');
        else if (status === 'error' || status === 'cancelled') node.classList.add('is-error');
        else if (status === 'waiting_for_approval') node.classList.add('is-waiting');
        if (activeIndex < 0 && status === 'done' && idx === statuses.length - 1) node.classList.add('is-done');
    });

    const phase = job.phase || 'queued';
    const phaseLabel = phase.replace(/_/g, ' ');
    pill.innerText = phaseLabel.toUpperCase();
    pill.className = `mission-status-pill phase-${phase}`;
    jobIdEl.innerText = job.job_id || job.mission_id || 'unknown';
    targetEl.innerText = (job.spec?.target_agent || job.target_agent || 'unknown').toUpperCase();
    familyEl.innerText = job.spec?.validation_profile?.family_label || 'Unknown family';
    if (ownerEl) ownerEl.innerText = String(job.owner_agent || 'Hermes').replace(/_/g, ' ').toUpperCase();
    if (intentEl) intentEl.innerText = String(job.intent || 'general_chat').replace(/_/g, ' ');
    if (rollbackEl) {
        const rollback = job.rollback_checkpoint || {};
        rollbackEl.innerText = rollback.recommended ? (rollback.reason || 'Checkpoint recommended') : (rollback.reason || 'No checkpoint required');
    }

    const melDetail = mel?.events?.length ? mel.events[mel.events.length - 1]?.detail : null;
    const dojoDetail = dojo?.session?.review_step || null;
    const currentStep = job.active_step || (activeIndex >= 0 ? statuses[activeIndex].key : phase);
    detailEl.innerText = melDetail || dojoDetail || `Current phase: ${phaseLabel}`;

    subdetailEl.innerText = `Current step: ${String(currentStep).replace(/_/g, ' ')}${mel?.last_pct ? ` • MEL ${mel.last_pct}%` : ''}${dojo?.session?.review_progress ? ` • Eval ${dojo.session.review_progress}%` : ''}`;

    const signalLines = [];
    if (steps.preflight?.checks) {
        const checks = steps.preflight.checks;
        signalLines.push(`Preflight: Ollama ${checks.ollama ? 'online' : 'offline'}, Dojo ${checks.dojo ? 'online' : 'offline'}, Hub ${checks.hub ? 'online' : 'offline'}`);
    }
    if (job.owner_agent || job.intent) signalLines.push(`Hermes: ${String(job.owner_agent || 'hermes')} • intent ${String(job.intent || 'general_chat').replace(/_/g, ' ')}`);
    if (melDetail) signalLines.push(`SH Lab: ${melDetail}`);
    if (dojo?.session?.status) signalLines.push(`Eval: ${dojo.session.status}${dojo.session.review_step ? ` • ${dojo.session.review_step}` : ''}`);
    if (job.results?.release_readiness?.recommendation) signalLines.push(`Release read: ${job.results.release_readiness.recommendation}`);
    if (job.rollback_checkpoint?.recommended) signalLines.push(`Rollback: ${job.rollback_checkpoint.reason || 'Checkpoint recommended before risky changes'}`);
    if (!signalLines.length) signalLines.push(`Mission ${job.job_id} is ${phaseLabel}.`);
    signalList.innerHTML = signalLines.slice(0, 4).map(line => `<div class="signal-line">${line}</div>`).join('');

    const progressRatio = activeIndex >= 0 ? activeIndex / Math.max(order.length - 1, 1) : (phase === 'completed' ? 1 : 0);
    if (pulse) pulse.style.left = `${Math.min(96, Math.max(2, progressRatio * 96))}%`;
    if (bars) bars.classList.toggle('bars-live', ['running', 'planning', 'reporting'].includes(phase));
}

function maybeStreamHermesMissionUpdate(job) {
    const phase = job.phase || 'queued';
    const activeStep = Object.entries(job.steps || {}).find(([, step]) => step?.status === 'running');
    const stepKey = job.active_step || activeStep?.[0] || phase;
    const detail = activeStep?.[1]?.progress?.detail || stepKey;
    const signature = `${job.job_id}|${phase}|${stepKey}`;
    if (!activeHermesJobSignature) {
        activeHermesJobSignature = signature;
        return;
    }
    if (signature === activeHermesJobSignature) return;
    activeHermesJobSignature = signature;
    appendMessage(PRIMARY_OPERATOR_NAME, `Hermes mission ${job.job_id} update: ${phase.replace(/_/g, ' ')} • ${detail}`);
}

function updateAgentSyncUI(agents) {
    // This could update the Dojo agent select or a separate status panel
    const select = document.getElementById('dojo-agent-select');
    if (select) {
        // We can add the last sync time to the options or a separate tooltip
        agents.forEach(a => {
            const option = Array.from(select.options).find(o => o.value === a.slug);
            if (option && a.last_synced) {
                const date = new Date(a.last_synced).toLocaleString([], {month: 'short', day: 'numeric', hour: '2-digit', minute:'2-digit'});
                option.innerText = `${a.name} (Synced ${date})`;
            }
        });
    }

    // Populate Sidebar Sync Dropdown
    const syncTarget = document.getElementById('anam-sync-target');
    if (syncTarget) {
        syncTarget.innerHTML = '<option value="all">Sync All Agents</option>';
        agents.forEach(a => {
            const opt = document.createElement('option');
            opt.value = a.slug;
            opt.innerText = a.name;
            syncTarget.appendChild(opt);
        });
    }
}

function renderEvalGrid(evals, agents = []) {
    const grid = document.getElementById('briefing-evals-grid');
    if (!grid) return;
    
    grid.innerHTML = evals.map(e => {
        const v = e.verdict || 'N/A';
        const verdictClass = v === 'SHIP' ? 'verdict-ship' : (v === 'NO-SHIP' ? 'verdict-no-ship' : 'verdict-na');
        const score = Math.round(e.score);
        
        // Find matching agent
        const searchName = String(e.target_agent || e.agent || '').toLowerCase();
        const agentMetadata = agents.find(a => String(a.slug || '').toLowerCase() === searchName);
        let syncHtml = '';
        if (agentMetadata && agentMetadata.last_synced) {
            const dateStr = new Date(agentMetadata.last_synced).toLocaleString(undefined, {month:'short', day:'numeric', hour:'numeric', minute:'2-digit'});
            syncHtml = `<div class="eval-sync-status" style="font-size:0.65rem; color:var(--success-color); margin-top:4px;">🧬 Synced: ${dateStr}</div>`;
        }

        return `
            <div class="eval-mini-card" onclick="switchToEval('${e.batch_id}')" style="cursor: pointer;">
                <div class="eval-agent-name">${e.agent}</div>
                <div class="eval-stats">
                    <div class="eval-score">${score}</div>
                    <div class="eval-verdict ${verdictClass}">${v}</div>
                </div>
                <div class="eval-count">${e.tests} tests combined</div>
                ${syncHtml}
            </div>
        `;
    }).join('');
}

function switchToEval(batchId) {
    if (!batchId) return;
    switchWorkspace('dojo');
    // We assume dojo.js is loaded and these are global
    if (typeof loadBatchResults === 'function') {
        loadBatchResults(batchId);
    }
    if (typeof switchDojoTab === 'function') {
        switchDojoTab('results');
    }
}
window.switchToEval = switchToEval;

function updateDept(id, data) {
    const summary = document.getElementById(`${id}-summary`);
    const list = document.getElementById(`${id}-priorities`);
    if (summary && data) {
        summary.innerText = data.summary;
        list.innerHTML = (data.priorities || []).map(p => `<li>${p}</li>`).join('');
    }
}

// ── Audit Grid ────────────────────────────────────────────────

function renderAuditGrid(audit, subscriptions) {
    const grid = document.getElementById('audit-grid');
    const hero = document.getElementById('stats-hero');
    grid.innerHTML = "";

    let totalMonthlyCost = 0;
    let activeNodes = 0;

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
        let mainMetric = resolveAuditMetric(result);

        const subKey = nameMap[name] || name;
        const sub = subLookup[subKey] || {};
        const plan = sub.plan || '—';
        const cost = sub.cost || '—';

        if (cost && cost !== '—') {
            const costVal = parseFloat(cost.replace(/[^0-9.]/g, ''));
            if (!isNaN(costVal)) totalMonthlyCost += costVal;
        }

        if (result.status === "blocked") {
            card.style.borderColor = "var(--danger)";
            mainMetric = "AUTH WALL";
            showSecurityAlert(name, result.issue);
        }

        card.innerHTML = `
            <div class="card-top-row">
                <span class="plan-badge">${plan}</span>
                <span class="cost-badge">${cost}</span>
            </div>
            <h3 class="platform-name">${name}</h3>
            <div class="metric-value">${mainMetric}</div>
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

function resolveAuditMetric(result) {
    const data = result?.data || {};
    if (result?.status === 'blocked') return 'AUTH WALL';
    if (data.error) return 'ERROR';
    if (data.total_spend) return data.total_spend;
    if (data.budget_limit) return data.budget_limit;
    if (data.free_minutes_summary) return `${data.free_minutes_summary} free min`;
    if (data.dashboard_minutes) return data.dashboard_minutes;
    if (data.minutes_used_total) return `${data.minutes_used_total} min used`;
    if (data.conversation_minutes_used) return `${data.conversation_minutes_used} min used`;
    if (data.emails_quota) return data.emails_quota;
    if (data.emails_sent) return data.emails_sent;
    if (data.total_credits) return `${data.total_credits} credits`;
    if (data.credits_remaining) return `${data.credits_remaining} credits left`;
    if (data.credits_found) return `${data.credits_found} credits`;
    if (data.bandwidth_used) return data.bandwidth_used;
    if (data.bandwidth) return data.bandwidth;
    if (data.execution_hours) return data.execution_hours;
    if (Array.isArray(data.accounts) && data.accounts.length) return `${data.accounts.length} billing account${data.accounts.length === 1 ? '' : 's'}`;
    if (data.status === 'no_patterns_matched') return 'DATA CAPTURED';
    return result?.metric_type || 'TELEMETRY...';
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

// ── Tool Triggering ───────────────────────────────────────────

async function syncAnam() {
    const targetSelect = document.getElementById('anam-sync-target');
    const agentSlug = targetSelect ? targetSelect.value : 'all';
    
    if (agentSlug === 'all') {
        showToast("🧬 Initializing Anam Persona Sync (All Agents)...");
    } else {
        showToast(`🧬 Initializing Anam Persona Sync (${agentSlug})...`);
    }

    try {
        const response = await fetch(`${API_BASE}/api/anam/sync`, { 
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ agent: agentSlug })
        });
        const data = await response.json();
        if (response.ok && data.status !== 'error') {
            showToast(`✅ Anam Personas Synced for ${agentSlug.toUpperCase()}`, false);
            refreshStatus();
            if (typeof initDojo === 'function') {
                const prevAgent = document.getElementById('dojo-agent-select')?.value;
                await initDojo();
                if (prevAgent) {
                    document.getElementById('dojo-agent-select').value = prevAgent;
                    if (typeof updateSyncStatus === 'function') updateSyncStatus();
                }
            }
        } else {
            showToast(`❌ Sync Failed: ${data.error || 'Unknown error'}`, true);
        }
    } catch (e) {
        showToast("❌ Bridge offline. Ensure tools/synapse_bridge.py is running.", true);
    }
}
window.syncAnam = syncAnam;

async function runArchivist() {
    showToast("📚 Launching The Great Archivist engine...");
    try {
        const response = await fetch(`${API_BASE}/api/archive/start`, { method: 'POST' });
        const data = await response.json();
        if (response.ok && data.status !== 'error') {
            showToast("✅ Archival sequence initiated. Keep an eye on the Hub for MFA alerts.", false);
        } else {
            showToast(`❌ Archivist Start Failed: ${data.error || 'Unknown error'}`, true);
        }
    } catch (e) {
        showToast("❌ Bridge offline. Ensure tools/synapse_bridge.py is running.", true);
    }
}
window.runArchivist = runArchivist;


async function triggerTool(name) {
    if (['direct_line', 'multi_model_research', 'archive_intel', 'usage_auditor', 'dojo', 'mel', 'home'].includes(name)) {
        switchWorkspace(name);
        return;
    }

    showToast(`Initiating ${name.toUpperCase()} Protocol...`);
    try {
        const response = await fetch(`${API_BASE}/trigger/${name}`, { method: 'POST' });
        if (response.ok) {
            showToast(`🚀 ${name.toUpperCase()} Launched.`, false);
            scheduleToolRefresh(name);
        } else {
            showToast(`❌ Failed to launch ${name}.`, true);
        }
    } catch (e) {
        showToast("❌ Bridge offline. Launch tools/synapse_bridge.py", true);
    }
}

// ── Security Alerts ───────────────────────────────────────────

function scheduleToolRefresh(name) {
    const delays = ['usage_auditor', 'briefing'].includes(name)
        ? [1500, 5000, 10000, 18000]
        : [1500];
    delays.forEach((delay) => {
        setTimeout(() => {
            refreshStatus();
        }, delay);
    });
}

function showSecurityAlert(platform, issue) {
    const banner = document.getElementById('security-alert-banner');
    const text = document.getElementById('security-alert-text');
    banner.style.display = 'flex';
        text.innerText = `Hermes is blocked at ${platform}: ${issue}. Founder intervention required.`;
}

function showToast(message, isError = false) {
    const toast = document.getElementById('toast');
    toast.innerText = message;
    toast.style.background = isError ? "var(--danger)" : "var(--accent)";
    toast.classList.add('show');
    setTimeout(() => toast.classList.remove('show'), 3000);
}

// ── Chat (Direct Line) ───────────────────────────────────────

function toggleChat() {
    const chat = document.getElementById('chat-container');
    if (chat?.classList.contains('active')) {
        switchWorkspace('home');
        return;
    }
    switchWorkspace('direct_line');
}

function syncDockState() {
    const body = document.body;
    if (!body) return;
    body.classList.remove('with-side-panel');
}

function formatSeconds(seconds) {
    const value = Number(seconds || 0);
    if (!Number.isFinite(value) || value <= 0) return '0s';
    if (value < 60) return `${value.toFixed(value >= 10 ? 0 : 1)}s`;
    const minutes = Math.floor(value / 60);
    const remaining = Math.round(value % 60);
    if (minutes < 60) return `${minutes}m ${remaining}s`;
    const hours = Math.floor(minutes / 60);
    return `${hours}h ${minutes % 60}m`;
}

function formatUsd(value) {
    const amount = Number(value || 0);
    if (!Number.isFinite(amount)) return '$0.00';
    if (amount < 0.01 && amount > 0) return `$${amount.toFixed(4)}`;
    return `$${amount.toFixed(2)}`;
}

function formatTokens(value) {
    const amount = Number(value || 0);
    if (!Number.isFinite(amount)) return '0';
    return amount.toLocaleString();
}

function formatPercent(value) {
    const amount = Number(value || 0);
    if (!Number.isFinite(amount)) return '0%';
    return `${amount.toFixed(amount % 1 === 0 ? 0 : 1)}%`;
}

function flattenEstimatedCost(costs) {
    const entries = Object.entries(costs || {});
    if (!entries.length) return '$0.00';
    const total = entries.reduce((sum, [, value]) => sum + Number(value || 0), 0);
    return formatUsd(total);
}

function topEntries(obj, limit = 5, sortBy = (value) => value.calls || 0) {
    return Object.entries(obj || {})
        .sort((a, b) => sortBy(b[1]) - sortBy(a[1]))
        .slice(0, limit);
}

function renderTelemetryCoverage(summary) {
    const note = document.getElementById('telemetry-coverage-note');
    if (!note) return;
    const coverage = summary?.coverage || {};
    const llm = summary?.llm_calls || {};
    const refreshSeconds = coverage.live_refresh_seconds || 30;
    note.innerText = `${coverage.token_note || 'Telemetry coverage note unavailable.'} Live Hub refresh: ${refreshSeconds}s. Current tracked calls: ${formatTokens(llm.count || 0)}.`;
}

function renderTelemetrySummaryCards(summary) {
    const grid = document.getElementById('telemetry-summary-grid');
    if (!grid) return;

    const llm = summary?.llm_calls || {};
    const workflows = summary?.workflows?.by_workflow || {};
    const gpu = summary?.gpu?.latest_sample || {};
    const workflowEntries = Object.entries(workflows);
    const totalWorkflowRuns = workflowEntries.reduce((sum, [, value]) => sum + Number(value.runs || 0), 0);
    const totalWorkflowErrors = workflowEntries.reduce((sum, [, value]) => sum + Number(value.errors || 0), 0);
    const totalWorkflowBlocked = workflowEntries.reduce((sum, [, value]) => sum + Number(value.blocked || 0), 0);
    const cloudEstimate = flattenEstimatedCost(llm.estimated_cloud_cost_usd || {});

    grid.innerHTML = `
        <div class="telemetry-summary-card">
            <span class="telemetry-stat-label">Cloud Equivalent</span>
            <div class="telemetry-stat-value">${cloudEstimate}</div>
            <div class="telemetry-stat-meta">${formatTokens(llm.input_tokens_est || 0)} input est. • ${formatTokens(llm.output_tokens_est || 0)} output est.</div>
        </div>
        <div class="telemetry-summary-card">
            <span class="telemetry-stat-label">LLM Calls</span>
            <div class="telemetry-stat-value">${formatTokens(llm.count || 0)}</div>
            <div class="telemetry-stat-meta">Average runtime ${formatSeconds(llm.average_duration_seconds || 0)}</div>
        </div>
        <div class="telemetry-summary-card">
            <span class="telemetry-stat-label">Workflow Runs</span>
            <div class="telemetry-stat-value">${formatTokens(totalWorkflowRuns)}</div>
            <div class="telemetry-stat-meta">${formatTokens(totalWorkflowErrors)} runtime errors • ${formatTokens(totalWorkflowBlocked)} blocked verdicts</div>
        </div>
        <div class="telemetry-summary-card">
            <span class="telemetry-stat-label">GPU Snapshot</span>
            <div class="telemetry-stat-value">${gpu.gpu_util_percent != null ? formatPercent(gpu.gpu_util_percent) : 'N/A'}</div>
            <div class="telemetry-stat-meta">${gpu.memory_used_mb != null ? `${Math.round(gpu.memory_used_mb)} / ${Math.round(gpu.memory_total_mb || 0)} MB` : 'No GPU sample yet'}${gpu.power_draw_watts != null ? ` • ${Math.round(gpu.power_draw_watts)} W` : ''}</div>
        </div>
    `;
}

function renderTelemetryModelList(summary) {
    const list = document.getElementById('telemetry-model-list');
    if (!list) return;
    const models = topEntries(summary?.llm_calls?.by_model || {}, 6, (value) => value.calls || 0);
    if (!models.length) {
        list.innerHTML = '<div class="telemetry-empty-row">No model telemetry yet.</div>';
        return;
    }
    list.innerHTML = models.map(([key, value]) => {
        const [provider, model] = key.split('::');
        return `
            <div class="telemetry-row">
                <div class="telemetry-row-copy">
                    <strong>${model || key}</strong>
                    <span>${provider || 'unknown'} • ${formatTokens(value.calls || 0)} calls • success ${formatPercent((value.success_rate || 0) * 100)}</span>
                </div>
                <div class="telemetry-row-metric">${formatUsd(Object.values(value.estimated_cloud_cost_usd || {}).reduce((sum, amount) => sum + Number(amount || 0), 0))}<br>${formatSeconds(value.average_duration_seconds || 0)}</div>
            </div>
        `;
    }).join('');
}

function renderTelemetryWorkflowList(summary) {
    const list = document.getElementById('telemetry-workflow-list');
    if (!list) return;
    const workflows = topEntries(summary?.workflows?.by_workflow || {}, 6, (value) => value.runs || 0);
    if (!workflows.length) {
        list.innerHTML = '<div class="telemetry-empty-row">No workflow telemetry yet.</div>';
        return;
    }
    list.innerHTML = workflows.map(([name, value]) => {
        const runs = Number(value.runs || 0);
        const completed = Number(value.completed || 0);
        const errors = Number(value.errors || 0);
        const successRate = runs ? ((completed / runs) * 100) : 0;
        return `
            <div class="telemetry-row">
                <div class="telemetry-row-copy">
                    <strong>${name.replace(/_/g, ' ')}</strong>
                    <span>${formatTokens(runs)} runs • ${formatTokens(errors)} errors • success ${formatPercent(successRate)}</span>
                </div>
                <div class="telemetry-row-metric">${formatSeconds(value.average_duration_seconds || 0)}</div>
            </div>
        `;
    }).join('');
}

function renderTelemetrySlowestRuns(summary) {
    const list = document.getElementById('telemetry-slowest-list');
    if (!list) return;
    const runs = summary?.workflows?.slowest_recent_runs || [];
    if (!runs.length) {
        list.innerHTML = '<div class="telemetry-empty-row">No recent workflow runs yet.</div>';
        return;
    }
    list.innerHTML = runs.map((run) => {
        const metadata = run.metadata || {};
        const metaBits = [];
        if (metadata.agent) metaBits.push(`agent ${metadata.agent}`);
        if (metadata.scenario_pack) metaBits.push(`pack ${metadata.scenario_pack}`);
        if (metadata.pending_id) metaBits.push(`pending ${metadata.pending_id}`);
        return `
            <div class="telemetry-row">
                <div class="telemetry-row-copy">
                    <strong>${(run.workflow || 'workflow').replace(/_/g, ' ')} • ${run.run_id || 'n/a'}</strong>
                    <span>${new Date(run.timestamp).toLocaleString()} • ${run.status || 'unknown'}${metaBits.length ? ` • ${metaBits.join(' • ')}` : ''}</span>
                </div>
                <div class="telemetry-row-metric">${formatSeconds(run.duration_seconds || 0)}</div>
            </div>
        `;
    }).join('');
}

function renderTelemetryFileList(summary) {
    const list = document.getElementById('telemetry-files-list');
    if (!list) return;
    const files = summary?.files || {};
    const entries = Object.entries(files);
    if (!entries.length) {
        list.innerHTML = '<div class="telemetry-empty-row">Waiting for telemetry files...</div>';
        return;
    }
    list.innerHTML = entries.map(([label, path]) => `
        <div class="telemetry-file-row">
            <div class="telemetry-file-copy">
                <strong>${label.replace(/_/g, ' ')}</strong>
                <span>${path}</span>
            </div>
        </div>
    `).join('');
}

function renderTelemetryModelList(summary) {
    const list = document.getElementById('telemetry-model-list');
    if (!list) return;
    const models = topEntries(summary?.llm_calls?.by_model || {}, 6, (value) => value.calls || 0);
    if (!models.length) {
        list.innerHTML = '<div class="telemetry-empty-row">No model telemetry yet.</div>';
        return;
    }
    list.innerHTML = models.map(([key, value]) => {
        const [provider, model] = key.split('::');
        return `
            <div class="telemetry-row">
                <div class="telemetry-row-copy">
                    <strong>${model || key}</strong>
                    <span>${provider || 'unknown'} • ${formatTokens(value.calls || 0)} calls • success ${formatPercent((value.success_rate || 0) * 100)}</span>
                    <span>${formatTokens(value.input_tokens_est || 0)} in • ${formatTokens(value.output_tokens_est || 0)} out</span>
                </div>
                <div class="telemetry-row-metric">${formatUsd((value.estimated_cloud_cost_usd || {}).openai_gpt_4o || 0)} 4o<br>${formatUsd((value.estimated_cloud_cost_usd || {}).anthropic_sonnet || 0)} Sonnet<br>${formatUsd((value.estimated_cloud_cost_usd || {}).gemini_2_5_pro || 0)} Gemini</div>
            </div>
        `;
    }).join('');
}

function renderTelemetryCoverage(summary) {
    const note = document.getElementById('telemetry-coverage-note');
    if (!note) return;
    const coverage = summary?.coverage || {};
    const llm = summary?.llm_calls || {};
    const refreshSeconds = coverage.live_refresh_seconds || 30;
    note.innerText = `${coverage.token_note || 'Telemetry coverage note unavailable.'} Live Hub refresh: ${refreshSeconds}s. Current tracked calls: ${formatTokens(llm.count || 0)}.`;
}

function renderTelemetryGpuChart(summary) {
    const chart = document.getElementById('telemetry-gpu-chart');
    const meta = document.getElementById('telemetry-gpu-meta');
    if (!chart || !meta) return;
    const samples = (summary?.gpu?.recent_samples || []).filter((sample) => sample && sample.gpu_util_percent != null);
    if (!samples.length) {
        chart.innerHTML = '<div class="telemetry-empty-row">No recent GPU samples yet.</div>';
        meta.innerText = 'Waiting for recent GPU samples...';
        return;
    }

    const latest = samples[samples.length - 1];
    meta.innerText = `Latest: ${formatPercent(latest.gpu_util_percent || 0)} GPU • ${latest.memory_used_mb != null ? `${Math.round(latest.memory_used_mb)} MB` : 'N/A'} VRAM • ${latest.power_draw_watts != null ? `${Math.round(latest.power_draw_watts)} W` : 'N/A'} • ${latest.temperature_c != null ? `${Math.round(latest.temperature_c)} C` : 'N/A'}`;
    chart.innerHTML = samples.map((sample) => {
        const gpuHeight = Math.max(8, Math.min(100, Number(sample.gpu_util_percent || 0)));
        const memHeight = Math.max(6, Math.min(100, Number(sample.memory_util_percent || 0)));
        const title = `${sample.timestamp || ''} | GPU ${formatPercent(sample.gpu_util_percent || 0)} | VRAM ${formatPercent(sample.memory_util_percent || 0)}`;
        return `<div class="telemetry-gpu-bar" style="height:${gpuHeight}%; --mem-height:${memHeight}%;" title="${title}" aria-label="${title}"></div>`;
    }).join('');
}

function renderTelemetryWorkflowList(summary) {
    const list = document.getElementById('telemetry-workflow-list');
    if (!list) return;
    const workflows = topEntries(summary?.workflows?.by_workflow || {}, 6, (value) => value.runs || 0);
    if (!workflows.length) {
        list.innerHTML = '<div class="telemetry-empty-row">No workflow telemetry yet.</div>';
        return;
    }
    list.innerHTML = workflows.map(([name, value]) => {
        const runs = Number(value.runs || 0);
        const completed = Number(value.completed || 0);
        const errors = Number(value.errors || 0);
        const blocked = Number(value.blocked || 0);
        const completionRate = runs ? ((completed / runs) * 100) : 0;
        return `
            <div class="telemetry-row">
                <div class="telemetry-row-copy">
                    <strong>${name.replace(/_/g, ' ')}</strong>
                    <span>${formatTokens(runs)} runs • ${formatTokens(errors)} runtime errors • ${formatTokens(blocked)} blocked • completion ${formatPercent(completionRate)}</span>
                </div>
                <div class="telemetry-row-metric">${formatSeconds(value.average_duration_seconds || 0)}</div>
            </div>
        `;
    }).join('');
}

async function refreshTelemetryPanel(forceToast = false) {
    if (telemetryRefreshInFlight) return;
    telemetryRefreshInFlight = true;
    try {
        const response = await fetch(`${API_BASE}/api/telemetry/summary`);
        if (!response.ok) {
            throw new Error('Telemetry summary unavailable');
        }
        const summary = await response.json();
        renderTelemetrySummaryCards(summary);
        renderTelemetryCoverage(summary);
        renderTelemetryModelList(summary);
        renderTelemetryWorkflowList(summary);
        renderTelemetryGpuChart(summary);
        renderTelemetrySlowestRuns(summary);
        renderTelemetryFileList(summary);
        if (forceToast) {
            showToast('✅ Telemetry observatory refreshed.');
        }
    } catch (e) {
        const grid = document.getElementById('telemetry-summary-grid');
        if (grid) {
            grid.innerHTML = '<div class="telemetry-empty-card">Telemetry summary unavailable right now.</div>';
        }
        const note = document.getElementById('telemetry-coverage-note');
        if (note) {
            note.innerText = 'Telemetry could not be loaded.';
        }
        ['telemetry-model-list', 'telemetry-workflow-list', 'telemetry-slowest-list', 'telemetry-files-list', 'telemetry-gpu-chart'].forEach((id) => {
            const el = document.getElementById(id);
            if (el) {
                el.innerHTML = '<div class="telemetry-empty-row">Telemetry could not be loaded.</div>';
            }
        });
        if (forceToast) {
            showToast('❌ Failed to refresh telemetry.', true);
        }
    } finally {
        telemetryRefreshInFlight = false;
    }
}
window.refreshTelemetryPanel = refreshTelemetryPanel;

function toggleResearchPanel() {
    const panel = document.getElementById('research-container');
    if (panel?.classList.contains('active')) {
        switchWorkspace('home');
        return;
    }
    switchWorkspace('multi_model_research');
}
window.toggleResearchPanel = toggleResearchPanel;

function toggleArchivePanel() {
    const panel = document.getElementById('archive-container');
    if (panel?.classList.contains('active')) {
        switchWorkspace('home');
        return;
    }
    switchWorkspace('archive_intel');
}
window.toggleArchivePanel = toggleArchivePanel;

function handleChatKey(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        sendMessage();
    }
}
window.handleChatKey = handleChatKey;

function handleResearchKey(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        sendResearchMessage();
    }
}
window.handleResearchKey = handleResearchKey;

function handleArchiveKey(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        sendArchiveMessage();
    }
}
window.handleArchiveKey = handleArchiveKey;

function autoResizeChatInput(el) {
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
}

function setChatInputStatus(text) {
    const status = document.getElementById('chat-input-status');
    if (status) status.innerText = text;
}

function setResearchInputStatus(text) {
    const status = document.getElementById('research-input-status');
    if (status) status.innerText = text;
}

function setArchiveInputStatus(text) {
    const status = document.getElementById('archive-input-status');
    if (status) status.innerText = text;
}

function getUploadsForScope(scope) {
    if (scope === 'research') return researchUploads;
    if (scope === 'archive') return archiveUploads;
    return chatUploads;
}

function setUploadsForScope(scope, uploads) {
    if (scope === 'research') {
        researchUploads = uploads;
    } else if (scope === 'archive') {
        archiveUploads = uploads;
    } else {
        chatUploads = uploads;
    }
}

function formatFileSize(bytes) {
    if (!Number.isFinite(bytes) || bytes < 1024) return `${bytes || 0} B`;
    const units = ['KB', 'MB', 'GB'];
    let value = bytes / 1024;
    let unitIndex = 0;
    while (value >= 1024 && unitIndex < units.length - 1) {
        value /= 1024;
        unitIndex += 1;
    }
    return `${value.toFixed(value >= 10 ? 0 : 1)} ${units[unitIndex]}`;
}

function pathToVaultUrl(absPath) {
    if (!absPath) return '';
    const normalized = absPath.replace(/\\/g, '/');
    const vaultMarker = '/vault/';
    const markerIndex = normalized.toLowerCase().indexOf(vaultMarker);
    if (markerIndex < 0) return '';
    return normalized.slice(markerIndex);
}

function escapeHtml(value) {
    return String(value || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function formatPercentValue(value) {
    return Number.isFinite(Number(value)) ? `${Number(value).toFixed(1)}%` : 'n/a';
}

function formatDisplayDate(value) {
    if (!value) return 'Unknown time';
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return String(value);
    return parsed.toLocaleString();
}

function buildResultLinks(items = []) {
    const safeItems = items.filter(item => item && item.path);
    if (!safeItems.length) {
        return '<span class="result-link muted">No evidence links yet.</span>';
    }
    return safeItems.map(item => {
        const label = escapeHtml(item.label || 'Open');
        const url = pathToVaultUrl(item.path);
        if (url) {
            return `<a class="result-link" href="${url}" target="_blank" rel="noopener noreferrer">${label}</a>`;
        }
        const escapedPath = String(item.path).replace(/\\/g, '\\\\').replace(/'/g, "\\'");
        return `<button class="result-link muted" onclick="copyTextToClipboard('${escapedPath}', '${label} path copied.')">${label} Path</button>`;
    }).join('');
}

function renderMelLatestResult(summary) {
    const headline = document.getElementById('results-mel-headline');
    const meta = document.getElementById('results-mel-meta');
    const body = document.getElementById('results-mel-body');
    const links = document.getElementById('results-mel-links');
    const melHeadline = document.getElementById('mel-latest-headline');
    const melCopy = document.getElementById('mel-latest-copy');
    const melLinks = document.getElementById('mel-latest-links');
    if (!headline || !meta || !body || !links || !melHeadline || !melCopy || !melLinks) return;

    if (!summary || !summary.available) {
        headline.textContent = 'No SH Lab recommendation yet.';
        meta.textContent = 'Launch SuperHero Lab to generate a current verdict packet.';
        body.textContent = 'Latest baseline score, recommended variant, and blocker summary will show up here.';
        links.innerHTML = '<span class="result-link muted">No evidence links yet.</span>';
        melHeadline.textContent = 'No SH Lab verdict packet yet.';
        melCopy.textContent = 'Run a cycle, then this panel will show the latest baseline, best challenger, and direct evidence links.';
        melLinks.innerHTML = '<span class="result-link muted">No verdict links yet.</span>';
        return;
    }

    const improvement = Number(summary.best_improvement || 0);
    const verdictLabel = summary.passes_threshold ? 'approval-ready' : 'review required';
    const headlineText = `${String(summary.agent_slug || 'Agent').toUpperCase()} • ${summary.best_variant === 'baseline' ? 'Baseline still leads' : `${summary.best_variant} is leading`} • ${formatPercentValue(summary.best_score)}`;
    const metaText = `${formatDisplayDate(summary.created_at)} • baseline ${formatPercentValue(summary.baseline_score)} • delta ${improvement > 0 ? '+' : ''}${improvement.toFixed(1)}% • ${verdictLabel}`;
    const bodyText = summary.failure_category
        ? `Primary blocker: ${String(summary.failure_category).replace(/_/g, ' ')}. ${summary.rationale || summary.failed_exchange || 'Open the evidence links for the full packet and batch summary.'}`
        : (summary.rationale || 'Open the evidence links for the full packet and batch summary.');
    const linkMarkup = buildResultLinks([
        { label: 'Pending Packet', path: summary.source_path || summary.artifacts?.pending_path },
        { label: 'Recommended Batch', path: summary.artifacts?.recommended_batch_summary_path },
        { label: 'Baseline Batch', path: summary.artifacts?.baseline_batch_summary_path },
        { label: 'Session Log', path: summary.artifacts?.latest_log_path },
    ]);

    headline.textContent = headlineText;
    meta.textContent = metaText;
    body.textContent = bodyText;
    links.innerHTML = linkMarkup;
    melHeadline.textContent = headlineText;
    melCopy.textContent = bodyText;
    melLinks.innerHTML = linkMarkup;
}

function renderMissionLatestResult(summary) {
    const headline = document.getElementById('results-mission-headline');
    const meta = document.getElementById('results-mission-meta');
    const body = document.getElementById('results-mission-body');
    const links = document.getElementById('results-mission-links');
    if (!headline || !meta || !body || !links) return;

    if (!summary || !summary.available) {
        headline.textContent = 'No Hermes mission has reported yet.';
        meta.textContent = 'Run SH Lab or X-Agent Eval to populate the mission inspector.';
        body.textContent = 'Latest mission recommendation and report links will appear here.';
        links.innerHTML = '<span class="result-link muted">No evidence links yet.</span>';
        return;
    }

    headline.textContent = `${String(summary.target_agent || 'agent').toUpperCase()} • ${String(summary.phase || 'unknown').replace(/_/g, ' ')} • ${summary.family_label || 'Unclassified lane'}`;
    meta.textContent = `${summary.job_id || 'unknown job'} • updated ${formatDisplayDate(summary.updated_at || summary.created_at)}`;
    body.textContent = summary.recommendation || summary.quick_read || 'Open the artifacts for the full report.';
    links.innerHTML = buildResultLinks([
        { label: 'Report', path: summary.artifacts?.report_text },
        { label: 'SH Lab Batch', path: summary.artifacts?.sh_lab_batch_summary },
        { label: 'X-Agent Eval Batch', path: summary.artifacts?.xagent_eval_batch_summary },
        { label: 'SH Lab Pending', path: summary.artifacts?.sh_lab_pending },
    ]);
}

async function refreshLatestResultsCenter(showToastOnComplete = false) {
    try {
        const response = await fetch(`${API_BASE}/api/hub/latest-results`);
        if (!response.ok) throw new Error(`Latest results ${response.status}`);
        const data = await response.json();
        latestResultsSummary = data;
        renderMissionLatestResult(data.mission);
        renderMelLatestResult(data.mel);
        if (showToastOnComplete) {
            showToast('Latest results refreshed.');
        }
    } catch (error) {
        renderMissionLatestResult(null);
        renderMelLatestResult(null);
        if (showToastOnComplete) {
            showToast('Failed to refresh latest results.', true);
        }
    }
}
window.refreshLatestResultsCenter = refreshLatestResultsCenter;

async function copyTextToClipboard(text, successMessage = 'Copied to clipboard.') {
    if (!text) {
        showToast('Nothing to copy yet.', true);
        return;
    }
    try {
        await navigator.clipboard.writeText(text);
        showToast(successMessage, false);
    } catch (error) {
        showToast('Clipboard copy failed on this browser tab.', true);
    }
}

async function copyArchivePath(kind) {
    if (kind === 'summary') {
        await copyTextToClipboard(latestArchiveArtifacts.summaryPath, 'Summary path copied.');
        return;
    }
    if (kind === 'state') {
        await copyTextToClipboard(latestArchiveArtifacts.statePath, 'Run state path copied.');
        return;
    }
    await copyTextToClipboard(latestArchiveArtifacts.folderPath, 'Archive folder path copied.');
}
window.copyArchivePath = copyArchivePath;

function openUploadPicker(scope) {
    const input = document.getElementById(`${scope}-file-input`);
    input?.click();
}
window.openUploadPicker = openUploadPicker;

function renderUploadList(scope) {
    const list = document.getElementById(`${scope}-upload-list`);
    if (!list) return;
    const uploads = getUploadsForScope(scope);
    list.innerHTML = '';
    list.hidden = uploads.length === 0;
    uploads.forEach((file, index) => {
        const chip = document.createElement('div');
        chip.className = 'upload-chip';
        chip.innerHTML = `
            <div class="upload-chip-copy">
                <strong>${file.name}</strong>
                <span>${formatFileSize(file.size || 0)}</span>
            </div>
            <button type="button" class="upload-chip-remove" onclick="removeUploadedFile('${scope}', ${index})">Remove</button>
        `;
        list.appendChild(chip);
    });
}

function removeUploadedFile(scope, index) {
    const uploads = [...getUploadsForScope(scope)];
    uploads.splice(index, 1);
    setUploadsForScope(scope, uploads);
    renderUploadList(scope);
}
window.removeUploadedFile = removeUploadedFile;

async function handleFileUpload(event, scope) {
    const input = event.target;
    const files = Array.from(input.files || []);
    if (!files.length) return;

    if (scope === 'research') {
        setResearchInputStatus(`Uploading ${files.length} file(s) into the vault...`);
    } else if (scope === 'archive') {
        setArchiveInputStatus(`Uploading ${files.length} file(s) into the vault...`);
    } else {
        setChatInputStatus(`Uploading ${files.length} file(s) into the vault...`);
    }

    const formData = new FormData();
    formData.append('scope', scope);
    files.forEach(file => formData.append('files', file, file.name));

    try {
        const response = await fetch(`${API_BASE}/api/uploads`, {
            method: 'POST',
            body: formData,
        });
        if (!response.ok) {
            throw new Error(`Upload failed: ${response.status}`);
        }
        const data = await response.json();
        const uploads = [...getUploadsForScope(scope), ...(data.files || [])];
        setUploadsForScope(scope, uploads);
        renderUploadList(scope);
        refreshVaultFeed(scope);
        showToast(`${files.length} file(s) added to the vault.`);
        if (scope === 'research') {
            setResearchInputStatus('Files attached. They will travel with the research prompt.');
        } else if (scope === 'archive') {
            setArchiveInputStatus('Files attached. They will travel with the archive request.');
        } else {
            setChatInputStatus('Files attached. Hermes will receive them with your message.');
        }
    } catch (error) {
        showToast('File upload failed. Please try again.', true);
        if (scope === 'research') {
            setResearchInputStatus('Upload failed. Research prompt is unchanged.');
        } else if (scope === 'archive') {
            setArchiveInputStatus('Upload failed. Archive request is unchanged.');
        } else {
            setChatInputStatus('Upload failed. You can still send a text-only message.');
        }
    } finally {
        input.value = '';
    }
}
window.handleFileUpload = handleFileUpload;

function renderMessageAttachments(target, attachments = []) {
    if (!attachments.length) return;
    const wrap = document.createElement('div');
    wrap.className = 'message-attachment-list';
    attachments.forEach(file => {
        const link = document.createElement(file.url ? 'a' : 'span');
        link.className = 'message-attachment';
        link.textContent = file.name;
        if (file.url) {
            link.href = file.url;
            link.target = '_blank';
            link.rel = 'noopener noreferrer';
        }
        wrap.appendChild(link);
    });
    target.appendChild(wrap);
}

function renderVaultFeed(scope, items = []) {
    const list = document.getElementById(`${scope}-vault-list`);
    if (!list) return;
    list.innerHTML = '';
    if (!items.length) {
        list.innerHTML = '<div class="vault-empty">Nothing recent yet.</div>';
        return;
    }
    items.forEach(item => {
        const row = document.createElement('a');
        row.className = 'vault-file-row';
        row.href = item.url || '#';
        row.target = '_blank';
        row.rel = 'noopener noreferrer';
        row.innerHTML = `
            <div class="vault-file-copy">
                <strong>${item.name}</strong>
                <span>${item.category} • ${new Date(item.modified_at).toLocaleString()}</span>
            </div>
            <span class="vault-file-size">${formatFileSize(item.size || 0)}</span>
        `;
        list.appendChild(row);
    });
}

async function refreshVaultFeed(scope) {
    const targets = scope ? [scope] : ['chat', 'research', 'archive'];
    await Promise.all(targets.map(async (currentScope) => {
        try {
            const response = await fetch(`${API_BASE}/api/vault/recent?scope=${encodeURIComponent(currentScope)}&limit=6`);
            if (!response.ok) throw new Error(`Vault response ${response.status}`);
            const data = await response.json();
            renderVaultFeed(currentScope, data.items || []);
        } catch (error) {
            renderVaultFeed(currentScope, []);
        }
    }));
}
window.refreshVaultFeed = refreshVaultFeed;

function appendTextToChatInput(text) {
    const input = document.getElementById('chat-input');
    if (!input || !text) return;
    const trimmed = text.trim();
    if (!trimmed) return;
    input.value = input.value.trim()
        ? `${input.value.trim()} ${trimmed}`
        : trimmed;
    autoResizeChatInput(input);
    input.focus();
}

function updateVoiceUi(message = null, isError = false) {
    const micBtn = document.getElementById('chat-mic-btn');
    const micLabel = document.getElementById('chat-mic-label');
    const runtimePill = document.getElementById('chat-runtime-pill');
    const micHelpBtn = document.getElementById('chat-mic-help-btn');

    if (!micBtn || !micLabel || !runtimePill || !micHelpBtn) return;

    micBtn.classList.toggle('listening', voiceListening);
    micBtn.classList.toggle('unsupported', !voiceSupported);
    micBtn.disabled = !voiceSupported || voiceTranscribing;
    micLabel.innerText = voiceTranscribing ? 'Working' : (voiceListening ? 'Stop' : 'Speak');
    micHelpBtn.hidden = !micPermissionDenied;

    if (message) {
        runtimePill.innerText = message;
    } else if (micPermissionDenied) {
        runtimePill.innerText = 'Mic blocked';
    } else if (voiceTranscribing) {
        runtimePill.innerText = 'Transcribing';
    } else if (!voiceSupported) {
        runtimePill.innerText = 'Voice unavailable';
    } else if (voiceListening) {
        runtimePill.innerText = 'Recording now';
    } else {
        runtimePill.innerText = 'Voice standby';
    }

    runtimePill.classList.toggle('is-error', !!isError);
    setChatInputStatus(
        voiceListening
            ? 'Recording. Tap Mic again when you are done speaking.'
            : (voiceTranscribing
                ? 'Transcribing your note locally for Hermes...'
            : (micPermissionDenied
                ? 'Brave is blocking mic access. Click Fix Mic, then allow microphone for this Hub tab.'
                : (chatPending ? 'Hermes is working on that request...' : 'Hermes Console is ready.')))
    );
}

async function syncMicrophonePermissionState() {
    if (!navigator.permissions?.query) return;
    try {
        const result = await navigator.permissions.query({ name: 'microphone' });
        micPermissionDenied = result.state === 'denied';
        micPermissionState = result.state;
        updateVoiceUi();
        result.onchange = () => {
            micPermissionDenied = result.state === 'denied';
            micPermissionState = result.state;
            updateVoiceUi();
            refreshMicDiagnostics();
        };
    } catch (error) {
        // Some browsers do not expose microphone permission through the Permissions API.
    }
}

function updateMicDiagnosticsUi() {
    const permissionEl = document.getElementById('mic-permission-value');
    const countEl = document.getElementById('mic-device-count-value');
    const listEl = document.getElementById('mic-device-list-value');
    const recorderEl = document.getElementById('mic-recorder-value');
    if (!permissionEl || !countEl || !listEl || !recorderEl) return;

    permissionEl.innerText = micPermissionState || 'unknown';
    countEl.innerText = String(lastMicDiagnostics.deviceCount || 0);
    listEl.innerText = lastMicDiagnostics.deviceNames?.length
        ? lastMicDiagnostics.deviceNames.join(', ')
        : 'No input devices exposed to this tab.';

    if (voiceTranscribing) {
        recorderEl.innerText = 'Transcribing';
    } else if (voiceListening) {
        recorderEl.innerText = `Recording (${activeRecordingMimeType || 'default'})`;
    } else if (!voiceSupported) {
        recorderEl.innerText = 'Unavailable';
    } else {
        recorderEl.innerText = `Idle (${activeRecordingMimeType || 'default'})`;
    }
}

async function refreshMicDiagnostics(showToastOnComplete = false) {
    if (!navigator.mediaDevices?.enumerateDevices) {
        lastMicDiagnostics = { deviceCount: 0, deviceNames: ['enumerateDevices unavailable'] };
        updateMicDiagnosticsUi();
        return;
    }
    try {
        const devices = await navigator.mediaDevices.enumerateDevices();
        const audioInputs = devices.filter(device => device.kind === 'audioinput');
        lastMicDiagnostics = {
            deviceCount: audioInputs.length,
            deviceNames: audioInputs.map((device, idx) => device.label || `Microphone ${idx + 1}`),
        };
        updateMicDiagnosticsUi();
        if (showToastOnComplete) {
            showToast(`Mic check complete: ${audioInputs.length} input device(s) detected.`);
        }
    } catch (error) {
        lastMicDiagnostics = {
            deviceCount: 0,
            deviceNames: [`diagnostics failed: ${error?.name || 'unknown'}`],
        };
        updateMicDiagnosticsUi();
        if (showToastOnComplete) {
            showToast('Mic check failed. Browser would not enumerate devices.', true);
        }
    }
}

function toggleMicDiagnostics() {
    const panel = document.getElementById('chat-mic-diagnostics');
    if (!panel) return;
    panel.hidden = !panel.hidden;
    if (!panel.hidden) {
        refreshMicDiagnostics();
    }
}
window.toggleMicDiagnostics = toggleMicDiagnostics;

function cleanupMediaRecorder() {
    if (mediaRecorder) {
        mediaRecorder.ondataavailable = null;
        mediaRecorder.onstop = null;
        mediaRecorder.onerror = null;
    }
    mediaRecorder = null;
    if (mediaStream) {
        mediaStream.getTracks().forEach(track => track.stop());
    }
    mediaStream = null;
    voiceChunks = [];
}

function initVoiceInput() {
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
        voiceSupported = false;
        updateVoiceUi('Voice unavailable');
        updateMicDiagnosticsUi();
        return;
    }
    voiceSupported = true;
    updateVoiceUi();
    syncMicrophonePermissionState();
    refreshMicDiagnostics();
}

function pickSupportedRecordingMimeType() {
    const candidates = [
        'audio/webm;codecs=opus',
        'audio/webm',
        'audio/mp4',
        'audio/ogg;codecs=opus',
    ];
    if (!window.MediaRecorder?.isTypeSupported) {
        return '';
    }
    return candidates.find(type => MediaRecorder.isTypeSupported(type)) || '';
}

async function transcribeVoiceBlob(blob) {
    voiceTranscribing = true;
    updateVoiceUi();
    try {
        const formData = new FormData();
        formData.append('audio', blob, 'direct-line.webm');
        const response = await fetch(`${API_BASE}/api/transcribe`, {
            method: 'POST',
            body: formData,
        });
        if (!response.ok) {
            throw new Error(`Transcription failed: ${response.status}`);
        }
        const data = await response.json();
        if (data.text?.trim()) {
            appendTextToChatInput(data.text);
            setChatInputStatus('Voice captured. Edit if needed, then send.');
        } else {
            showToast('I heard audio, but nothing clear came through.', true);
            setChatInputStatus('No transcript detected. Try again with a shorter, clearer note.');
        }
    } catch (error) {
        showToast('Voice transcription failed. Please try again.', true);
        setChatInputStatus('Voice transcription failed. You can still type normally.');
    } finally {
        voiceTranscribing = false;
        updateVoiceUi();
        updateMicDiagnosticsUi();
    }
}

async function startVoiceRecording() {
    try {
        mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        micPermissionDenied = false;
        voiceChunks = [];
        activeRecordingMimeType = pickSupportedRecordingMimeType() || 'audio/webm';
        const recorderOptions = activeRecordingMimeType ? { mimeType: activeRecordingMimeType } : undefined;
        mediaRecorder = recorderOptions
            ? new MediaRecorder(mediaStream, recorderOptions)
            : new MediaRecorder(mediaStream);
        updateMicDiagnosticsUi();
        mediaRecorder.ondataavailable = (event) => {
            if (event.data && event.data.size > 0) {
                voiceChunks.push(event.data);
            }
        };
        mediaRecorder.onerror = () => {
            voiceListening = false;
            cleanupMediaRecorder();
            updateVoiceUi('Voice unavailable', true);
            updateMicDiagnosticsUi();
            showToast('Recording failed. Please try again.', true);
        };
        mediaRecorder.onstop = async () => {
            voiceListening = false;
            const blob = new Blob(voiceChunks, { type: activeRecordingMimeType || 'audio/webm' });
            cleanupMediaRecorder();
            updateVoiceUi();
            updateMicDiagnosticsUi();
            if (blob.size > 0) {
                await transcribeVoiceBlob(blob);
            }
        };
        mediaRecorder.start();
        voiceListening = true;
        updateVoiceUi();
        updateMicDiagnosticsUi();
    } catch (error) {
        micPermissionDenied = error?.name === 'NotAllowedError' || error?.name === 'SecurityError';
        updateVoiceUi(micPermissionDenied ? 'Mic blocked' : 'Voice unavailable', true);
        refreshMicDiagnostics();
        const detailMap = {
            NotAllowedError: 'Brave is blocking microphone access for this Hub tab.',
            SecurityError: 'Brave is blocking microphone access for this Hub tab.',
            NotFoundError: 'No microphone input was detected on this machine.',
            NotReadableError: 'Another app may be holding the microphone right now.',
            AbortError: 'The microphone was interrupted while starting.',
        };
        showToast(
            detailMap[error?.name] || `Microphone capture failed to start (${error?.name || 'unknown'}).`,
            true
        );
    }
}

async function toggleVoiceInput() {
    if (!voiceSupported) {
        showToast('Voice input is not available in this browser session.', true);
        return;
    }
    if (voiceTranscribing) {
        showToast('Still transcribing your last note. Give me a second.', true);
        return;
    }
    if (voiceListening) {
        mediaRecorder?.stop();
        return;
    }
    await startVoiceRecording();
}
window.toggleVoiceInput = toggleVoiceInput;

function openMicHelp() {
    const origin = window.location.origin;
    const instructions = [
        'Brave microphone unlock:',
        `1. Click the site controls icon to the left of ${origin}.`,
        '2. Open Site settings.',
        '3. Change Microphone to Allow.',
        '4. Refresh the Hub tab.',
        '5. Click Mic again.',
    ].join('\n');
    alert(instructions);
    showToast('Open the site controls beside the address bar, allow Microphone, then refresh this tab.');
}
window.openMicHelp = openMicHelp;

function setChatPendingState(isPending) {
    chatPending = isPending;
    const sendBtn = document.getElementById('send-btn');
    const editBtn = document.getElementById('chat-edit-btn');
    if (sendBtn) {
        sendBtn.disabled = isPending;
        sendBtn.innerText = isPending ? 'Sending...' : 'Send';
    }
    if (editBtn) editBtn.disabled = isPending;
    updateVoiceUi();
}

function setResearchPendingState(isPending) {
    researchPending = isPending;
    const sendBtn = document.getElementById('research-send-btn');
    const editBtn = document.getElementById('research-edit-btn');
    const stopBtn = document.getElementById('research-stop-btn');
    const pill = document.getElementById('research-status-pill');

    if (sendBtn) {
        sendBtn.disabled = isPending;
        sendBtn.innerText = isPending ? 'Running...' : 'Send';
    }
    if (editBtn) editBtn.disabled = isPending;
    if (stopBtn) stopBtn.disabled = !isPending && !researchAbortController;
    if (pill) {
        pill.innerText = isPending ? 'Researching' : 'Standby';
        pill.classList.toggle('busy', isPending);
    }
}

function setArchivePendingState(isPending) {
    archivePending = isPending;
    const sendBtn = document.getElementById('archive-send-btn');
    const editBtn = document.getElementById('archive-edit-btn');
    const stopBtn = document.getElementById('archive-stop-btn');
    const pill = document.getElementById('archive-status-pill');
    const inputStatus = document.getElementById('archive-input-status');
    if (sendBtn) {
        sendBtn.disabled = isPending;
        sendBtn.innerText = isPending ? 'Running...' : 'Run';
    }
    if (editBtn) editBtn.disabled = isPending;
    if (stopBtn) stopBtn.disabled = !isPending;
    if (pill) {
        pill.innerText = isPending ? 'Archiving' : (archiveRunId ? 'Tracking' : 'Standby');
        pill.classList.toggle('busy', isPending);
    }
}

function clearResearchProgressTimer() {
    researchProgressTimers.forEach(timer => clearTimeout(timer));
    researchProgressTimers = [];
}

function scheduleResearchProgressUpdates() {
    clearResearchProgressTimer();
    const steps = [
        { delay: 0, status: 'Opening fresh sessions across ChatGPT, Perplexity, Gemini, and Grok...', note: 'Fresh sessions requested on all providers.' },
        { delay: 4000, status: 'Dispatching the same research question into each provider...', note: 'Multi-model sweep in flight.' },
        { delay: 12000, status: 'Waiting for the providers to finish their first-pass reasoning...', note: 'Collecting model outputs.' },
        { delay: 24000, status: 'Hermes will judge the spread and turn it into one operator brief next...', note: 'Preparing Hermes synthesis.' },
    ];
    steps.forEach(({ delay, status, note }, index) => {
        const timer = setTimeout(() => {
            if (!researchPending) return;
            setResearchInputStatus(status);
            if (index === 0 || index === 2) {
                appendResearchMessage(PRIMARY_OPERATOR_NAME, note);
            }
        }, delay);
        researchProgressTimers.push(timer);
    });
}

function seedChatPrompt(text) {
    const input = document.getElementById('chat-input');
    if (!input) return;
    if (!document.getElementById('chat-container').classList.contains('active')) {
        switchWorkspace('direct_line');
    }
    input.value = text;
    autoResizeChatInput(input);
    input.focus();
}
window.seedChatPrompt = seedChatPrompt;

function seedResearchPrompt(text) {
    const input = document.getElementById('research-input');
    if (!input) return;
    if (!document.getElementById('research-container').classList.contains('active')) {
        switchWorkspace('multi_model_research');
    }
    input.value = text;
    autoResizeChatInput(input);
    input.focus();
}
window.seedResearchPrompt = seedResearchPrompt;

function seedArchivePrompt(text) {
    const input = document.getElementById('archive-input');
    if (!input) return;
    if (!document.getElementById('archive-container').classList.contains('active')) {
        switchWorkspace('archive_intel');
    }
    input.value = text;
    autoResizeChatInput(input);
    input.focus();
}
window.seedArchivePrompt = seedArchivePrompt;

async function sendMessage() {
    const input = document.getElementById('chat-input');
    const msgText = input.value.trim();
    if (!msgText || chatPending) return;
    const attachments = [...chatUploads];

    if (voiceListening && mediaRecorder) {
        mediaRecorder.stop();
    }

    lastUserChatMessage = msgText;
    appendMessage('user', msgText, attachments);
    input.value = "";
    autoResizeChatInput(input);
    setChatPendingState(true);

    try {
        const response = await fetch(`${API_BASE}/api/hermes/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: msgText, attachments })
        });
        if (!response.ok) {
            throw new Error(`Bridge response ${response.status}`);
        }
        const data = await response.json();
        if (data.job_id) {
            activeHermesJobId = data.job_id;
            activeHermesJobSignature = null;
            refreshMissionTheater();
        }
        appendMessage(data.agent || PRIMARY_OPERATOR_NAME, data.reply);
        chatUploads = [];
        renderUploadList('chat');
        refreshVaultFeed('chat');
    } catch (e) {
        appendMessage(PRIMARY_OPERATOR_NAME, "I've lost connection to the Bridge, Founder. Check the console.");
    } finally {
        setChatPendingState(false);
    }
}

function appendResearchMessage(role, text, attachments = []) {
    const container = document.getElementById('research-messages');
    if (!container) return;
    const msgDiv = document.createElement('div');
    const normalized = normalizeOperatorRole(role);
    msgDiv.className = `message ${normalized.cssRole}`;

    const meta = document.createElement('div');
    meta.className = 'message-meta';
    const roleLabel = document.createElement('span');
    roleLabel.className = 'message-role';
    roleLabel.innerText = normalized.label;
    meta.appendChild(roleLabel);

    const content = document.createElement('div');
    content.className = 'message-content';
    content.innerText = text;

    msgDiv.appendChild(meta);
    msgDiv.appendChild(content);
    renderMessageAttachments(msgDiv, attachments);
    container.appendChild(msgDiv);
    container.scrollTop = container.scrollHeight;
}

function updateResearchArtifactLabel(path, provider, model) {
    const artifact = document.getElementById('research-artifact-label');
    const providerLabel = document.getElementById('research-provider-label');
    if (artifact) {
        artifact.innerText = path ? path.split(/[\\/]/).pop() : 'No report yet';
    }
    if (providerLabel) {
        providerLabel.innerText = provider
            ? `${provider}${model ? ` • ${model}` : ''}`
            : 'Waiting for dispatch';
    }
    if (path) {
        refreshVaultFeed('research');
    }
}

async function sendResearchMessage() {
    const input = document.getElementById('research-input');
    const msgText = input.value.trim();
    if (!msgText || researchPending) return;
    const attachments = [...researchUploads];

    lastResearchMessage = msgText;
    appendResearchMessage('user', msgText, attachments);
    input.value = "";
    autoResizeChatInput(input);
    setResearchPendingState(true);
    setResearchInputStatus('Opening fresh sessions across the research providers...');
    appendResearchMessage(PRIMARY_OPERATOR_NAME, 'Dispatch acknowledged. I am opening fresh sessions on ChatGPT, Perplexity, Gemini, and Grok before sending the query.');
    scheduleResearchProgressUpdates();
    researchAbortController = new AbortController();

    try {
        const response = await fetch(`${API_BASE}/api/research/multi-model`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query: msgText, attachments }),
            signal: researchAbortController.signal,
        });
        if (!response.ok) {
            throw new Error(`Research response ${response.status}`);
        }
        const data = await response.json();
        appendResearchMessage(PRIMARY_OPERATOR_NAME, data.reply || 'Research completed, but no summary was returned.');
        updateResearchArtifactLabel(data.artifact_path, data.synthesis_provider, data.synthesis_model);
        setResearchInputStatus('Research brief ready.');
        researchUploads = [];
        renderUploadList('research');
        refreshVaultFeed('research');
    } catch (e) {
        if (e.name === 'AbortError') {
            appendResearchMessage(PRIMARY_OPERATOR_NAME, 'Research request stopped on the Hub side. If the backend already started, it may still finish in the background.');
            setResearchInputStatus('Research halted locally.');
        } else {
            appendResearchMessage(PRIMARY_OPERATOR_NAME, 'The research lane lost contact with the Bridge before I could return the brief.');
            setResearchInputStatus('Research failed. Check the bridge logs.');
        }
    } finally {
        clearResearchProgressTimer();
        researchAbortController = null;
        setResearchPendingState(false);
    }
}
window.sendResearchMessage = sendResearchMessage;

function editLastResearchMessage() {
    const input = document.getElementById('research-input');
    if (!input || !lastResearchMessage) return;
    input.value = lastResearchMessage;
    autoResizeChatInput(input);
    input.focus();
}
window.editLastResearchMessage = editLastResearchMessage;

function stopResearchRequest() {
    if (!researchPending || !researchAbortController) {
        appendResearchMessage(PRIMARY_OPERATOR_NAME, 'There is no active research sweep to stop at the moment.');
        return;
    }
    researchAbortController.abort();
}
window.stopResearchRequest = stopResearchRequest;

function appendArchiveMessage(role, text, attachments = []) {
    const container = document.getElementById('archive-messages');
    if (!container) return;
    const msgDiv = document.createElement('div');
    const normalized = normalizeOperatorRole(role);
    msgDiv.className = `message ${normalized.cssRole}`;

    const meta = document.createElement('div');
    meta.className = 'message-meta';
    const roleLabel = document.createElement('span');
    roleLabel.className = 'message-role';
    roleLabel.innerText = normalized.label;
    meta.appendChild(roleLabel);

    const content = document.createElement('div');
    content.className = 'message-content';
    content.innerText = text;

    msgDiv.appendChild(meta);
    msgDiv.appendChild(content);
    renderMessageAttachments(msgDiv, attachments);
    container.appendChild(msgDiv);
    container.scrollTop = container.scrollHeight;
}

function updateArchiveRunLabels(run) {
    const runLabel = document.getElementById('archive-run-label');
    const phaseLabel = document.getElementById('archive-phase-label');
    const summaryLabel = document.getElementById('archive-summary-label');
    const emailLabel = document.getElementById('archive-email-label');
    const pill = document.getElementById('archive-status-pill');
    const inputStatus = document.getElementById('archive-input-status');
    const summaryFile = document.getElementById('archive-summary-file');
    const folderLabel = document.getElementById('archive-folder-label');
    const openSummary = document.getElementById('archive-open-summary');
    if (!run) {
        if (runLabel) runLabel.innerText = 'No sweep yet';
        if (phaseLabel) phaseLabel.innerText = 'Waiting for dispatch';
        if (summaryLabel) summaryLabel.innerText = 'No summary yet';
        if (emailLabel) emailLabel.innerText = 'Email optional';
        if (inputStatus) inputStatus.innerText = 'Archive lane is ready.';
        if (summaryFile) summaryFile.innerText = 'No summary yet';
        if (folderLabel) folderLabel.innerText = 'No archive folder yet';
        latestArchiveArtifacts = { summaryPath: '', statePath: '', folderPath: '' };
        if (openSummary) {
            openSummary.href = '#';
            openSummary.classList.add('disabled');
        }
        if (pill) {
            pill.innerText = 'Standby';
            pill.classList.remove('busy', 'error');
        }
        return;
    }
    lastArchiveFolderName = run.folder_name || lastArchiveFolderName || '';

    if (runLabel) runLabel.innerText = run.run_id || 'Archive run';
    if (phaseLabel) {
        const phase = (run.phase || run.status || 'queued').replace(/_/g, ' ');
        phaseLabel.innerText = `${phase.charAt(0).toUpperCase()}${phase.slice(1)}${run.detail ? ` • ${run.detail}` : ''}`;
    }
    if (inputStatus) {
        inputStatus.innerText = run.detail || (run.status === 'error'
            ? 'Archive Intel stopped with an error.'
            : run.status === 'completed'
                ? 'Archive Intel finished.'
                : 'Archive Intel is working.');
    }
    if (summaryLabel) {
        summaryLabel.innerText = run.summary_path
            ? run.summary_path.split(/[\\/]/).pop()
            : run.status === 'error'
                ? 'No summary generated'
                : `${(run.saved_files || []).length} file(s) saved`;
    }
    if (emailLabel) {
        if (run.email_sent) {
            emailLabel.innerText = 'Summary email sent';
        } else if (run.email_recipient) {
            emailLabel.innerText = `Email queued for ${run.email_recipient}`;
        } else {
            emailLabel.innerText = 'Local summary only';
        }
    }
    latestArchiveArtifacts.summaryPath = run.summary_path || '';
    latestArchiveArtifacts.statePath = `${'C:\\AI Fusion Labs\\X AGENTS\\REPOS\\X-LINK\\vault\\archives\\_runs'}\\${run.run_id || ''}\\state.json`;
    const firstSaved = (run.saved_files || [])[0] || '';
    latestArchiveArtifacts.folderPath = firstSaved ? firstSaved.split(/[\\/]/).slice(0, -1).join('\\') : '';
    if (summaryFile) {
        summaryFile.innerText = run.summary_path ? run.summary_path.split(/[\\/]/).pop() : 'Summary not generated yet';
    }
    if (folderLabel) {
        folderLabel.innerText = lastArchiveFolderName
            ? `${lastArchiveFolderName}${latestArchiveArtifacts.folderPath ? ` • ${latestArchiveArtifacts.folderPath}` : ''}`
            : (latestArchiveArtifacts.folderPath || 'Archive folder will appear after the first saved file.');
    }
    if (openSummary) {
        const summaryUrl = pathToVaultUrl(run.summary_path || '');
        if (summaryUrl) {
            openSummary.href = summaryUrl;
            openSummary.classList.remove('disabled');
        } else {
            openSummary.href = '#';
            openSummary.classList.add('disabled');
        }
    }
    if (pill) {
        const status = run.status || 'queued';
        pill.innerText = status === 'completed' ? 'Complete' : status === 'error' ? 'Attention' : archivePending ? 'Archiving' : 'Tracking';
        pill.classList.toggle('busy', archivePending || status === 'running');
        pill.classList.toggle('error', status === 'error');
    }
}

function extractArchiveFolderName(text) {
    const prompt = (text || '').trim();
    if (!prompt) return '';
    const patterns = [
        /from\s+"([^"]+)"/i,
        /from\s+'([^']+)'/i,
        /folder\s+"([^"]+)"/i,
        /folder\s+'([^']+)'/i,
        /folder\s+named\s+"([^"]+)"/i,
        /folder\s+named\s+'([^']+)'/i,
        /projects?\s+folder\s+named\s+"([^"]+)"/i,
        /projects?\s+folder\s+named\s+'([^']+)'/i,
    ];
    for (const pattern of patterns) {
        const match = prompt.match(pattern);
        if (match?.[1]) return match[1].trim();
    }
    return '';
}

function inferArchivePlatform(text, fallback = 'all') {
    const prompt = (text || '').trim().toLowerCase();
    if (!prompt) return fallback;
    if (prompt.includes('chatgpt')) return 'chatgpt';
    if (prompt.includes('perplexity')) return 'perplexity';
    if (prompt.includes('gemini')) return 'gemini';
    if (prompt.includes('grok')) return 'grok';
    if (prompt.includes('all providers') || prompt.includes('all chats')) return 'all';
    return fallback;
}

function describeArchiveRun(run) {
    if (!run) return 'No archive run details available yet.';
    const platform = run.current_platform || 'archive lane';
    const detail = run.detail || `${(run.saved_files || []).length} file(s) captured so far.`;
    const title = run.current_title ? ` • ${run.current_title}` : '';
    return `${platform}: ${detail}${title}`;
}

function setArchiveTracking(active) {
    if (archiveStatusPoller) {
        clearInterval(archiveStatusPoller);
        archiveStatusPoller = null;
    }
    if (active && archiveRunId) {
        archiveStatusPoller = setInterval(() => {
            refreshArchiveStatus(archiveRunId);
        }, 3000);
    }
}

async function refreshArchiveStatus(runId = archiveRunId) {
    if (!runId) {
        updateArchiveRunLabels(null);
        return;
    }
    try {
        const response = await fetch(`${API_BASE}/api/archive/status?run_id=${encodeURIComponent(runId)}`);
        if (!response.ok) throw new Error(`Archive status ${response.status}`);
        const run = await response.json();
        archiveRunId = run.run_id || runId;
        updateArchiveRunLabels(run);

        const signature = [run.status, run.phase, run.detail, run.current_platform, run.current_title, (run.saved_files || []).length].join('|');
        if (signature !== archiveStatusSignature) {
            archiveStatusSignature = signature;
            if (run.status === 'completed') {
                appendArchiveMessage(PRIMARY_OPERATOR_NAME, `Archive Intel is complete. ${describeArchiveRun(run)}`);
                if (run.summary_path) {
                    appendArchiveMessage(PRIMARY_OPERATOR_NAME, 'The summary brief is now in the vault strip above, ready to open or forward.');
                }
            } else if (run.status === 'error') {
                appendArchiveMessage(PRIMARY_OPERATOR_NAME, `Archive Intel hit a snag: ${run.detail || 'Unknown failure.'}`);
            } else {
                appendArchiveMessage(PRIMARY_OPERATOR_NAME, describeArchiveRun(run));
            }
        }

        const isActive = !['completed', 'error', 'cancelled', 'stopped'].includes(run.status || '');
        setArchivePendingState(isActive);
        if (!isActive) {
            setArchiveTracking(false);
            refreshVaultFeed('archive');
        }
    } catch (error) {
        setArchiveInputStatus('Archive status is temporarily unavailable.');
        if (archivePending) {
            appendArchiveMessage(PRIMARY_OPERATOR_NAME, 'I lost sight of the archive telemetry for a moment. The run may still be working in the background.');
        }
        setArchiveTracking(false);
        setArchivePendingState(false);
    }
}
window.refreshArchiveStatus = refreshArchiveStatus;

async function sendArchiveMessage() {
    const input = document.getElementById('archive-input');
    const platformSelect = document.getElementById('archive-platform-select');
    const limitSelect = document.getElementById('archive-limit-select');
    const emailToggle = document.getElementById('archive-email-toggle');
    const msgText = input?.value.trim() || '';
    const explicitFolderName = extractArchiveFolderName(msgText);
    const requestedPlatform = inferArchivePlatform(msgText, platformSelect?.value || 'all');
    const folderName = requestedPlatform === 'chatgpt' ? (explicitFolderName || lastArchiveFolderName || '') : '';

    if ((!msgText && archiveUploads.length === 0) || archivePending) return;

    const payload = {
        prompt: msgText,
        platform: requestedPlatform,
        limit: limitSelect?.value || '10',
        email: emailToggle?.checked ? 'aifusionlabs@gmail.com' : '',
        folder_name: folderName,
        attachments: [...archiveUploads],
    };

    if (platformSelect) {
        platformSelect.value = requestedPlatform;
    }

    if (requestedPlatform === 'chatgpt' && explicitFolderName) {
        lastArchiveFolderName = explicitFolderName;
    } else if (requestedPlatform !== 'chatgpt') {
        lastArchiveFolderName = '';
    }
    lastArchiveMessage = msgText;
    appendArchiveMessage('user', msgText || 'Archive request with attachments only.', payload.attachments);
    if (input) {
        input.value = '';
        autoResizeChatInput(input);
    }

    setArchivePendingState(true);
    setArchiveInputStatus('Dispatching the archive sweep and waiting for the first telemetry update...');
    archiveStatusSignature = null;
    lastArchivePhase = null;

    try {
        const response = await fetch(`${API_BASE}/api/archive/start`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (!response.ok) {
            let errorText = `Archive start ${response.status}`;
            try {
                const failure = await response.json();
                errorText = failure?.error || failure?.detail || failure?.message || errorText;
            } catch (_err) {
                // Keep the HTTP fallback text.
            }
            throw new Error(errorText);
        }
        const data = await response.json();
        if (data?.status === 'error' || !data?.run_id) {
            throw new Error(data?.error || data?.detail || data?.message || 'Archive launch returned an invalid response.');
        }
        archiveRunId = data.run_id || null;
        appendArchiveMessage(PRIMARY_OPERATOR_NAME, `Archive Intel dispatched. I am sweeping ${payload.platform === 'all' ? 'all providers' : payload.platform} with a ${payload.limit}-chat depth${payload.email ? ', and I will email the summary when it is done.' : '.'}`);
        archiveUploads = [];
        renderUploadList('archive');
        updateArchiveRunLabels({
            run_id: archiveRunId,
            status: 'running',
            phase: 'dispatch',
            detail: data.message || 'Archive run launched.',
            email_recipient: payload.email || null,
            saved_files: [],
        });
        setArchiveTracking(true);
        refreshArchiveStatus(archiveRunId);
    } catch (error) {
        setArchivePendingState(false);
        const message = error?.message || 'Archive dispatch failed. Check the bridge logs.';
        setArchiveInputStatus(message);
        appendArchiveMessage(PRIMARY_OPERATOR_NAME, `I could not launch Archive Intel cleanly: ${message}`);
    }
}
window.sendArchiveMessage = sendArchiveMessage;

function editLastArchiveMessage() {
    const input = document.getElementById('archive-input');
    if (!input || !lastArchiveMessage) return;
    input.value = lastArchiveMessage;
    autoResizeChatInput(input);
    input.focus();
}
window.editLastArchiveMessage = editLastArchiveMessage;

async function stopArchiveRequest() {
    if (!archiveRunId) {
        appendArchiveMessage(PRIMARY_OPERATOR_NAME, 'There is no active archive sweep to stop at the moment.');
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/api/archive/stop/${encodeURIComponent(archiveRunId)}`, {
            method: 'POST',
        });
        if (!response.ok) {
            throw new Error(`Archive stop ${response.status}`);
        }
        const data = await response.json();
        setArchiveTracking(false);
        setArchivePendingState(false);
        setArchiveInputStatus('Archive sweep stopped.');
        appendArchiveMessage(PRIMARY_OPERATOR_NAME, data.message || `Archive run ${archiveRunId} has been stopped.`);
        refreshArchiveStatus(archiveRunId);
    } catch (error) {
        appendArchiveMessage(PRIMARY_OPERATOR_NAME, 'I could not stop that archive sweep cleanly. Please check the bridge logs.');
    }
}
window.stopArchiveRequest = stopArchiveRequest;

function editLastUserMessage() {
    const input = document.getElementById('chat-input');
    if (!input || !lastUserChatMessage) return;
    input.value = lastUserChatMessage;
    autoResizeChatInput(input);
    input.focus();
}
window.editLastUserMessage = editLastUserMessage;

async function stopActiveMission() {
    if (!activeHermesJobId) {
        appendMessage(PRIMARY_OPERATOR_NAME, "There is no active Hermes mission to stop at the moment.");
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/api/hermes/jobs/${encodeURIComponent(activeHermesJobId)}/cancel`, {
            method: 'POST'
        });
        if (!response.ok) {
            throw new Error(`Cancel failed: ${response.status}`);
        }
        const job = await response.json();
        appendMessage(PRIMARY_OPERATOR_NAME, `Mission ${job.job_id} has been stopped. Current state: ${job.status}.`);
        activeHermesJobSignature = null;
        refreshMissionTheater();
    } catch (e) {
        appendMessage(PRIMARY_OPERATOR_NAME, "I couldn't stop that mission cleanly. Please check the bridge logs.");
    }
}
window.stopActiveMission = stopActiveMission;

function normalizeOperatorRole(role) {
    const raw = String(role || PRIMARY_OPERATOR_NAME).trim();
    const lower = raw.toLowerCase();
    if (lower === 'user' || lower === 'founder') {
        return { cssRole: 'user', label: 'Founder' };
    }
    if (lower === 'hermes' || lower === 'sloane' || lower === 'assistant') {
        return { cssRole: 'sloane', label: PRIMARY_OPERATOR_NAME };
    }
    return { cssRole: lower, label: raw };
}

function appendMessage(role, text, attachments = []) {
    const container = document.getElementById('chat-messages');
    const msgDiv = document.createElement('div');
    const normalized = normalizeOperatorRole(role);
    
    msgDiv.className = `message ${normalized.cssRole}`;

    const meta = document.createElement('div');
    meta.className = 'message-meta';
    const roleLabel = document.createElement('span');
    roleLabel.className = 'message-role';
    roleLabel.innerText = normalized.label;
    meta.appendChild(roleLabel);
    msgDiv.appendChild(meta);

    const content = document.createElement('div');
    content.className = 'message-content';
    content.textContent = text;
    msgDiv.appendChild(content);
    renderMessageAttachments(msgDiv, attachments);
    
    container.appendChild(msgDiv);
    container.scrollTop = container.scrollHeight;
}

document.addEventListener('DOMContentLoaded', () => {
    const startupParams = new URLSearchParams(window.location.search);
    const forceStartupHome = startupParams.get('startup_home') === '1';
    if (forceStartupHome) {
        document.querySelectorAll('.workspace-pane').forEach((pane) => {
            pane.classList.remove('active');
            pane.style.display = 'none';
        });
        const home = document.getElementById('workspace-desk');
        if (home) {
            home.classList.add('active');
            home.style.display = 'block';
        }
        document.querySelectorAll('.sidebar-item').forEach((item) => item.classList.remove('active-tool'));
        updateHomeSurfaceVisibility(true);
        if (window.history && window.history.replaceState) {
            const cleanUrl = `${window.location.pathname}${window.location.hash || ''}`;
            window.history.replaceState({}, document.title, cleanUrl);
        }
    } else {
        updateHomeSurfaceVisibility(true);
    }
    const input = document.getElementById('chat-input');
    if (input) {
        autoResizeChatInput(input);
        input.addEventListener('input', () => autoResizeChatInput(input));
    }
    const researchInput = document.getElementById('research-input');
    if (researchInput) {
        autoResizeChatInput(researchInput);
        researchInput.addEventListener('input', () => autoResizeChatInput(researchInput));
    }
    const archiveInput = document.getElementById('archive-input');
    if (archiveInput) {
        autoResizeChatInput(archiveInput);
        archiveInput.addEventListener('input', () => autoResizeChatInput(archiveInput));
    }
    initVoiceInput();
    updateMicDiagnosticsUi();
    renderUploadList('chat');
    renderUploadList('research');
    renderUploadList('archive');
    refreshVaultFeed();
    refreshArchiveStatus();
    refreshLatestResultsCenter();
});

// ── Intervention System ──────────────────────────────────────

async function checkIntervention() {
    try {
        const response = await fetch(`${API_BASE}/api/intervention`);
        const data = await response.json();
        const overlay = document.getElementById('intervention-overlay');
        
        if (!overlay) {
            console.error("[Hub] Intervention overlay missing from DOM!");
            return;
        }

        if (data.active) {
            const srv = document.getElementById('intervention-service');
            const iss = document.getElementById('intervention-issue');
            const msg = document.getElementById('intervention-message');
            const url = document.getElementById('intervention-url');
            const actionBtn = document.getElementById('intervention-resume-btn');
            
            if (srv) srv.innerText = data.service || 'Unknown';
            if (iss) iss.innerText = data.issue || 'Unknown';
            if (msg) msg.innerText = data.message || 'Hermes needs help.';
            if (url) url.innerText = data.url || '';
            if (actionBtn) actionBtn.innerText = data.action_label || 'Done | Resume Mission';
            
            overlay.style.display = 'flex';
            
            if (!document.interventionNotified) {
                showToast(`🚨 Hermes Blocked on ${data.service}: ${data.issue}`, true);
                document.interventionNotified = true;
            }
        } else {
            overlay.style.display = 'none';
            const actionBtn = document.getElementById('intervention-resume-btn');
            if (actionBtn) actionBtn.innerText = 'Done | Resume Mission';
            document.interventionNotified = false;
        }
    } catch (e) {
        console.warn("[Hub] checkIntervention error: ", e.message);
    }
}

async function clearIntervention() {
    try {
        await fetch(`${API_BASE}/api/intervention/clear`, { method: 'POST' });
        document.getElementById('intervention-overlay').style.display = 'none';
        showToast('✅ Mission Resumed. Hermes is back on track.', false);
    } catch (e) {
        showToast('❌ Failed to clear intervention.', true);
    }
}

// ── Boot ──────────────────────────────────────────────────────

refreshStatus();
refreshMissionTheater();
checkIntervention();
setInterval(refreshStatus, 30000);
setInterval(refreshMissionTheater, 5000);
setInterval(checkIntervention, 5000);

// ── MEL (Superhero Lab) Functions ────────────────────────────

let melInitialized = false;

function initMel() {
    if (!melInitialized) {
        populateMelAgents();
        populateMelPacks(); // New: Populate scenario packs
        melInitialized = true;
    }
    loadPendingApprovals();
    
    // Check if a run is in progress. If not, clear any old timeline data.
    checkMelProgress(true); // true means 'is_init'
}

async function populateMelPacks() {
    try {
        // We reuse the Dojo config API for the pack list
        const response = await fetch(`${API_BASE}/api/dojo/config`);
        const config = await response.json();
        const select = document.getElementById('mel-pack-select');
        if (!select) return;
        
        // Keep the "Auto-Discover" option
        select.innerHTML = '<option value="default_pack">Auto-Discover (Smart)</option>';
        config.scenario_packs.forEach(p => {
            const opt = document.createElement('option');
            opt.value = p;
            opt.textContent = p.replace(/_/g, ' ').toUpperCase();
            select.appendChild(opt);
        });
    } catch (e) {
        console.error('[MEL] Pack population failed:', e);
    }
}

function onMelAgentChange() {
    const slug = document.getElementById('mel-agent-select').value;
    const packSelect = document.getElementById('mel-pack-select');
    
    // Auto-align pack if smart discovery is on
    if (slug && packSelect && window.dojoConfig && window.dojoConfig.agents) {
        const agent = window.dojoConfig.agents.find(a => a.slug === slug);
        if (agent && packSelect.value === 'default_pack') {
            showToast('Smart discovery enabled. The final pack is chosen at launch time based on agent and difficulty.', false);
        }
    }
}

function formatMelStageLabel(stage) {
    return String(stage || 'idle').replace(/_/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase());
}

function formatMelActivityAge(seconds) {
    if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return 'Waiting for SH Lab telemetry.';
    if (seconds < 10) return 'Live just now.';
    if (seconds < 60) return `Last MEL activity ${seconds}s ago.`;
    const mins = Math.round(seconds / 60);
    return `Last MEL activity ${mins}m ago.`;
}

function updateMelLiveSummary(data) {
    const summary = data.summary || {};
    const statusText = document.getElementById('mel-status-text');
    const liveStage = document.getElementById('mel-live-stage');
    const liveDetail = document.getElementById('mel-live-detail');
    const liveMeta = document.getElementById('mel-live-meta');
    if (!liveStage || !liveDetail || !liveMeta) return;

    const state = summary.state || (data.running ? 'running' : 'idle');
    const label = summary.stage_label || formatMelStageLabel(summary.current_stage || (data.running ? 'running' : 'idle'));
    const detail = summary.current_detail || (data.running ? 'Evolution cycle running.' : 'No active evolution cycle.');
    const warnings = summary.warnings || [];
    const meta = warnings.length ? warnings[0] : formatMelActivityAge(summary.last_event_age_seconds);

    liveStage.className = `mel-live-stage state-${state}`;
    liveStage.textContent = label;
    liveDetail.textContent = detail;
    liveMeta.textContent = meta;

    if (statusText) {
        statusText.textContent = data.running ? `${label}: ${detail}` : (warnings[0] || detail);
    }
}

function ensureMelPolling() {
    if (melPoller) return;
    pollForMelResults();
}

function stopMelPolling() {
    if (!melPoller) return;
    clearInterval(melPoller);
    melPoller = null;
}

function shouldDisplayMelTimeline(data, isInit = false) {
    if (!data) return false;
    if (data.running) return true;
    const events = data.events || [];
    if (!events.length) return false;

    const summary = data.summary || {};
    const state = summary.state || 'idle';

    if (state === 'error') return true;
    if (state === 'completed') {
        return true;
    }
    return false;
}

async function checkMelProgress(isInit = false) {
    try {
        const res = await fetch('/api/mel/progress');
        const data = await res.json();
        const panel = document.getElementById('mel-progress-panel');
        const stopBtn = document.getElementById('mel-stop-btn');
        const status = document.getElementById('mel-status');
        const btn = document.getElementById('mel-evolve-btn');
        updateMelLiveSummary(data);

        if (data.running && panel) {
            panel.style.display = 'block';
            if (stopBtn) stopBtn.style.display = 'inline-block';
            renderMelTimeline(data);
            
            // Start polling if not already
            if (btn && !btn.disabled) {
                btn.disabled = true;
                btn.textContent = '⏳ Running...';
                if (status) status.style.display = 'flex';
            }
            ensureMelPolling();
        } else if (panel && shouldDisplayMelTimeline(data, isInit)) {
            panel.style.display = 'block';
            renderMelTimeline(data);
            if (stopBtn) stopBtn.style.display = 'none';
            if (btn) {
                btn.disabled = false;
                btn.textContent = '⚡ Start Evolution Cycle';
            }
            if (status) status.style.display = 'flex';
            stopMelPolling();
        } else {
            if (panel) panel.style.display = 'none';
            if (stopBtn) stopBtn.style.display = 'none';
            if (btn) {
                btn.disabled = false;
                btn.textContent = '⚡ Start Evolution Cycle';
            }
            if (status) status.style.display = 'none';
            stopMelPolling();
        }
    } catch(e) { /* ignore */ }
}

function renderMelTimeline(data) {
    const timeline = document.getElementById('mel-timeline');
    const progressFill = document.getElementById('mel-progress-fill');
    const progressPct = document.getElementById('mel-progress-pct');
    if (!data.events || !timeline) return;
    const timelineScrollState = captureContainerScrollState(timeline);

    const stageIcons = {
        preflight: '🔌', load_agent: '📂', snapshot: '📸',
        diagnose: '🔍', troy: '🧠', baseline: '📊',
        challenger_1: '⚔️', challenger_2: '⚔️',
        saving: '📋', complete: '🏁'
    };

    const pct = data.last_pct || data.summary?.last_pct || 0;
    if (progressFill) progressFill.style.width = `${pct}%`;
    if (progressPct) progressPct.textContent = `${pct}%`;
    updateMelLiveSummary(data);

    timeline.innerHTML = data.events.map(ev => {
        const icon = stageIcons[ev.stage] || '⚙️';
        const statusClass = ev.status === 'done' ? 'mel-step-done' :
                           ev.status === 'active' ? 'mel-step-active' :
                           ev.status === 'error' ? 'mel-step-error' : '';
        const statusIcon = ev.status === 'done' ? '✅' :
                          ev.status === 'active' ? '<span class="mel-step-spinner">◉</span>' :
                          ev.status === 'error' ? '❌' : '';
        const scoreHtml = ev.data && ev.data.score !== undefined
            ? `<span class="mel-step-score">${ev.data.score}%</span>` : '';
        const categoryHtml = ev.data && ev.data.phase === 'scoring' && ev.data.category_index && ev.data.category_total
            ? `<span class="mel-step-score">${ev.data.category_index}/${ev.data.category_total}</span>` : '';
        return `
            <div class="mel-step ${statusClass}">
                <div class="mel-step-indicator">${statusIcon}</div>
                <div class="mel-step-content">
                    <div class="mel-step-title">${icon} ${ev.stage.replace(/_/g, ' ').toUpperCase()}</div>
                    <div class="mel-step-detail">${ev.detail} ${scoreHtml} ${categoryHtml}</div>
                    <div class="mel-step-time">${new Date(ev.timestamp).toLocaleTimeString()}</div>
                </div>
            </div>
        `;
    }).join('');
    restoreContainerScrollState(timeline, timelineScrollState);
}

async function populateMelAgents() {
    try {
        const res = await fetch('/api/data');
        const data = await res.json();
        const select = document.getElementById('mel-agent-select');
        if (!select) return;
        select.innerHTML = '';
        const agents = data.agents || [];
        agents.forEach(a => {
            const opt = document.createElement('option');
            opt.value = a.slug;
            opt.textContent = `${a.name || a.slug}`;
            select.appendChild(opt);
        });
    } catch (e) {
        console.error('[MEL] Failed to load agents:', e);
    }
}

async function triggerMelLoop() {
    const agent = document.getElementById('mel-agent-select')?.value;
    const pack = document.getElementById('mel-pack-select')?.value || 'default_pack';
    const difficulty = document.getElementById('mel-diff-select')?.value || 'mixed';
    const scenarios = parseInt(document.getElementById('mel-scenario-count')?.value || '3');
    const maxTurns = parseInt(document.getElementById('mel-turn-count')?.value || '8');
    
    if (!agent) {
        showToast('❌ Select an agent first.', true);
        return;
    }

    const btn = document.getElementById('mel-evolve-btn');
    const stopBtn = document.getElementById('mel-stop-btn');
    const status = document.getElementById('mel-status');
    const statusText = document.getElementById('mel-status-text');
    
    btn.disabled = true;
    btn.textContent = '⏳ Running...';
    if (stopBtn) {
        stopBtn.style.display = 'inline-block';
        stopBtn.disabled = false;
    }
    status.style.display = 'flex';
    statusText.textContent = `Evolution cycle running for ${agent} (${scenarios} scenarios, ${maxTurns === 0 ? 'Limitless' : maxTurns} turns)...`;

    // Reset Progress UI
    const progressPanel = document.getElementById('mel-progress-panel');
    const timeline = document.getElementById('mel-timeline');
    const progressFill = document.getElementById('mel-progress-fill');
    const progressPct = document.getElementById('mel-progress-pct');
    const limitlessBadge = document.getElementById('mel-limitless-badge');
    
    if (progressPanel) progressPanel.style.display = 'block';
    lastMelTimelineSignature = null;
    if (timeline) timeline.innerHTML = '<div class="mel-placeholder">Initializing evolution engine...</div>';
    if (progressFill) progressFill.style.width = '0%';
    if (progressPct) progressPct.innerText = '0%';
    if (limitlessBadge) limitlessBadge.style.display = (maxTurns === 0) ? 'inline-block' : 'none';

    try {
        const res = await fetch('/api/mel/evolve', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                agent, 
                scenario_pack: pack, 
                difficulty: difficulty, 
                scenarios, 
                max_turns: maxTurns 
            })
        });
        const data = await res.json();
        if (data.status === 'initiated') {
            showToast(`🦸 Evolution cycle launched for ${agent} (PID: ${data.pid}). Check feed for results.`);
            statusText.textContent = `Running... PID ${data.pid}. Polling for results.`;
            // Poll for completion
            ensureMelPolling();
        } else {
            showToast(`❌ MEL failed: ${data.detail || 'Unknown error'}`, true);
            btn.disabled = false;
            btn.textContent = '⚡ Start Evolution Cycle';
            status.style.display = 'none';
        }
    } catch (e) {
        showToast(`❌ MEL error: ${e.message}`, true);
        btn.disabled = false;
        btn.textContent = '⚡ Start Evolution Cycle';
        status.style.display = 'none';
        if (stopBtn) stopBtn.style.display = 'none';
    }
}
window.triggerMelLoop = triggerMelLoop;

async function stopMelLoop() {
    const stopBtn = document.getElementById('mel-stop-btn');
    if (stopBtn) stopBtn.disabled = true;
    showToast('🛑 Attempting to abort evolution cycle...');
    
    try {
        const res = await fetch('/api/mel/stop', { method: 'POST' });
        const data = await res.json();
        if (data.status === 'stopped') {
            showToast('✅ Evolution cycle successfully aborted.');
            stopMelPolling();
            // Force UI reset immediately
            const panel = document.getElementById('mel-progress-panel');
            if (panel) panel.style.display = 'none';
            const btn = document.getElementById('mel-evolve-btn');
            if (btn) {
                btn.disabled = false;
                btn.textContent = '⚡ Start Evolution Cycle';
            }
            const status = document.getElementById('mel-status');
            if (status) status.style.display = 'none';
            if (stopBtn) stopBtn.style.display = 'none';
        } else {
            showToast('⚠️ No active session found or abortion failed.', true);
        }
    } catch (e) {
        showToast('❌ Failed to communicate with Bridge.', true);
    }
}
window.stopMelLoop = stopMelLoop;

function pollForMelResults() {
    if (melPoller) return;
    let polls = 0;
    const maxPolls = 1440; // 2 hour max (5s intervals)
    const progressPanel = document.getElementById('mel-progress-panel');
    const timeline = document.getElementById('mel-timeline');
    const progressFill = document.getElementById('mel-progress-fill');
    const progressPct = document.getElementById('mel-progress-pct');

    if (progressPanel) progressPanel.style.display = 'block';

    const stageIcons = {
        preflight: '🔌', load_agent: '📂', snapshot: '📸',
        diagnose: '🔍', troy: '🧠', baseline: '📊',
        challenger_1: '⚔️', challenger_2: '⚔️',
        saving: '📋', complete: '🏁'
    };

    melPoller = setInterval(async () => {
        polls++;
        try {
            const res = await fetch('/api/mel/progress');
            const data = await res.json();

            // Toggle stop button based on running state
            const stopBtn = document.getElementById('mel-stop-btn');
            if (stopBtn) {
                stopBtn.style.display = data.running ? 'inline-block' : 'none';
                stopBtn.disabled = false; // Re-enable if it was disabled by a click
            }

            if (data.events && data.events.length > 0) {
                updateMelLiveSummary(data);
                // Update progress bar
                const pct = data.last_pct || 0;
                if (progressFill) progressFill.style.width = `${pct}%`;
                
                // Show last activity time
                const lastEvent = data.events[data.events.length - 1];
                if (lastEvent && progressPct) {
                    const elapsed = Math.round((Date.now() - new Date(lastEvent.timestamp)) / 1000);
                    progressPct.innerHTML = `${pct}% <span style="font-size: 0.7rem; opacity: 0.7; font-weight: normal; margin-left: 10px;">(Last activity ${elapsed}s ago)</span>`;
                }

                // Render timeline
                if (timeline) {
                    const renderSignature = [
                        data.events.length,
                        lastEvent?.timestamp || '',
                        lastEvent?.stage || '',
                        lastEvent?.status || '',
                        lastEvent?.detail || '',
                        lastEvent?.data?.scenario || '',
                        lastEvent?.data?.turn || '',
                        lastEvent?.data?.agent_msg || '',
                    ].join('|');
                    if (renderSignature !== lastMelTimelineSignature) {
                        const timelineScrollState = captureContainerScrollState(timeline);
                        timeline.innerHTML = data.events.map(ev => {
                        const icon = stageIcons[ev.stage] || '⚙️';
                        const statusClass = ev.status === 'done' ? 'mel-step-done' :
                                           ev.status === 'active' ? 'mel-step-active' :
                                           ev.status === 'error' ? 'mel-step-error' : '';
                        const statusIcon = ev.status === 'done' ? '✅' :
                                          ev.status === 'active' ? '<span class="mel-step-spinner">◉</span>' :
                                          ev.status === 'error' ? '❌' : '';
                        
                        // Handle Live Conversation Data (Chat Bubbles)
                        if (ev.data && ev.data.user && ev.data.agent_msg) {
                            return `
                                <div class="mel-step ${statusClass}" style="border:none; padding:10px 0;">
                                    <div class="mel-convo-container">
                                        <div class="mel-scenario-tag">Scenario ${ev.data.scenario} | Turn ${ev.data.turn}</div>
                                        <div class="mel-chat-bubble user">
                                            <span class="speaker">User Simulator</span>
                                            ${ev.data.user}
                                        </div>
                                        <div class="mel-chat-bubble agent">
                                            <span class="speaker">${ev.agent ? ev.agent.toUpperCase() : 'AGENT'}</span>
                                            ${ev.data.agent_msg}
                                        </div>
                                    </div>
                                </div>
                            `;
                        }

                        const scoreHtml = ev.data && ev.data.score !== undefined
                            ? `<span class="mel-step-score">${ev.data.score}%</span>` : '';
                        const categoryHtml = ev.data && ev.data.phase === 'scoring' && ev.data.category_index && ev.data.category_total
                            ? `<span class="mel-step-score">${ev.data.category_index}/${ev.data.category_total}</span>` : '';

                        return `
                            <div class="mel-step ${statusClass}">
                                <div class="mel-step-indicator">${statusIcon}</div>
                                <div class="mel-step-content">
                                    <div class="mel-step-title">${icon} ${ev.stage.replace(/_/g, ' ').toUpperCase()}</div>
                                    <div class="mel-step-detail">${ev.detail} ${scoreHtml} ${categoryHtml}</div>
                                    <div class="mel-step-time">${new Date(ev.timestamp).toLocaleTimeString()}</div>
                                </div>
                            </div>
                        `;
                    }).join('');
                    lastMelTimelineSignature = renderSignature;
                    restoreContainerScrollState(timeline, timelineScrollState);
                    }
                }
            }

            // Check if complete or timed out
            if (!data.running || polls >= maxPolls) {
                stopMelPolling();
                const btn = document.getElementById('mel-evolve-btn');
                const stopBtn = document.getElementById('mel-stop-btn');
                const status = document.getElementById('mel-status');
                const progressPanel = document.getElementById('mel-progress-panel');
                
                if (btn) {
                    btn.disabled = false;
                    btn.textContent = '⚡ Start Evolution Cycle';
                }
                if (stopBtn) stopBtn.style.display = 'none';
                const shouldKeepVisible = shouldDisplayMelTimeline(data, false);
                if (status) status.style.display = shouldKeepVisible ? 'flex' : 'none';
                if (progressPanel) progressPanel.style.display = shouldKeepVisible ? 'block' : 'none';
                
                loadPendingApprovals();

                if (!data.running && data.events && data.events.length > 0) {
                    const last = data.events[data.events.length - 1];
                    if (last.status === 'error') {
                        showToast(`❌ Evolution failed: ${last.detail}`, true);
                    } else if ((data.last_pct || 0) < 100 && polls < maxPolls) {
                        // This case covers the new auto-clear/liveness pulse reset
                        showToast('🔄 Hub auto-cleared a dead evolution session.');
                    } else {
                        showToast('🦸 Evolution cycle complete! Review results below.');
                    }
                } else if (polls >= maxPolls) {
                    showToast('⏰ Polling timed out. Check terminal for MEL status.', true);
                }
            }
        } catch (e) {
            // Keep polling
        }
    }, 3000);
}

async function loadPendingApprovals(options = {}) {
    const container = document.getElementById('mel-feed-container');
    if (!container) return;
    const { silent = false } = options;

    if (!silent) {
        showToast('🔄 Refreshing Superhero Lab feed...');
    }

    try {
        const res = await fetch('/api/mel/pending');
        const data = await res.json();

        if (!data.pending || data.pending.length === 0) {
            container.innerHTML = '<div class="mel-placeholder">No pending approvals. Run an evolution cycle to generate candidates.</div>';
            return;
        }

        container.innerHTML = data.pending.map(p => {
            const rec = p.recommendation || {};
            const improvement = rec.improvement || 0;
            const impClass = improvement >= 10 ? 'mel-improvement-good' : 'mel-improvement-review';
            const impLabel = improvement >= 10 ? '✅ RECOMMEND APPROVE' : '🔍 REVIEW NEEDED';
            const baseline = p.baseline || {};
            const diag = p.diagnostic || {};
            
            // Format prompt with highlights for patches
            const promptRaw = rec.prompt || "No prompt data available.";
            const promptFormatted = promptRaw
                .replace(/### \[MEL PATCH — .*\]/g, "<b>$&</b>")
                .replace(/### \[REINFORCED CONSTRAINTS\]/g, "<b>$&</b>");

            return `
                <div class="mel-pending-card">
                    <div class="mel-card-header">
                        <span class="mel-agent-badge">${p.agent_slug}</span>
                        <span class="mel-timestamp">${new Date(p.created_at).toLocaleString()}</span>
                    </div>
                    <div class="mel-card-body">
                        <div class="mel-diagnostic">
                            <span class="mel-label">Failure Category:</span>
                            <span class="mel-value">${diag.failure_category || 'N/A'}</span>
                        </div>
                        <div class="mel-scores">
                            <div class="mel-score-item">
                                <span class="mel-score-label">Baseline</span>
                                <span class="mel-score-value">${baseline.score || 0}%</span>
                            </div>
                            <div class="mel-score-item">
                                <span class="mel-score-label">Best Challenger</span>
                                <span class="mel-score-value">${rec.score || 0}%</span>
                            </div>
                            <div class="mel-score-item ${impClass}">
                                <span class="mel-score-label">Improvement</span>
                                <span class="mel-score-value">${improvement > 0 ? '+' : ''}${improvement}%</span>
                            </div>
                        </div>
                        <div class="mel-patch-info">
                            <span class="mel-label">Variant:</span> ${rec.variant || 'N/A'}
                            <br><span class="mel-label">Rationale:</span> ${rec.rationale || 'N/A'}
                        </div>
                        
                        <button class="mel-view-toggle-btn" onclick="togglePersonaViewer(event, '${p.pending_id}')">👁️ View Suggested Persona</button>
                        
                        <div id="persona-viewer-${p.pending_id}" class="mel-persona-viewer">
                            <div class="mel-persona-header">
                                <span>Suggested System Prompt</span>
                                <button class="mel-copy-btn" onclick="copyPromptToClipboard('${p.pending_id}')">Copy Prompt</button>
                            </div>
                            <div class="mel-persona-content">
                                <pre id="persona-text-${p.pending_id}">${promptFormatted}</pre>
                            </div>
                        </div>

                        <div class="mel-verdict">${impLabel}</div>
                    </div>
                    <div class="mel-card-actions">
                        <button class="mel-approve-btn" onclick="approvePatch('${p.pending_id}')">✅ Approve</button>
                        <button class="mel-reject-btn" onclick="rejectPatch('${p.pending_id}')">❌ Reject</button>
                    </div>
                </div>
            `;
        }).join('');
    } catch (e) {
        container.innerHTML = '<div class="mel-placeholder">Error loading pending approvals.</div>';
    }
}
window.loadPendingApprovals = loadPendingApprovals;

async function refreshMelFeed() {
    const refreshButtons = Array.from(document.querySelectorAll('.mel-refresh-btn'));
    refreshButtons.forEach(btn => {
        btn.disabled = true;
        btn.textContent = 'Refreshing...';
    });

    try {
        await Promise.all([
            checkMelProgress(false),
            loadPendingApprovals({ silent: true }),
        ]);
        showToast('✅ Superhero Lab refreshed.');
    } catch (e) {
        showToast('❌ Failed to refresh Superhero Lab.', true);
    } finally {
        refreshButtons.forEach(btn => {
            btn.disabled = false;
            btn.textContent = 'Refresh Feed';
        });
    }
}
window.refreshMelFeed = refreshMelFeed;

function togglePersonaViewer(event, pendingId) {
    const viewer = document.getElementById(`persona-viewer-${pendingId}`);
    if (!viewer) return;
    const isVisible = viewer.style.display === 'block';
    viewer.style.display = isVisible ? 'none' : 'block';
    const btn = event.currentTarget || event.target;
    btn.textContent = isVisible ? '👁️ View Suggested Persona' : '📂 Hide Suggested Persona';
}
window.togglePersonaViewer = togglePersonaViewer;

async function copyPromptToClipboard(pendingId) {
    const pre = document.getElementById(`persona-text-${pendingId}`);
    if (!pre) return;
    try {
        await navigator.clipboard.writeText(pre.innerText);
        showToast("✅ Persona copied to clipboard.");
    } catch (err) {
        showToast("❌ Failed to copy.", true);
    }
}
window.copyPromptToClipboard = copyPromptToClipboard;

async function approvePatch(pendingId) {
    if (!confirm('Apply this prompt patch to agents.yaml?')) return;
    try {
        const res = await fetch('/api/mel/approve', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ pending_id: pendingId })
        });
        const data = await res.json();
        if (data.status === 'approved') {
            showToast(`✅ Patch approved and applied to ${data.agent}!`);
            loadPendingApprovals();
        } else {
            showToast(`❌ Approval failed: ${data.detail || 'Unknown error'}`, true);
        }
    } catch (e) {
        showToast(`❌ Approval error: ${e.message}`, true);
    }
}
window.approvePatch = approvePatch;

async function rejectPatch(pendingId) {
    try {
        const res = await fetch('/api/mel/reject', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ pending_id: pendingId })
        });
        const data = await res.json();
        if (data.status === 'rejected') {
            showToast('❌ Patch rejected and discarded.');
            loadPendingApprovals();
        } else {
            showToast(`❌ Rejection failed: ${data.detail || 'Unknown error'}`, true);
        }
    } catch (e) {
        showToast(`❌ Rejection error: ${e.message}`, true);
    }
}
window.rejectPatch = rejectPatch;
