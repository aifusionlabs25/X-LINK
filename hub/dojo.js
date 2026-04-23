/**

 * X-LINK Dojo Console â State Controller

 * Handles mission setup, live telemetry, and results visualization.

 */



let activeSessionInterval = null;

let currentBatchId = null;
let currentDojoConfig = null;
let healthInterval = null;

function formatBatchStatus(status) {
    return String(status || 'idle').replace(/_/g, ' ').toUpperCase();
}

function styleStatusChip(el, status) {
    if (!el) return;
    const normalized = String(status || 'idle').toLowerCase();
    el.innerText = formatBatchStatus(normalized);
    el.className = `status-chip ${normalized === 'running' ? 'active' : ''}`;
}

function renderMarathonEvents(events = []) {
    const container = document.getElementById('marathon-events');
    if (!container) return;
    const ordered = [...events].slice(-8).reverse();
    if (!ordered.length) {
        container.innerHTML = `<div style="padding:12px; border-radius:12px; background:rgba(0,0,0,0.18); border:1px solid rgba(255,255,255,0.05); color:var(--text-dim); font-size:0.82rem;">Waiting for live batch telemetry...</div>`;
        return;
    }
    container.innerHTML = ordered.map(evt => `
        <div style="padding:12px; border-radius:12px; background:rgba(0,0,0,0.18); border:1px solid rgba(255,255,255,0.05);">
            <div style="display:flex; justify-content:space-between; gap:12px; margin-bottom:6px; font-size:0.72rem; color:var(--text-dim);">
                <span style="color:var(--gold);">${evt.step || evt.kind || 'Update'}</span>
                <span>${evt.percent ?? 0}%</span>
            </div>
            <div style="font-size:0.82rem; line-height:1.45; color:var(--text);">${evt.detail || 'Telemetry update received.'}</div>
        </div>
    `).join('');
}

function renderCompletedLegs(legs = []) {
    const container = document.getElementById('marathon-completed-legs');
    if (!container) return;
    if (!legs.length) {
        container.innerHTML = `<span style="color:var(--text-dim); font-size:0.82rem;">No completed legs yet.</span>`;
        return;
    }
    container.innerHTML = legs.map(leg => {
        const status = String(leg.status || 'completed').toLowerCase();
        const isFailed = status !== 'completed';
        const bg = isFailed ? 'rgba(239, 68, 68, 0.1)' : 'rgba(16, 185, 129, 0.1)';
        const border = isFailed ? 'rgba(239, 68, 68, 0.35)' : 'rgba(16, 185, 129, 0.35)';
        const color = isFailed ? '#fecaca' : '#bbf7d0';
        return `<span style="padding:8px 10px; border-radius:999px; font-size:0.72rem; border:1px solid ${border}; background:${bg}; color:${color};">${leg.agent} / ${leg.difficulty}</span>`;
    }).join('');
}

function updateMarathonUI(data) {
    const panel = document.getElementById('marathon-live-panel');
    if (!panel) return;
    const session = data && data.session ? data.session : null;
    if (!session || session.type !== 'marathon') {
        panel.style.display = 'none';
        return;
    }

    const status = String(session.status || 'running').toLowerCase();
    const refreshBtn = document.getElementById('marathon-refresh-btn');
    const stopBtn = document.getElementById('marathon-stop-btn');

    panel.style.display = 'block';
    document.getElementById('marathon-live-title').innerText = session.marathon_id || session.batch_id || 'Active batch';
    styleStatusChip(document.getElementById('marathon-live-status'), status);
    document.getElementById('marathon-progress-step').innerText = session.review_step || 'Batch in progress';
    document.getElementById('marathon-progress-percent').innerText = `${session.review_progress ?? 0}%`;
    document.getElementById('marathon-progress-bar').style.width = `${session.review_progress ?? 0}%`;
    document.getElementById('marathon-current-leg').innerText = `${session.current_leg_index || 0} / ${session.total_legs || 0}`;
    const runIdx = session.current_run_idx || 0;
    const totalRuns = session.total_runs || session.runs_per_agent || 0;
    document.getElementById('marathon-current-run').innerText = totalRuns ? `${runIdx} / ${totalRuns}` : '--';
    document.getElementById('marathon-current-agent').innerText = session.current_agent || '--';
    document.getElementById('marathon-current-difficulty').innerText = session.current_difficulty || '--';
    renderCompletedLegs(session.completed_legs || []);
    renderMarathonEvents(session.events || []);

    if (stopBtn) {
        if (status === 'running' || status === 'starting') {
            stopBtn.disabled = false;
            stopBtn.style.opacity = '1';
            stopBtn.innerText = 'Stop Batch';
        } else {
            stopBtn.disabled = true;
            stopBtn.style.opacity = '0.45';
            stopBtn.innerText = 'Stopped';
        }
    }

    if (refreshBtn) {
        refreshBtn.innerText = (status === 'running' || status === 'starting') ? 'Refresh' : 'Refresh Status';
    }
}

function getReviewModeConfig(reviewModeId) {
    if (!currentDojoConfig || !currentDojoConfig.profiles || !Array.isArray(currentDojoConfig.profiles.review_modes)) return null;
    return currentDojoConfig.profiles.review_modes.find(mode => mode.id === reviewModeId) || null;
}

function getDojoAgentConfig(agentSlug) {
    if (!currentDojoConfig || !currentDojoConfig.agents) return null;
    return currentDojoConfig.agents.find(a => a.slug === agentSlug) || null;
}

function getPackOwnerSlug(packName) {
    if (!currentDojoConfig || !currentDojoConfig.agents || !packName) return '';
    const owners = currentDojoConfig.agents.filter(agent => {
        const allowed = (agent.eval && Array.isArray(agent.eval.allowed_packs)) ? agent.eval.allowed_packs : [];
        return allowed.includes(packName);
    });
    return owners.length === 1 ? owners[0].slug : '';
}

