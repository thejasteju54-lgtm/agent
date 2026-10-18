/**
 * MarketPulse AI — Client Application Controller
 * Handles REST API communication, live polling, and UI interactions.
 */

const API_BASE = '/api/v1';

// State
let activeTaskId = null;
let pollTimer = null;

// DOM Elements
document.addEventListener('DOMContentLoaded', () => {
  initTabs();
  initClock();
  initHealthCheck();
  initTaskForm();
  initEmergencyStop();
  initModal();

  // Initial Data Loads
  loadTasks();
  loadReports();
  loadWatchlists();
  loadAlerts();
  loadSchedules();
  loadApprovals();
  loadAudit();

  // Background refresh cycle (every 10s)
  setInterval(() => {
    loadApprovals();
    loadTasks();
  }, 10000);
});

// ---------------------------------------------------------------------------
// Tabs Navigation
// ---------------------------------------------------------------------------
function initTabs() {
  const tabs = document.querySelectorAll('.nav-tab-btn');
  tabs.forEach(btn => {
    btn.addEventListener('click', () => {
      tabs.forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));

      btn.classList.add('active');
      const targetId = btn.getAttribute('data-tab');
      const pane = document.getElementById(targetId);
      if (pane) pane.classList.add('active');
    });
  });
}

// ---------------------------------------------------------------------------
// IST Clock
// ---------------------------------------------------------------------------
function initClock() {
  const clockEl = document.getElementById('header-ist-time');
  function update() {
    const now = new Date();
    // Format to Asia/Kolkata
    const istString = now.toLocaleTimeString('en-US', {
      timeZone: 'Asia/Kolkata',
      hour12: false,
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
    if (clockEl) {
      clockEl.innerHTML = `<span>IST: ${istString}</span>`;
    }
  }
  update();
  setInterval(update, 1000);
}

// ---------------------------------------------------------------------------
// Health Probes & System Status
// ---------------------------------------------------------------------------
async function initHealthCheck() {
  try {
    const res = await fetch(`${API_BASE}/health`);
    if (!res.ok) throw new Error('Health probe returned non-200');
    const data = await res.json();

    const modeText = document.getElementById('header-mode-text');
    if (modeText) modeText.textContent = `${(data.mode || 'DESKTOP').toUpperCase()} MODE`;

    const n8nText = document.getElementById('header-n8n-text');
    if (n8nText) {
      const isLive = data.n8n_status === 'CONNECTED';
      n8nText.textContent = `n8n: ${isLive ? 'CONNECTED' : 'STANDBY'}`;
      n8nText.style.color = isLive ? 'var(--accent-emerald)' : 'var(--accent-amber)';
    }

    const statDb = document.getElementById('stat-db-status');
    if (statDb) {
      statDb.textContent = data.database_connected ? 'CONNECTED' : 'ERROR';
      statDb.style.color = data.database_connected ? 'var(--accent-emerald)' : 'var(--accent-rose)';
    }

    const statN8n = document.getElementById('stat-n8n-status');
    if (statN8n) {
      statN8n.textContent = data.n8n_status === 'CONNECTED' ? 'ONLINE' : 'STANDBY';
    }
  } catch (err) {
    console.error('Failed to query health probe:', err);
  }
}

// ---------------------------------------------------------------------------
// Emergency Stop
// ---------------------------------------------------------------------------
function initEmergencyStop() {
  const btn = document.getElementById('btn-emergency-stop');
  if (!btn) return;

  btn.addEventListener('click', async () => {
    const confirmStop = confirm('Are you sure you want to trigger the global EMERGENCY STOP?\nAll running automation tasks will immediately halt.');
    if (!confirmStop) return;

    try {
      const res = await fetch('/webhook/notify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          event_type: 'EMERGENCY_STOP_TRIGGERED',
          message: 'Operator pressed UI Emergency Stop button',
          details: { origin: 'Web Dashboard' },
        }),
      });
      alert('EMERGENCY STOP SIGNAL SENT: The runtime has halted active task steps.');
      loadTasks();
    } catch (err) {
      alert('Error triggering emergency stop: ' + err.message);
    }
  });
}

// ---------------------------------------------------------------------------
// Tasks Management & Live Execution Tracker
// ---------------------------------------------------------------------------
function initTaskForm() {
  const form = document.getElementById('task-submit-form');
  const refreshBtn = document.getElementById('btn-refresh-tasks');

  if (refreshBtn) refreshBtn.addEventListener('click', loadTasks);

  if (form) {
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const prompt = document.getElementById('task-prompt').value.trim();
      const ticker = document.getElementById('task-ticker').value.trim() || null;
      const taskType = document.getElementById('task-type').value;
      const autoApprove = document.getElementById('task-auto-approve').checked;

      const submitBtn = document.getElementById('btn-submit-task');
      submitBtn.disabled = true;
      submitBtn.innerHTML = `<span>Submitting...</span>`;

      try {
        const payload = {
          prompt: prompt,
          company_symbol: ticker,
          task_type: taskType,
          sync_execute: false,
        };

        const res = await fetch('/webhook/task', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });

        if (!res.ok) throw new Error('Task creation failed: ' + (await res.text()));
        const data = await res.json();

        activeTaskId = data.task_id;
        startActiveTaskPolling(activeTaskId, prompt);
        loadTasks();
        form.reset();
      } catch (err) {
        alert('Task submission error: ' + err.message);
      } finally {
        submitBtn.disabled = false;
        submitBtn.innerHTML = `<span>Execute Task</span> →`;
      }
    });
  }
}

function startActiveTaskPolling(taskId, prompt) {
  if (pollTimer) clearInterval(pollTimer);

  const cardBody = document.getElementById('active-task-body');
  const pill = document.getElementById('active-task-pill');

  pill.className = 'pill pill-running';
  pill.textContent = 'RUNNING';

  cardBody.innerHTML = `
    <div style="font-size: 0.85rem; margin-bottom: 0.75rem;">
      <strong style="color: var(--accent-cyan);">Task ID:</strong> <code>${taskId}</code>
    </div>
    <div style="font-size: 0.9rem; margin-bottom: 1rem; color: var(--text-primary);">
      ${escapeHtml(prompt)}
    </div>
    <div style="background: rgba(255,255,255,0.06); height: 6px; border-radius: 3px; overflow: hidden; margin-bottom: 1rem;">
      <div id="active-task-progress-bar" style="background: var(--accent-cyan); width: 25%; height: 100%; transition: width 0.3s ease;"></div>
    </div>
    <div style="display: flex; justify-content: space-between; align-items: center;">
      <span id="active-task-status-text" style="font-size: 0.8rem; color: var(--text-muted);">Step: In progress...</span>
      <button class="btn-danger btn-sm" onclick="cancelActiveTask('${taskId}')">Cancel</button>
    </div>
  `;

  pollTimer = setInterval(async () => {
    try {
      const res = await fetch(`/webhook/task/${taskId}`);
      if (!res.ok) return;
      const data = await res.json();

      const status = data.status.toUpperCase();
      const progressBar = document.getElementById('active-task-progress-bar');
      const statusText = document.getElementById('active-task-status-text');

      if (statusText) {
        statusText.textContent = `Status: ${status} (Step: ${data.current_step || 0}/${data.step_limit || 20})`;
      }

      if (progressBar) {
        const pct = Math.min(100, Math.max(10, ((data.current_step || 1) / (data.step_limit || 20)) * 100));
        progressBar.style.width = `${pct}%`;
      }

      if (['COMPLETED', 'FAILED', 'CANCELLED'].includes(status)) {
        clearInterval(pollTimer);
        pollTimer = null;
        pill.className = status === 'COMPLETED' ? 'pill pill-completed' : 'pill pill-failed';
        pill.textContent = status;

        if (status === 'COMPLETED' && data.result_summary) {
          cardBody.innerHTML += `
            <div style="margin-top: 1rem; padding: 0.75rem; background: rgba(0,255,136,0.05); border-left: 3px solid var(--accent-emerald); font-size: 0.85rem;">
              <strong>Result:</strong> ${escapeHtml(data.result_summary)}
            </div>
          `;
        }
        loadTasks();
        loadReports();
      }
    } catch (e) {
      console.warn('Polling error:', e);
    }
  }, 2000);
}

async function cancelActiveTask(taskId) {
  try {
    const res = await fetch(`${API_BASE}/tasks/${taskId}/cancel`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason: 'Cancelled from Dashboard UI' }),
    });
    if (res.ok) {
      alert('Task cancelled successfully.');
      loadTasks();
    }
  } catch (err) {
    alert('Failed to cancel task: ' + err.message);
  }
}