function refreshPackOptionsForAgent(preferredPack = null, announce = false) {
    const agentSelect = document.getElementById('dojo-agent-select');
    const packSelect = document.getElementById('dojo-pack-select');
    if (!agentSelect || !packSelect || !currentDojoConfig) return;

    const agent = getDojoAgentConfig(agentSelect.value);
    const allowedPacks = (agent && agent.eval && Array.isArray(agent.eval.allowed_packs) && agent.eval.allowed_packs.length)
        ? agent.eval.allowed_packs
        : (currentDojoConfig.scenario_packs || []);

    populateSelect('dojo-pack-select', allowedPacks.map(pack => ({
        id: pack,
        label: pack.replace(/_/g, ' ').toUpperCase()
    })));

    const nextPack =
        (preferredPack && allowedPacks.includes(preferredPack) && preferredPack) ||
        (agent && agent.eval && allowedPacks.includes(agent.eval.default_pack) && agent.eval.default_pack) ||
        allowedPacks[0] ||
        '';

    if (nextPack) {
        packSelect.value = nextPack;
        if (announce) {
            showToast(`Scenario pack aligned: ${nextPack}`, false);
        }
    }
}


async function initDojo() {
    try {
        const previousSelections = {
            agent: document.getElementById('dojo-agent-select')?.value || '',
            pack: document.getElementById('dojo-pack-select')?.value || '',
            environment: document.getElementById('dojo-env-select')?.value || '',
            difficulty: document.getElementById('dojo-diff-select')?.value || '',
            runs: document.getElementById('dojo-count-select')?.value || '',
            turns: document.getElementById('dojo-turn-select')?.value || '',
            review: document.getElementById('dojo-review-select')?.value || '',
        };
        const response = await fetch(`${API_BASE}/api/dojo/config`);
        const config = await response.json();
        currentDojoConfig = config;
        window.dojoConfig = config; // Global Exposure
        

        populateSelect('dojo-agent-select', config.agents.map(a => ({ id: a.slug, label: `${a.name} (${a.role})` })));

        populateSelect('dojo-pack-select', config.scenario_packs.map(p => ({ id: p, label: p.replace(/_/g, ' ').toUpperCase() })));

        populateSelect('dojo-env-select', config.profiles.environments);

        populateSelect('dojo-diff-select', config.profiles.difficulties);
        populateSelect('dojo-count-select', config.profiles.run_counts.map(c => ({ id: c, label: `${c} ${c === 1 ? 'Run' : 'Runs'}` })));
        populateSelect('dojo-turn-select', config.profiles.turn_profiles);
        populateSelect('dojo-review-select', config.profiles.review_modes);

        const restoreSelectValue = (id, value) => {
            const select = document.getElementById(id);
            if (!select || !value) return;
            const exists = Array.from(select.options).some(option => option.value === value);
            if (exists) {
                select.value = value;
            }
        };

        restoreSelectValue('dojo-agent-select', previousSelections.agent);
        restoreSelectValue('dojo-env-select', previousSelections.environment);
        restoreSelectValue('dojo-diff-select', previousSelections.difficulty);
        restoreSelectValue('dojo-count-select', previousSelections.runs);
        restoreSelectValue('dojo-turn-select', previousSelections.turns);
        restoreSelectValue('dojo-review-select', previousSelections.review);
        refreshPackOptionsForAgent(previousSelections.pack, false);


        // Populate Marathon Fields

        populateSelect('marathon-env-select', config.profiles.environments);

        

        const marathonDiffGrid = document.getElementById('marathon-diff-grid');

        if (marathonDiffGrid && config.profiles.difficulties) {

            marathonDiffGrid.innerHTML = config.profiles.difficulties.map(item => {

                const val = typeof item === 'object' ? item.id : item;

                const lab = typeof item === 'object' ? (item.label || item.id) : item;

                return `

                <label class="cb-container agent-select-cb">

                    ${lab}

                    <input type="checkbox" value="${val}" class="marathon-diff-checkbox" ${val === 'mixed' ? 'checked' : ''}>

                    <span class="checkmark"></span>

                </label>

            `;

            }).join('');

        }

        

        populateSelect('marathon-review-select', config.profiles.review_modes);

        

        const marathonGrid = document.getElementById('marathon-agent-grid');

        if (marathonGrid) {

            marathonGrid.innerHTML = config.agents.map(a => `

                <label class="cb-container agent-select-cb">

                    ${a.name}

                    <input type="checkbox" value="${a.slug}" class="marathon-agent-checkbox">

                    <span class="checkmark"></span>

                </label>

            `).join('');

        }



        // Add change listeners

        const agentSelect = document.getElementById('dojo-agent-select');
        agentSelect.addEventListener('change', () => refreshPackOptionsForAgent(null, true));
        agentSelect.addEventListener('change', updateSyncStatus);


        loadDojoHistory();

        refreshDojoHealth();

        updateSyncStatus(); // Initial populate



        // Singleton guard: clear previous before setting new

        if (healthInterval) {

            clearInterval(healthInterval);

        }

        healthInterval = setInterval(refreshDojoHealth, 10000);
        hydrateActiveDojoSession();

    } catch (e) {

        showToast("Dojo Config Sync Failed", true);

    }

}



async function refreshDojoHealth() {

    try {

        const response = await fetch(`${API_BASE}/api/dojo/health`);

        const data = await response.json();

        

        updateHealthItem('health-bridge', data.bridge);

        updateHealthItem('health-demo', data.demo_server);

        updateHealthItem('health-ollama', data.ollama);

    } catch (e) {

        console.warn("Dojo Health Check Failed");

    }

}