async function loadTasks() {
  const tbody = document.getElementById('tasks-tbody');
  if (!tbody) return;

  try {
    const res = await fetch(`${API_BASE}/tasks?limit=15`);
    if (!res.ok) throw new Error('Failed to load tasks');
    const tasks = await res.json();

    if (!tasks || tasks.length === 0) {
      tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--text-muted);">No tasks found.</td></tr>`;
      return;
    }

    tbody.innerHTML = tasks.map(t => {
      const statusPill = getStatusPill(t.status);
      return `
        <tr>
          <td><code style="font-size:0.75rem;">${t.id.slice(0, 8)}...</code></td>
          <td><span class="pill pill-info">${t.task_type || 'RESEARCH'}</span></td>
          <td>${statusPill}</td>
          <td style="max-width: 250px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${escapeHtml(t.prompt)}</td>
          <td>${t.current_step || 0}/${t.step_limit || 20}</td>
          <td style="font-size:0.75rem;">${formatDate(t.started_at)}</td>
          <td>
            ${t.status === 'RUNNING' ? `<button class="btn-danger btn-sm" onclick="cancelActiveTask('${t.id}')">Cancel</button>` : `<span style="color:var(--text-muted); font-size:0.75rem;">-</span>`}
          </td>
        </tr>
      `;
    }).join('');
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="7" style="color: var(--accent-rose); text-align: center;">Error: ${err.message}</td></tr>`;
  }
}

// ---------------------------------------------------------------------------
// Research Reports Archive
// ---------------------------------------------------------------------------
async function loadReports() {
  const tbody = document.getElementById('reports-tbody');
  const refreshBtn = document.getElementById('btn-refresh-reports');
  if (refreshBtn) refreshBtn.addEventListener('click', loadReports);
  if (!tbody) return;

  try {
    const res = await fetch(`${API_BASE}/research/reports?limit=20`);
    if (!res.ok) throw new Error('Failed to load reports');
    const reports = await res.json();

    if (!reports || reports.length === 0) {
      tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--text-muted);">No research reports generated yet.</td></tr>`;
      return;
    }

    tbody.innerHTML = reports.map(r => {
      return `
        <tr>
          <td><code>${r.report_id ? r.report_id.slice(0, 8) : r.id.slice(0, 8)}...</code></td>
          <td><strong style="color: var(--accent-cyan);">${r.company_symbol || 'INDIAN_MARKET'}</strong></td>
          <td>${r.sector_name || 'Multi-Sector'}</td>
          <td style="font-weight: 600; color: var(--text-primary);">${escapeHtml(r.title)}</td>
          <td><span class="pill pill-completed">${r.evidence_references ? r.evidence_references.length : 0} Verified</span></td>
          <td style="font-size: 0.75rem;">${formatDate(r.created_at)}</td>
          <td>
            <button class="btn-secondary btn-sm" onclick="openReportModal('${r.id || r.report_id}')">View</button>
          </td>
        </tr>
      `;
    }).join('');
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="7" style="color: var(--accent-rose); text-align: center;">Error: ${err.message}</td></tr>`;
  }
}

async function openReportModal(reportId) {
  const modal = document.getElementById('report-modal');
  const title = document.getElementById('modal-report-title');
  const body = document.getElementById('modal-report-body');

  body.innerHTML = `<p style="color: var(--text-muted);">Loading report details...</p>`;
  modal.classList.add('active');

  try {
    const res = await fetch(`${API_BASE}/research/reports/${reportId}`);
    if (!res.ok) throw new Error('Report not found');
    const rep = await res.json();

    title.textContent = rep.title;
    body.innerHTML = `
      <div style="margin-bottom: 1.25rem;">
        <span class="pill pill-info">${rep.company_symbol || 'GENERAL'}</span>
        <span class="pill pill-completed" style="margin-left: 0.5rem;">${rep.sector_name || 'Broad Market'}</span>
      </div>
      <div style="margin-bottom: 1.5rem;">
        <h4 style="color: var(--text-secondary); text-transform: uppercase; font-size: 0.8rem; margin-bottom: 0.5rem;">Executive Summary</h4>
        <div style="background: rgba(255,255,255,0.03); padding: 1rem; border-radius: var(--radius-md); font-size: 0.9rem; line-height: 1.6; white-space: pre-wrap;">
          ${escapeHtml(rep.executive_summary || 'No summary available.')}
        </div>
      </div>
      ${rep.scenarios ? `
        <div style="margin-bottom: 1.5rem;">
          <h4 style="color: var(--text-secondary); text-transform: uppercase; font-size: 0.8rem; margin-bottom: 0.5rem;">Scenario Analysis</h4>
          <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 0.75rem; font-size: 0.85rem;">
            <div style="background: rgba(0,255,136,0.05); border: 1px solid rgba(0,255,136,0.2); padding: 0.75rem; border-radius: var(--radius-md);">
              <strong style="color: var(--accent-emerald);">Bull Case:</strong><br>${escapeHtml(rep.scenarios.bull_case || '-')}
            </div>
            <div style="background: rgba(0,240,255,0.05); border: 1px solid rgba(0,240,255,0.2); padding: 0.75rem; border-radius: var(--radius-md);">
              <strong style="color: var(--accent-cyan);">Base Case:</strong><br>${escapeHtml(rep.scenarios.base_case || '-')}
            </div>
            <div style="background: rgba(255,51,102,0.05); border: 1px solid rgba(255,51,102,0.2); padding: 0.75rem; border-radius: var(--radius-md);">
              <strong style="color: var(--accent-rose);">Bear Case:</strong><br>${escapeHtml(rep.scenarios.bear_case || '-')}
            </div>
          </div>
        </div>
      ` : ''}
      <div>
        <h4 style="color: var(--text-secondary); text-transform: uppercase; font-size: 0.8rem; margin-bottom: 0.5rem;">Verified Evidence & Primary Citations</h4>
        <div class="data-table-container">
          <table class="data-table">
            <thead><tr><th>Verified Fact</th><th>Primary Source</th></tr></thead>
            <tbody>
              ${(rep.evidence_references && rep.evidence_references.length > 0) ? rep.evidence_references.map(ev => `
                <tr>
                  <td>${escapeHtml(ev.fact || ev.content_preview || '-')}</td>
                  <td>${ev.url ? `<a href="${ev.url}" target="_blank" style="color: var(--accent-cyan); text-decoration: none;">Link ↗</a>` : '-'}</td>
                </tr>
              `).join('') : `<tr><td colspan="2" style="color: var(--text-muted);">No external citations.</td></tr>`}
            </tbody>
          </table>
        </div>
      </div>
    `;
  } catch (err) {
    body.innerHTML = `<p style="color: var(--accent-rose);">Error: ${err.message}</p>`;
  }
}

function initModal() {
  const modal = document.getElementById('report-modal');
  const closeBtn = document.getElementById('btn-close-modal');
  if (closeBtn) closeBtn.addEventListener('click', () => modal.classList.remove('active'));
  if (modal) {
    modal.addEventListener('click', (e) => {
      if (e.target === modal) modal.classList.remove('active');
    });
  }
}

// ---------------------------------------------------------------------------
// Market Brief & Calendar
// ---------------------------------------------------------------------------
const generateBriefBtn = document.getElementById('btn-generate-brief');
if (generateBriefBtn) {
  generateBriefBtn.addEventListener('click', async () => {
    generateBriefBtn.disabled = true;
    generateBriefBtn.textContent = 'Generating Brief...';
    try {
      const res = await fetch(`${API_BASE}/research/brief`, { method: 'POST' });
      if (!res.ok) throw new Error('Brief generation failed');
      const brief = await res.json();

      document.getElementById('brief-session-state').textContent = brief.session_state || 'REGULAR SESSION';
      document.getElementById('brief-calendar-date').textContent = brief.session_date || 'Today';
      document.getElementById('brief-summary-content').textContent = brief.executive_summary;

      const statContainer = document.getElementById('brief-statistics-container');
      if (brief.verified_statistics && brief.verified_statistics.length > 0) {
        statContainer.innerHTML = brief.verified_statistics.map(s => `
          <div style="background: rgba(255,255,255,0.03); padding: 0.75rem; border-radius: var(--radius-md); margin-bottom: 0.5rem;">
            <div style="font-size: 0.75rem; color: var(--text-muted);">${s.company_name} (${s.symbol})</div>
            <div style="font-family: var(--font-mono); font-size: 1.1rem; font-weight: 700; color: var(--text-primary);">${s.value}</div>
            <div style="font-size: 0.7rem; color: var(--accent-cyan);">${s.observation_date} • ${s.source_reference}</div>
          </div>
        `).join('');
      } else {
        statContainer.innerHTML = `<p style="color: var(--text-muted); font-size: 0.85rem;">No verified observations in window.</p>`;
      }
    } catch (err) {
      alert('Error: ' + err.message);
    } finally {
      generateBriefBtn.disabled = false;
      generateBriefBtn.textContent = "Generate Today's Brief";
    }
  });
}

// ---------------------------------------------------------------------------
// Watchlists & Alerts
// ---------------------------------------------------------------------------
async function loadWatchlists() {
  const container = document.getElementById('watchlist-container');
  const countBadge = document.getElementById('watchlist-symbol-count');
  if (!container) return;

  try {
    const res = await fetch(`${API_BASE}/watchlists`);
    if (!res.ok) throw new Error('Failed to load watchlists');
    const watchlists = await res.json();

    if (!watchlists || watchlists.length === 0) {
      container.innerHTML = `<p style="color: var(--text-muted);">No active watchlists found.</p>`;
      return;
    }

    let totalSymbols = 0;
    container.innerHTML = watchlists.map(wl => {
      const items = wl.items || [];
      totalSymbols += items.length;
      return `
        <div style="background: rgba(255,255,255,0.03); border: 1px solid var(--border-subtle); border-radius: var(--radius-md); padding: 1rem; margin-bottom: 0.75rem;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
            <strong style="color: var(--accent-cyan); font-size: 0.95rem;">${escapeHtml(wl.name)}</strong>
            <span class="pill pill-completed">${items.length} TICKERS</span>
          </div>
          <div style="font-size: 0.85rem; color: var(--text-secondary); margin-bottom: 0.5rem;">${escapeHtml(wl.description || '')}</div>
          <div style="display: flex; flex-wrap: wrap; gap: 0.4rem;">
            ${items.map(it => `<span class="pill pill-info" style="font-size: 0.7rem;">${it.company ? it.company.symbol : it.symbol || 'TICKER'}</span>`).join('')}
          </div>
        </div>
      `;
    }).join('');

    if (countBadge) countBadge.textContent = `${totalSymbols} SYMBOLS`;
  } catch (err) {
    container.innerHTML = `<p style="color: var(--accent-rose);">Error: ${err.message}</p>`;
  }
}

async function loadAlerts() {
  const tbody = document.getElementById('alerts-tbody');
  const evalBtn = document.getElementById('btn-evaluate-alerts');

  if (evalBtn) {
    evalBtn.addEventListener('click', async () => {
      evalBtn.disabled = true;
      evalBtn.textContent = 'Evaluating...';
      try {
        const res = await fetch(`${API_BASE}/alerts/evaluate`, { method: 'POST' });
        if (res.ok) {
          const resData = await res.json();
          alert(`Watchlist alert evaluation complete!\nAlerts triggered: ${resData.alerts_triggered_count}`);
          loadAlerts();
        }
      } catch (e) {
        alert('Evaluation failed: ' + e.message);
      } finally {
        evalBtn.disabled = false;
        evalBtn.textContent = 'Evaluate Now';
      }
    });
  }

  if (!tbody) return;

  try {
    const res = await fetch(`${API_BASE}/alerts/events?limit=20`);
    if (!res.ok) throw new Error('Failed to load alert events');
    const alerts = await res.json();

    if (!alerts || alerts.length === 0) {
      tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: var(--text-muted);">No alert events recorded yet.</td></tr>`;
      return;
    }

    tbody.innerHTML = alerts.map(a => {
      const sevClass = a.severity === 'CRITICAL' || a.severity === 'HIGH' ? 'pill-failed' : (a.severity === 'MEDIUM' ? 'pill-pending' : 'pill-info');
      return `
        <tr>
          <td><span class="pill ${sevClass}">${a.severity}</span></td>
          <td><strong style="color: var(--accent-cyan);">${a.company_symbol}</strong></td>
          <td><span class="pill pill-info" style="font-size: 0.65rem;">${a.event_category}</span></td>
          <td>
            <div style="font-weight: 600; color: var(--text-primary); font-size: 0.85rem;">${escapeHtml(a.title)}</div>
            <div style="font-size: 0.75rem; color: var(--text-secondary); margin-top: 0.2rem;">${escapeHtml(a.trigger_rationale)}</div>
          </td>
          <td style="font-size: 0.75rem;">${formatDate(a.created_at)}</td>
        </tr>
      `;
    }).join('');
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="5" style="color: var(--accent-rose); text-align: center;">Error: ${err.message}</td></tr>`;
  }
}

// ---------------------------------------------------------------------------
// Schedules & Automation
// ---------------------------------------------------------------------------
async function loadSchedules() {
  const tbody = document.getElementById('schedules-tbody');
  if (!tbody) return;

  try {
    const res = await fetch(`${API_BASE}/schedules`);
    if (!res.ok) throw new Error('Failed to load schedules');
    const schedules = await res.json();

    if (!schedules || schedules.length === 0) {
      tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--text-muted);">No schedules configured.</td></tr>`;
      return;
    }

    tbody.innerHTML = schedules.map(s => {
      const statusPill = s.is_active ? '<span class="pill pill-completed">ACTIVE</span>' : '<span class="pill pill-failed">DISABLED</span>';
      const dryPill = s.dry_run ? '<span class="pill pill-pending">DRY RUN</span>' : '<span class="pill pill-info">LIVE</span>';
      return `
        <tr>
          <td><code>${s.id}</code></td>
          <td style="font-weight: 600; color: var(--text-primary);">${escapeHtml(s.name)}</td>
          <td><code style="color: var(--accent-cyan);">${s.cron_expression || s.schedule_type}</code></td>
          <td>${s.timezone}</td>
          <td><span class="pill pill-info">${s.task_type}</span></td>
          <td>${dryPill}</td>
          <td>${statusPill}</td>
          <td>
            <button class="btn-primary btn-sm" onclick="triggerSchedule('${s.id}')">Trigger Now</button>
            <button class="btn-secondary btn-sm" style="margin-left: 4px;" onclick="toggleSchedule('${s.id}', ${!s.is_active})">
              ${s.is_active ? 'Disable' : 'Enable'}
            </button>
          </td>
        </tr>
      `;
    }).join('');
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="8" style="color: var(--accent-rose); text-align: center;">Error: ${err.message}</td></tr>`;
  }
}

async function triggerSchedule(scheduleId) {
  try {
    const res = await fetch(`${API_BASE}/schedules/${scheduleId}/trigger`, { method: 'POST' });
    if (!res.ok) throw new Error('Trigger failed: ' + (await res.text()));
    const data = await res.json();
    alert(`Schedule '${data.name}' dispatched!\nMode: ${data.is_dry_run ? 'SIMULATION / DRY RUN' : 'LIVE TASK'}\nStatus: ${data.status}`);
    loadTasks();
  } catch (e) {
    alert('Error triggering schedule: ' + e.message);
  }
}

async function toggleSchedule(scheduleId, newState) {
  try {
    const res = await fetch(`${API_BASE}/schedules/${scheduleId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_active: newState }),
    });
    if (res.ok) {
      loadSchedules();
    }
  } catch (e) {
    alert('Error updating schedule: ' + e.message);
  }
}