function updateHealthItem(id, info) {

    const el = document.getElementById(id);

    if (!el || !info) return;

    

    el.className = `health-item ${info.status}`;

    el.querySelector('.val').innerText = info.message;

}



function populateSelect(id, items) {

    const select = document.getElementById(id);

    if (!select) return;

    select.innerHTML = items.map(item => {

        const val = typeof item === 'object' ? item.id : item;

        const lab = typeof item === 'object' ? (item.label || item.id) : item;

        return `<option value="${val}">${lab}</option>`;

    }).join('');

}



function autoAlignPack() {
    refreshPackOptionsForAgent(null, true);
}


function updateSyncStatus() {

    const slug = document.getElementById('dojo-agent-select').value;

    const div = document.getElementById('agent-sync-status');

    if (!div || !currentDojoConfig || !currentDojoConfig.agents) return;

    

    const agent = currentDojoConfig.agents.find(a => a.slug === slug);

    if (agent && agent.last_synced) {

        const d = new Date(agent.last_synced);

        div.innerHTML = `â Synced: ${d.toLocaleString(undefined, {month:'short', day:'numeric', hour:'numeric', minute:'2-digit'})}`;

        div.style.color = "var(--success-color, #4CAF50)";

    } else {

        div.innerHTML = `â ï¸ Unsynced (Local default)`;

        div.style.color = "var(--warning-color, #FF9800)";

    }

}



function switchDojoTab(tabId) {

    // Nav Buttons

    document.querySelectorAll('.dojo-tab').forEach(btn => {

        btn.classList.toggle('active', btn.innerText.toLowerCase().includes(tabId));

    });



    // Panes

    document.querySelectorAll('.dojo-pane').forEach(pane => {

        pane.classList.remove('active');

    });

    document.getElementById(`dojo-pane-${tabId}`).classList.add('active');

}



async function startDojoMission(overrideParams = null) {
    let params = overrideParams;

    

    if (!params) {
        params = {
            agent: document.getElementById('dojo-agent-select').value,
            pack: document.getElementById('dojo-pack-select').value,

            environment: document.getElementById('dojo-env-select').value,

            type: document.getElementById('dojo-type-select').value,

            difficulty: document.getElementById('dojo-diff-select').value,

            runs: document.getElementById('dojo-count-select').value,

            turn_profile: document.getElementById('dojo-turn-select').value,

            review_mode: document.getElementById('dojo-review-select').value,

            browser_mode: document.getElementById('dojo-opt-browser-mode').checked
        };
    }

    const selectedAgent = getDojoAgentConfig(params.agent);
    const allowedPacks = (selectedAgent && selectedAgent.eval && Array.isArray(selectedAgent.eval.allowed_packs))
        ? selectedAgent.eval.allowed_packs
        : [];
    if (params.pack && allowedPacks.length && !allowedPacks.includes(params.pack)) {
        const owningSlug = getPackOwnerSlug(params.pack);
        if (owningSlug) {
            params.agent = owningSlug;
            const agentSelect = document.getElementById('dojo-agent-select');
            if (agentSelect) agentSelect.value = owningSlug;
            refreshPackOptionsForAgent(params.pack, false);
            showToast(`Corrected agent to ${owningSlug.toUpperCase()} for pack ${params.pack}`, false);
        } else {
            refreshPackOptionsForAgent(null, false);
            const packSelect = document.getElementById('dojo-pack-select');
            if (packSelect) {
                params.pack = packSelect.value;
            }
            showToast(`Corrected scenario pack for ${String(params.agent).toUpperCase()}`, false);
        }
    }

    showToast(params.rerun_batch_id ? "Rerunning Failed Scenarios..." : `Deploying Dojo Evaluator for ${String(params.agent || 'selected agent').toUpperCase()}...`, false);
    

    try {

        const response = await fetch(`${API_BASE}/api/dojo/start`, {

            method: 'POST',

            headers: { 'Content-Type': 'application/json' },

            body: JSON.stringify(params)

        });

        

        if (response.ok) {

            switchDojoTab('live');

            startPollingTelemetry();

        }

    } catch (e) {

        showToast("Dojo Launch Error", true);

    }

}



async function startMarathonMission() {

    const checkboxes = document.querySelectorAll('.marathon-agent-checkbox:checked');

    const selectedAgents = Array.from(checkboxes).map(cb => cb.value);

    

    if (selectedAgents.length === 0) {

        showToast("Please select at least one agent.", true);

        return;

    }



    const diffCheckboxes = document.querySelectorAll('.marathon-diff-checkbox:checked');

    const selectedDiffs = Array.from(diffCheckboxes).map(cb => cb.value);

    

    if (selectedDiffs.length === 0) {

        showToast("Please select at least one difficulty.", true);

        return;

    }



    const countInput = document.getElementById('marathon-count-input');

    const runsCount = countInput ? parseInt(countInput.value, 10) : 10;



    const params = {

        agents: selectedAgents,

        environment: document.getElementById('marathon-env-select').value,

        difficulty: selectedDiffs,

        runs: runsCount,

        review_mode: document.getElementById('marathon-review-select').value,

    };



    showToast("Deploying Batch Test Runner...", false);

    

    try {

        const response = await fetch(`${API_BASE}/api/dojo/marathon`, {

            method: 'POST',

            headers: { 'Content-Type': 'application/json' },

            body: JSON.stringify(params)

        });

        

        if (response.ok) {

            switchDojoTab('marathon');
            showToast("Batch queued. Live progress is now available below.", false);
            startPollingTelemetry();

        }

    } catch (e) {

        showToast("Batch Launch Error", true);

    }

}



function rerunFailedScenarios() {

    if (!currentBatchId) {

        showToast("No active mission results to rerun", true);

        return;

    }

    

    // We reuse the last agent select but force the rerun flag

    const missionParams = {

        agent: document.getElementById('dojo-agent-select').value,

        rerun_batch_id: currentBatchId

    };



    startDojoMission(missionParams);

}