// ---------------------------------------------------------------------------
// Human Approvals Gate
// ---------------------------------------------------------------------------
async function loadApprovals() {
  const tbody = document.getElementById('approvals-tbody');
  const countBadge = document.getElementById('approval-count-badge');
  const refreshBtn = document.getElementById('btn-refresh-approvals');
  if (refreshBtn) refreshBtn.addEventListener('click', loadApprovals);
  if (!tbody) return;

  try {
    const res = await fetch(`${API_BASE}/approvals?status=PENDING`);
    if (!res.ok) throw new Error('Failed to load approvals');
    const approvals = await res.json();

    if (countBadge) {
      if (approvals && approvals.length > 0) {
        countBadge.textContent = approvals.length;
        countBadge.style.display = 'inline-block';
      } else {
        countBadge.style.display = 'none';
      }
    }

    if (!approvals || approvals.length === 0) {
      tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--text-muted);">No actions awaiting approval. System operating smoothly.</td></tr>`;
      return;
    }

    tbody.innerHTML = approvals.map(appr => {
      return `
        <tr>
          <td><code>${appr.id.slice(0, 8)}...</code></td>
          <td><code>${appr.task_id ? appr.task_id.slice(0, 8) : '-'}...</code></td>
          <td><strong style="color: var(--accent-cyan);">${appr.action_type}</strong></td>
          <td><span class="pill pill-failed">${appr.risk_level}</span></td>
          <td>${escapeHtml(appr.action_description)}</td>
          <td style="font-size: 0.75rem;">${formatDate(appr.created_at)}</td>
          <td>
            <button class="btn-success btn-sm" onclick="resolveApproval('${appr.id}', 'APPROVED')">Approve</button>
            <button class="btn-danger btn-sm" style="margin-left: 4px;" onclick="resolveApproval('${appr.id}', 'REJECTED')">Reject</button>
          </td>
        </tr>
      `;
    }).join('');
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="7" style="color: var(--accent-rose); text-align: center;">Error: ${err.message}</td></tr>`;
  }
}

async function resolveApproval(approvalId, decision) {
  try {
    const reason = prompt(`Enter resolution rationale for ${decision}:`, decision === 'APPROVED' ? 'Approved by analyst' : 'Rejected by analyst');
    if (reason === null) return;

    const res = await fetch(`${API_BASE}/approvals/${approvalId}/resolve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        status: decision,
        resolution_reason: reason,
        resolved_by: 'Analyst Dashboard UI',
      }),
    });

    if (res.ok) {
      alert(`Approval ${decision} successfully.`);
      loadApprovals();
      loadTasks();
    } else {
      throw new Error(await res.text());
    }
  } catch (e) {
    alert('Failed to resolve approval: ' + e.message);
  }
}