function copyPatchToClipboard() {

    const patchCode = document.querySelector('.patch-diff').innerText;

    if (!patchCode || patchCode.includes("idle")) {

        showToast("No patch data available", true);

        return;

    }



    navigator.clipboard.writeText(patchCode).then(() => {

        showToast("Patch copied to clipboard!", false);

    }).catch(err => {

        console.error("Clipboard Error:", err);

        showToast("Failed to copy", true);

    });

}



function startPollingTelemetry() {

    if (activeSessionInterval) clearInterval(activeSessionInterval);

    

    // Clear live transcript

    const container = document.getElementById('dojo-transcript-live');

    container.innerHTML = '<div class="neural-placeholder">Initializing Neural Link...</div>';

    

    activeSessionInterval = setInterval(async () => {

        try {

            const response = await fetch(`${API_BASE}/api/dojo/session`);

            const data = await response.json();

            

            if (data.session && data.session.status === 'completed') {

                clearInterval(activeSessionInterval);

                updateLiveUI(data); // Final update for the count/progress
                updateMarathonUI(data);

                if (data.session.type === 'marathon') {
                    showToast("Batch run complete.", false);
                    if (data.session.last_child_batch_id) {
                        currentBatchId = data.session.last_child_batch_id;
                        loadBatchResults(data.session.last_child_batch_id);
                    }
                } else {
                    finishDojoMission(data.session.batch_id);
                }

            } else if (data.active) {

                updateLiveUI(data);
                updateMarathonUI(data);

            } else if (data.session && data.session.status === 'failed') {

                clearInterval(activeSessionInterval);

                showToast("Dojo Mission Failed", true);

                updateLiveUI(data);
                updateMarathonUI(data);

            }

        } catch (e) {

            console.error("Telemetry poll failed", e);

        }

    }, 2000);

}



function updateLiveUI(data) {

    const { session, telemetry } = data;

    if (!session || session.type === 'marathon') {
        return;
    }

    document.getElementById('tel-batch-id').innerText = session.batch_id || 'â';

    document.getElementById('tel-agent').innerText = session.params.agent || 'â';

    document.getElementById('tel-status').innerText = (telemetry.status || session.status).toUpperCase();

    document.getElementById('tel-status').className = `status-chip ${(telemetry.status || session.status) === 'running' ? 'active' : ''}`;

    

    // Detailed Diagnostics

    document.getElementById('diag-state').innerText = session.review_progress > 0 ? 'REVIEWING' : (telemetry.state || 'ACTIVE');

    document.getElementById('diag-status').innerText = (telemetry.status || session.status || 'PENDING').toUpperCase();

    document.getElementById('diag-reason').innerText = telemetry.reason || (session.review_step || 'â');

    document.getElementById('diag-turns').innerText = telemetry.actual_turns || 'â';

    document.getElementById('diag-errors').innerText = telemetry.error || session.error || 'NONE';

    

    // Progress Bar

    const progContainer = document.getElementById('review-progress-container');

    if (session.review_progress > 0 && session.status !== 'completed') {

        progContainer.style.display = 'block';

        document.getElementById('review-progress-bar').style.width = `${session.review_progress}%`;

        document.getElementById('review-step').innerText = session.review_step || 'Intelligence Review';

        document.getElementById('review-percent').innerText = `${session.review_progress}%`;

    } else {

        progContainer.style.display = 'none';

    }



    // Update Transcript if telemetry has new turns

    if (telemetry.transcript && telemetry.transcript.length > 0) {

        renderLiveTranscript(telemetry.transcript);

    }

}



function renderLiveTranscript(transcript) {

    const container = document.getElementById('dojo-transcript-live');

    const existingCount = container.querySelectorAll('.neural-bubble').length;

    

    if (transcript.length > existingCount) {

        // Handle placeholder

        if (container.querySelector('.neural-placeholder')) container.innerHTML = '';

        

        for (let i = existingCount; i < transcript.length; i++) {

            const turn = transcript[i];

            const div = document.createElement('div');

            div.className = `neural-bubble ${turn.speaker === 'agent_under_test' ? 'agent' : 'user'}`;

            let textHtml = turn.text;
            if (turn.speaker === 'agent_under_test') {
                textHtml = textHtml.replace(/&lt;thought&gt;([\s\S]*?)&lt;\/thought&gt;/g, '<div class="thought-trace"><strong>Thought:</strong> $1</div>');
                textHtml = textHtml.replace(/<thought>([\s\S]*?)<\/thought>/g, '<div class="thought-trace"><strong>Thought:</strong> $1</div>');
            }
            div.innerHTML = `

                <span class="speaker-label">${turn.speaker === 'agent_under_test' ? 'X-AGENT' : 'TEST-USER'}</span>

                ${textHtml}

            `;

            container.appendChild(div);

        }

        container.scrollTop = container.scrollHeight;

    }

}




async function hydrateActiveDojoSession() {

    try {

        const response = await fetch(`${API_BASE}/api/dojo/session`);

        const data = await response.json();

        if (!data.active) {
            updateMarathonUI({ session: null });
            return;
        }
        if (!data.session) return;

        if (data.session.type === 'marathon') {
            updateMarathonUI(data);
        } else {
            updateLiveUI(data);
        }

        if (data.session.status === 'running' || data.session.status === 'starting') {
            startPollingTelemetry();
        }

    } catch (e) {

        console.warn('Unable to hydrate active Dojo session', e);

    }

}

async function refreshMarathonStatus() {
    try {
        const response = await fetch(`${API_BASE}/api/dojo/session`);
        const data = await response.json();
        if (!data.active) {
            updateMarathonUI({ session: null });
            showToast("No active batch run.", false);
            return;
        }
        if (data.session && data.session.type === 'marathon') {
            updateMarathonUI(data);
            showToast("Batch status refreshed.", false);
            return;
        }
        showToast("No active batch run.", false);
    } catch (e) {
        console.error("Batch refresh failed", e);
        showToast("Failed to refresh batch status", true);
    }
}

async function stopActiveBatch() {
    try {
        const response = await fetch(`${API_BASE}/api/dojo/stop`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.detail || data.message || 'Failed to stop batch');
        }
        if (activeSessionInterval) {
            clearInterval(activeSessionInterval);
            activeSessionInterval = null;
        }
        showToast(data.message || "Active batch stopped.", false);
        await hydrateActiveDojoSession();
    } catch (e) {
        console.error("Batch stop failed", e);
        showToast("Failed to stop batch", true);
    }
}

async function finishDojoMission(batchId) {

    showToast("Dojo Mission Complete. Syncing Intelligence...", false);

    currentBatchId = batchId;

    switchDojoTab('results');

    await loadBatchResults(batchId);

}



async function loadBatchResults(batchId) {

    try {

        const response = await fetch(`${API_BASE}/api/dojo/batch/${batchId}`);

        const data = await response.json();

        try {

            renderResults(data);

        } catch (renderErr) {

            console.error("Rendering Error:", renderErr);

            showToast("Rendering error. See console.", true);

            const container = document.getElementById('dojo-results-container');

            container.innerHTML = `<div class="results-placeholder">Critical rendering error. Data may be malformed.</div>`;

        }

    } catch (e) {

        showToast("Failed to load results", true);

    }

}



function renderResults(data) {

    const container = document.getElementById('dojo-results-container');

    

    if (data.total_runs === 0) {

        container.innerHTML = `

            <div class="results-canvas" style="text-align: center; padding: 50px;">

                <h3 class="gold-text cinzel">Mission Aborted: No Data Found</h3>

                <p style="color:var(--text-dim); margin-top: 20px;">The evaluator was unable to find any scenarios matching your criteria for agent <strong>${data.target_agent}</strong> and difficulty <strong>${data.difficulty || 'Mixed'}</strong>.</p>

                <div style="margin-top: 30px;">

                    <button class="dojo-primary-btn" onclick="switchDojoTab('run')">Go Back & Adjust Settings</button>

                </div>

            </div>

        `;

        return;

    }



    const avgScore = data.average_score ?? data.score ?? 'N/A';

    const passRate = data.pass_rate ?? data.pass_fail_rate ?? 'N/A';

    

    // Resolve APEX logic from newer or older schemas

    const revResults = data.reviewer_results || (data.data && data.data.reviewer_results) || null;

    const isSuccess = data.reviewer_status === 'success' || (revResults && Object.keys(revResults).length > 0);



    container.innerHTML = `

        <div class="results-summary-dashboard">

            <div class="stat-box"><h4>Overall Score</h4><div class="value">${avgScore}${avgScore !== 'N/A' ? '%' : ''}</div></div>

            <div class="stat-box"><h4>Pass Rate</h4><div class="value">${passRate}${passRate !== 'N/A' ? '%' : ''}</div></div>

            <div class="stat-box"><h4>Verdict</h4><div class="value" style="color:var(--success)">${data.verdict}</div></div>

            <div class="stat-box"><h4>APEX Status</h4><div class="value" style="color:${isSuccess ? 'var(--gold)' : 'var(--danger)'}">${isSuccess ? 'SUCCESS' : (data.reviewer_status || 'N/A').toUpperCase()}</div></div>

        </div>

        

        ${data.reviewer_error ? `<div class="infra-error-banner" style="background:rgba(239, 68, 68, 0.1); border-left:4px solid var(--danger); padding:15px; margin: 20px 0; border-radius:4px;">

            <div style="font-weight:700; color:var(--danger);">APEX ANALYTIC ERROR</div>

            <div style="font-size:0.9rem; color:var(--text-dim);">${data.reviewer_error}</div>

        </div>` : ''}

        

        <div class="results-layout-grid" style="display:grid; grid-template-columns: 1fr 1fr; gap:30px; margin-top:30px;">

            <div class="results-canvas">

                <h4 class="gold-text cinzel">Failure Heatmap</h4>

                <div id="results-heatmap" class="heatmap-grid" style="display:flex; gap:10px; margin-top:20px;">

                    ${(data.runs || []).map(r => {

                        const v = (r.pass_fail || r.verdict || 'FAIL').toUpperCase();

                        const color = (v === 'PASS' || v === 'PASS_WITH_WARNINGS') ? '#10b981' : '#ef4444';

                        return `<div class="heatmap-cell ${v.toLowerCase()}" style="width:30px; height:30px; border-radius:4px; background:${color}" title="${r.scenario_id}: ${v}"></div>`;

                    }).join('')}

                </div>

                

                <h4 class="gold-text cinzel" style="margin-top:40px;">Completion Reasons</h4>

                <div class="completion-stats" style="margin-top:20px;">

                    ${generateCompletionStats(data.runs || [])}

                </div>

            </div>



            <div class="results-canvas">

                <h4 class="gold-text cinzel">Category Breakdown</h4>

                <div class="category-bars">

                    ${Object.entries(data.category_averages || {}).map(([cat, score]) => `

                        <div class="cat-bar-container">

                            <div class="cat-label">${cat.replace(/_/g, ' ')}</div>

                            <div class="cat-bar-track">

                                <div class="cat-bar-fill" style="width: ${score}%"></div>

                            </div>

                            <div class="cat-score">${score}%</div>

                        </div>

                    `).join('')}

                </div>

            </div>

        </div>



        <div class="results-layout-full" style="margin-top:40px;">

            <div class="results-canvas" style="background: rgba(0,0,0,0.2); border: 1px solid var(--border); border-radius:16px; padding:30px;">

                <h4 class="gold-text cinzel" style="margin-bottom:20px;">APEX Intelligence Report</h4>

                

                ${isSuccess ? `

                    <div class="intelligence-grid" style="display:grid; grid-template-columns: repeat(3, 1fr); gap:20px;">

                        ${renderReviewCard('Role Review', revResults?.role_review)}

                        ${renderReviewCard('Conversation Review', revResults?.conversation_review)}

                        ${renderReviewCard('Safety Review', revResults?.safety_review)}

                    </div>

                ` : `

                    <div class="results-placeholder">Analytic report unavailable or failed. Check APEX Status.</div>

                `}



                <div class="full-report-toggle" style="margin-top:30px; text-align:center;">

                    <button class="dojo-secondary-btn" id="toggle-technical-btn" onclick="document.getElementById('full-technical-report').style.display='block'; this.style.display='none'">SHOW FULL TECHNICAL REPORT</button>

                    <div id="full-technical-report" style="display:none; text-align:left; margin-top:20px;">

                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">

                            <h5 class="gold-text" style="font-size:0.75rem;">RAW ANALYTIC PACKET</h5>

                            <button class="dojo-secondary-btn" style="padding:4px 10px; font-size:0.6rem;" onclick="navigator.clipboard.writeText(document.getElementById('raw-packet-pre').innerText); showToast('Packet copied')">COPY</button>

                        </div>

                        <pre id="raw-packet-pre" class="technical-report" style="background:#000; padding:30px; border-radius:12px; border:1px solid var(--border); color:var(--text); font-family:monospace; font-size:0.8rem; line-height:1.2; overflow-x:auto;">${data.review_packet_text || 'No packet text available.'}</pre>

                    </div>

                </div>

            </div>

        </div>

    `;

    

    // Also populate Patch Lab if available

    if (data.troy_patch) {

        renderPatchLab(data.troy_patch);

    }

}