// ---------------------------------------------------------------------------
// Audit Log & Provenance
// ---------------------------------------------------------------------------
async function loadAudit() {
  const tbody = document.getElementById('audit-tbody');
  const refreshBtn = document.getElementById('btn-refresh-audit');
  if (refreshBtn) refreshBtn.addEventListener('click', loadAudit);
  if (!tbody) return;

  try {
    const res = await fetch(`${API_BASE}/audit?limit=25`);
    if (!res.ok) throw new Error('Failed to load audit events');
    const events = await res.json();

    if (!events || events.length === 0) {
      tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--text-muted);">No audit events recorded yet.</td></tr>`;
      return;
    }

    tbody.innerHTML = events.map(ev => {
      let preview = ev.details_json || '{}';
      try {
        const obj = JSON.parse(preview);
        preview = JSON.stringify(obj, null, 1).replace(/\n/g, ' ');
        if (preview.length > 80) preview = preview.slice(0, 77) + '...';
      } catch (e) {}

      return `
        <tr>
          <td style="font-size: 0.75rem; font-family: var(--font-mono);">${formatDate(ev.timestamp)}</td>
          <td><span class="pill pill-info">${ev.event_type}</span></td>
          <td>${ev.entity_type || '-'}</td>
          <td><code style="font-size: 0.75rem;">${ev.entity_id ? ev.entity_id.slice(0, 10) : '-'}</code></td>
          <td><strong>${ev.actor}</strong></td>
          <td style="font-family: var(--font-mono); font-size: 0.75rem; color: var(--text-muted);">${escapeHtml(preview)}</td>
        </tr>
      `;
    }).join('');
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" style="color: var(--accent-rose); text-align: center;">Error: ${err.message}</td></tr>`;
  }
}

// ---------------------------------------------------------------------------
// Utility Helpers
// ---------------------------------------------------------------------------
function getStatusPill(status) {
  const s = (status || 'UNKNOWN').toUpperCase();
  if (s === 'COMPLETED') return '<span class="pill pill-completed">COMPLETED</span>';
  if (s === 'RUNNING') return '<span class="pill pill-running">RUNNING</span>';
  if (s === 'PENDING') return '<span class="pill pill-pending">PENDING</span>';
  if (s === 'FAILED') return '<span class="pill pill-failed">FAILED</span>';
  if (s === 'CANCELLED') return '<span class="pill pill-failed">CANCELLED</span>';
  return `<span class="pill pill-info">${s}</span>`;
}

function formatDate(isoStr) {
  if (!isoStr) return '-';
  try {
    const d = new Date(isoStr);
    return d.toISOString().replace('T', ' ').slice(0, 19);
  } catch (e) {
    return isoStr;
  }
}

function escapeHtml(text) {
  if (!text) return '';
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