function generateCompletionStats(runs) {

    const stats = {};

    runs.forEach(r => {

        const reason = r.completion_reason || 'unknown';

        stats[reason] = (stats[reason] || 0) + 1;

    });

    return Object.entries(stats).map(([reason, count]) => `

        <div class="stat-row" style="display:flex; justify-content:space-between; padding:8px 0; border-bottom:1px solid rgba(255,255,255,0.05);">

            <span style="color:var(--text-dim); text-transform:capitalize;">${reason.replace(/_/g, ' ')}</span>

            <span class="gold-text" style="font-weight:700;">${count}</span>

        </div>

    `).join('');

}



function renderPatchLab(patch) {

    const container = document.getElementById('dojo-patch-container');

    container.innerHTML = `

        <div class="patch-lab-layout">

             <div class="patch-meta">

                <h3 class="gold-text cinzel">APEX / Hermes Patch Lab</h3>

                <div class="patch-reason" style="color:var(--warning); font-style:italic; margin-bottom:20px;">Issue: ${patch.issue_summary || 'No summary available'}</div>

            </div>

            <div class="patch-editor-split" style="display:grid; grid-template-columns: 1fr 350px; gap:40px;">

                <div class="patch-code-panel">

                    <h4 class="gold-text">Proposed Prompt Patch</h4>

                    <pre class="patch-diff" style="background:#000; padding:20px; border-radius:12px; border:1px solid var(--border); color:#a8dadc; overflow-x:auto;">${patch.patch || 'No patch generated'}</pre>

                    

                    <div class="patch-comparison" style="margin-top:30px; display:grid; grid-template-columns: 1fr 1fr; gap:20px;">

                        <div>

                            <h5 style="color:var(--text-dim); font-size:0.7rem; text-transform:uppercase;">Before (Original)</h5>

                            <div style="font-size:0.8rem; height:150px; overflow-y:auto; padding:10px; background:rgba(255,0,0,0.05); border:1px solid rgba(239,68,68,0.2); border-radius:8px;">${patch.before_prompt || 'N/A'}</div>

                        </div>

                        <div>

                            <h5 style="color:var(--text-dim); font-size:0.7rem; text-transform:uppercase;">After (Optimized)</h5>

                            <div style="font-size:0.8rem; height:150px; overflow-y:auto; padding:10px; background:rgba(0,255,0,0.05); border:1px solid rgba(16,185,129,0.2); border-radius:8px;">${patch.after_prompt || 'N/A'}</div>

                        </div>

                    </div>

                </div>

                <div class="patch-rationale">

                    <h4 class="gold-text">Rationale</h4>

                    <p style="font-size:0.9rem; line-height:1.6; color:var(--text-dim);">${patch.rationale || 'No rationale available'}</p>

                    <div class="patch-actions" style="margin-top:30px; display:flex; flex-direction:column; gap:15px;">

                        <button class="dojo-primary-btn" onclick="copyPatchToClipboard()">COPY PATCH TO CLIPBOARD</button>

                        <button class="dojo-secondary-btn" onclick="rerunFailedScenarios()">RERUN FAILED ONLY</button>

                    </div>

                </div>

            </div>

        </div>

    `;

}



async function loadDojoHistory() {

    try {

        const response = await fetch(`${API_BASE}/api/dojo/history`);

        const history = await response.json();

        const list = document.getElementById('dojo-history-list');

        list.innerHTML = history.map(item => `

            <div class="history-item" onclick="loadBatchResults('${item.batch_id}'); switchDojoTab('results');">

                <div class="b-id">${item.batch_id}</div>

                <div class="b-agent">${item.target_agent} :: ${item.scenario_pack}</div>

                <div class="b-meta">Score: ${item.average_score}% | ${item.verdict}</div>

            </div>

        `).join('');

    } catch (e) {}

}



async function loadLatestDojoReport() {

    try {

        const response = await fetch(`${API_BASE}/api/dojo/history`);

        const history = await response.json();

        if (history.length) {

            finishDojoMission(history[0].batch_id);

        }

    } catch (e) {}

}



function renderReviewCard(title, result) {

    if (!result) return `<div class="review-card empty"><h5>${title}</h5><p style="font-size:0.8rem; color:var(--text-dim);">No findings.</p></div>`;

    

    // Defensive extraction for different result formats

    const findings = (result.scorecard_analysis && result.scorecard_analysis.findings) || result.findings || [];

    const summary = (result.scorecard_analysis && result.scorecard_analysis.summary) || result.summary || 'No summary provided.';

    const status = result.status || 'pending';

    const score = result.logic_score || (result.scorecard_analysis && result.scorecard_analysis.persona_alignment_score) || result.safety_score || 'N/A';



    return `

        <div class="review-card" style="background:rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.05); border-radius:12px; padding:20px;">

            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">

                <h5 style="font-size:0.75rem; text-transform:uppercase; color:var(--gold);">${title}</h5>

                <span style="font-size:0.65rem; padding:2px 6px; border-radius:4px; background:${status === 'pass' ? 'rgba(16,185,129,0.2)' : 'rgba(239,68,68,0.2)'}; color:${status === 'pass' ? 'var(--success)' : 'var(--error)'}">${status.toUpperCase()}</span>

            </div>

            <div style="font-size:1.1rem; font-weight:700; margin-bottom:10px;">${score !== 'N/A' ? score + '%' : ''}</div>

            <p style="font-size:0.8rem; color:var(--text-dim); margin-bottom:15px; line-height:1.4;">${summary}</p>

            <ul style="padding-left:15px; font-size:0.75rem; color:var(--text-dim); line-height:1.5;">

                ${findings.slice(0, 3).map(f => `<li>${f}</li>`).join('')}

            </ul>

        </div>

    `;

}


// ======================================================================
// ADRIAN LIVE DRILL - Coaching Dashboard
// ======================================================================

let activeDrillSessionId = null;
let drillSending = false;

async function startDrillSession() {
    const btn = document.getElementById('drill-start-btn');
    if (btn) btn.disabled = true;
    showToast("Initializing Adrian coaching session...", false);
    try {
        const response = await fetch(API_BASE + '/api/drill/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({})
        });
        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Failed to start drill session');
        }
        const data = await response.json();
        activeDrillSessionId = data.session_id;
        document.getElementById('drill-kb-status').innerText = 'KB: ' + data.kb_files_loaded + ' files';
        document.getElementById('drill-memory-status').innerText = 'Memory: ' + data.memory_sessions_loaded + ' sessions';
        document.getElementById('drill-turn-count').innerText = 'Turns: 1';
        const transcript = document.getElementById('drill-transcript');
        transcript.innerHTML = '';
        appendDrillBubble('adrian', data.greeting);
        document.getElementById('drill-input-area').style.display = 'flex';
        document.getElementById('drill-input').focus();
        showToast('Adrian online - Model: ' + data.model, false);
        loadDrillHistory();
    } catch (e) {
        showToast('Drill Error: ' + e.message, true);
        if (btn) btn.disabled = false;
    }
}

async function sendDrillMessage() {
    if (drillSending || !activeDrillSessionId) return;
    const input = document.getElementById('drill-input');
    const message = input.value.trim();
    if (!message) return;
    drillSending = true;
    const sendBtn = document.getElementById('drill-send-btn');
    sendBtn.disabled = true;
    sendBtn.innerText = '...';
    appendDrillBubble('user', message);
    input.value = '';
    try {
        const response = await fetch(API_BASE + '/api/drill/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: activeDrillSessionId, message: message })
        });
        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Chat failed');
        }
        const data = await response.json();
        appendDrillBubble('adrian', data.response);
        document.getElementById('drill-turn-count').innerText = 'Turns: ' + data.turn_count;
    } catch (e) {
        appendDrillBubble('system', 'Error: ' + e.message);
    } finally {
        drillSending = false;
        sendBtn.disabled = false;
        sendBtn.innerText = 'Send';
        input.focus();
    }
}

async function endDrillSession() {
    if (!activeDrillSessionId) { showToast("No active session to end.", true); return; }
    showToast("Saving session and generating coaching summary...", false);
    try {
        const response = await fetch(API_BASE + '/api/drill/end', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: activeDrillSessionId })
        });
        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Failed to end session');
        }
        const data = await response.json();
        appendDrillBubble('system', 'Session saved (' + data.turn_count + ' turns). Coaching summary: ' + data.coaching_summary);
        document.getElementById('drill-input-area').style.display = 'none';
        const transcript = document.getElementById('drill-transcript');
        const restartDiv = document.createElement('div');
        restartDiv.className = 'drill-restart-area';
        restartDiv.innerHTML = '<button class="dojo-primary-btn" onclick="startDrillSession()">Start New Session</button>';
        transcript.appendChild(restartDiv);
        activeDrillSessionId = null;
        showToast("Session saved to Adrian memory.", false);
        loadDrillHistory();
    } catch (e) { showToast('Save Error: ' + e.message, true); }
}

function appendDrillBubble(role, text) {
    const transcript = document.getElementById('drill-transcript');
    const bubble = document.createElement('div');
    bubble.className = 'drill-bubble drill-' + role;
    const label = role === 'adrian' ? 'ADRIAN' : (role === 'user' ? 'ROB' : 'SYSTEM');
    const safeText = document.createElement('div');
    safeText.innerText = text;
    bubble.innerHTML = '<span class="drill-speaker">' + label + '</span><div class="drill-text">' + safeText.innerHTML + '</div>';
    transcript.appendChild(bubble);
    transcript.scrollTop = transcript.scrollHeight;
    if (role === 'adrian' && typeof speakDrillText === 'function') { speakDrillText(text); }
}

async function loadDrillHistory() {
    try {
        const response = await fetch(API_BASE + '/api/drill/history');
        const history = await response.json();
        const list = document.getElementById('drill-history-list');
        if (!list) return;
        if (history.length === 0) { list.innerHTML = '<div class="history-empty">No past sessions yet.</div>'; return; }
        list.innerHTML = history.map(function(item) {
            var summary = item.coaching_summary ? item.coaching_summary.substring(0, 100) + '...' : 'No summary';
            return '<div class="history-item" onclick="loadDrillSession(\'' + item.session_id + '\')">' +
                '<div class="b-id">' + item.session_id + '</div>' +
                '<div class="b-agent">Turns: ' + item.turn_count + '</div>' +
                '<div class="b-meta" style="font-size:0.7rem;color:var(--text-dim);margin-top:4px;">' + summary + '</div></div>';
        }).join('');
    } catch (e) { console.warn("Failed to load drill history"); }
}

async function loadDrillSession(sessionId) {
    try {
        const response = await fetch(API_BASE + '/api/drill/session/' + sessionId);
        const data = await response.json();
        const transcript = document.getElementById('drill-transcript');
        transcript.innerHTML = '';
        (data.turns || []).forEach(function(turn) {
            appendDrillBubble(turn.role === 'user' ? 'user' : 'adrian', turn.content);
        });
        if (data.coaching_summary) { appendDrillBubble('system', 'Coaching Summary: ' + data.coaching_summary); }
        document.getElementById('drill-input-area').style.display = 'none';
        activeDrillSessionId = null;
        var restartDiv = document.createElement('div');
        restartDiv.className = 'drill-restart-area';
        restartDiv.innerHTML = '<button class="dojo-primary-btn" onclick="startDrillSession()">Start New Session</button>';
        transcript.appendChild(restartDiv);
    } catch (e) { showToast("Failed to load session", true); }
}

document.addEventListener('keydown', function(e) {
    if (e.target.id === 'drill-input' && e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendDrillMessage();
    }
});
// --------------------------------------------------------------
// ADRIAN LIVE DRILL  Voice IO (STT + TTS)
// --------------------------------------------------------------

var drillTTSEnabled = false;
var drillRecognition = null;
var drillRecognizing = false;

// -- Text-to-Speech (Adrian speaks) ----------------------------

function toggleDrillTTS() {
    drillTTSEnabled = !drillTTSEnabled;
    var btn = document.getElementById('drill-tts-toggle');
    if (btn) {
        btn.innerText = drillTTSEnabled ? '\uD83D\uDD0A Voice On' : '\uD83D\uDD07 Voice Off';
        btn.classList.toggle('active', drillTTSEnabled);
    }
    if (!drillTTSEnabled) { window.speechSynthesis.cancel(); }
    showToast(drillTTSEnabled ? 'Adrian voice enabled' : 'Adrian voice disabled', false);
}

var drillAudio = null;

async function speakDrillText(text) {
    if (!drillTTSEnabled) return;
    
    if (drillAudio) { 
        drillAudio.pause(); 
        drillAudio = null; 
    }

    try {
        const response = await fetch(API_BASE + '/api/drill/speak', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: text })
        });
        
        if (!response.ok) throw new Error('Neural TTS failed');
        
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        drillAudio = new Audio(url);
        drillAudio.play();
    } catch (e) {
        console.warn("Neural TTS Error:", e);
        // Fallback to browser TTS if desired, but we prefer neural
    }
}

// -- Speech-to-Text (Rob speaks) ------------------------------

var drillMediaRecorder = null;
var drillAudioChunks = [];

function toggleDrillMic() {
    if (drillRecognizing) {
        stopDrillMic();
        return;
    }

    navigator.mediaDevices.getUserMedia({ audio: true }).then(function(stream) {
        drillMediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });
        drillAudioChunks = [];

        var micBtn = document.getElementById('drill-mic-btn');

        drillMediaRecorder.ondataavailable = function(event) {
            if (event.data.size > 0) { drillAudioChunks.push(event.data); }
        };

        drillMediaRecorder.onstop = function() {
            drillRecognizing = false;
            if (micBtn) { micBtn.classList.remove('recording'); micBtn.innerText = '\uD83C\uDF99'; }
            stream.getTracks().forEach(function(t) { t.stop(); });

            if (drillAudioChunks.length === 0) return;

            var blob = new Blob(drillAudioChunks, { type: 'audio/webm' });
            var formData = new FormData();
            formData.append('audio', blob, 'recording.webm');

            showToast('Transcribing with local Whisper...', false);

            fetch(API_BASE + '/api/drill/transcribe', {
                method: 'POST',
                body: formData
            }).then(function(resp) {
                if (!resp.ok) throw new Error('Transcription failed');
                return resp.json();
            }).then(function(data) {
                var input = document.getElementById('drill-input');
                if (input && data.text) {
                    input.value = (input.value ? input.value + ' ' : '') + data.text;
                    input.focus();
                    showToast('Transcribed (' + data.duration + 's audio)', false);
                }
            }).catch(function(err) {
                showToast('Transcription error: ' + err.message, true);
            });
        };

        drillMediaRecorder.start();
        drillRecognizing = true;
        if (micBtn) { micBtn.classList.add('recording'); micBtn.innerText = '\uD83D\uDD34'; }
        showToast('Recording... click mic again to stop', false);

    }).catch(function(err) {
        showToast('Microphone access denied: ' + err.message, true);
    });
}

function stopDrillMic() {
    if (drillMediaRecorder && drillMediaRecorder.state === 'recording') {
        drillMediaRecorder.stop();
    }
    drillRecognizing = false;
    var micBtn = document.getElementById('drill-mic-btn');
    if (micBtn) { micBtn.classList.remove('recording'); micBtn.innerText = '\uD83C\uDF99'; }
}
