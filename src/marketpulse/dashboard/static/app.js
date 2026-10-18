/**
 * MarketPulse AI — Client Application Controller
 * Institutional Indian Financial Intelligence & Automation Runtime
 */

const API_BASE = window.MARKETPULSE_API_BASE || localStorage.getItem('marketpulse_api_base') || '/api/v1';

// State
let activeTaskId = null;
let pollTimer = null;

// DOM Initialization
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
    initHealthCheck();
  }, 10000);
});

// ---------------------------------------------------------------------------
// Toast Notification System (Institutional UX — replaces browser alert)
// ---------------------------------------------------------------------------
function showToast(title, message, type = 'info', durationMs = 4500) {
  const container = document.getElementById('toast-container');
  if (!container) {
    console.log(`[Toast ${type}] ${title}: ${message}`);
    return;
  }

  const icons = {
    success: '🟢',
    error: '🔴',
    warning: '🟡',
    info: '🔵',
  };

  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.innerHTML = `
    <div class="toast-icon">${icons[type] || '🔵'}</div>
    <div class="toast-content">
      <div class="toast-title">${escapeHtml(title)}</div>
      <div class="toast-body">${escapeHtml(message)}</div>
    </div>
    <button class="toast-close" title="Dismiss">&times;</button>
  `;

  const closeBtn = toast.querySelector('.toast-close');
  const dismiss = () => {
    toast.classList.add('toast-hiding');
    setTimeout(() => {
      if (toast.parentElement) toast.remove();
    }, 250);
  };

  closeBtn.addEventListener('click', dismiss);
  container.appendChild(toast);

  if (durationMs > 0) {
    setTimeout(dismiss, durationMs);
  }
}

// ---------------------------------------------------------------------------
// Custom Confirmation Modal (Replaces browser confirm)
// ---------------------------------------------------------------------------
function showConfirmModal({ title, message, confirmText = 'Confirm', cancelText = 'Cancel', isDestructive = false }) {
  return new Promise((resolve) => {
    const modal = document.getElementById('confirm-modal');
    const titleEl = document.getElementById('confirm-modal-title');
    const bodyEl = document.getElementById('confirm-modal-body');
    const proceedBtn = document.getElementById('btn-confirm-proceed');
    const cancelBtn = document.getElementById('btn-confirm-cancel');
    const closeXBtn = document.getElementById('btn-confirm-cancel-x');

    if (!modal || !proceedBtn || !cancelBtn) {
      resolve(true);
      return;
    }

    titleEl.textContent = title || 'Confirm Action';
    bodyEl.innerHTML = escapeHtml(message || 'Are you sure you want to proceed?');
    proceedBtn.textContent = confirmText;
    proceedBtn.className = isDestructive ? 'btn-danger' : 'btn-primary';
    cancelBtn.textContent = cancelText;

    const cleanup = () => {
      modal.classList.remove('active');
      proceedBtn.removeEventListener('click', onProceed);
      cancelBtn.removeEventListener('click', onCancel);
      if (closeXBtn) closeXBtn.removeEventListener('click', onCancel);
    };

    const onProceed = () => {
      cleanup();
      resolve(true);
    };

    const onCancel = () => {
      cleanup();
      resolve(false);
    };

    proceedBtn.addEventListener('click', onProceed);
    cancelBtn.addEventListener('click', onCancel);
    if (closeXBtn) closeXBtn.addEventListener('click', onCancel);

    modal.classList.add('active');
  });
}

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
// Health Probes & System Diagnostics (Truthful & Actionable)
// ---------------------------------------------------------------------------
async function initHealthCheck() {
  const modeText = document.getElementById('header-mode-text');
  const n8nText = document.getElementById('header-n8n-text');
  const statDb = document.getElementById('stat-db-status');
  const statN8n = document.getElementById('stat-n8n-status');
  const diagnosticsBox = document.getElementById('diagnostics-guidance-content');
  const diagnosticsBadge = document.getElementById('diagnostics-last-checked');

  try {
    const res = await fetch(`${API_BASE}/health`, { cache: 'no-store' });
    if (!res.ok) throw new Error(`Health probe returned HTTP ${res.status}`);
    const data = await res.json();

    const isCloud = (data.mode || '').toLowerCase() === 'cloud';
    if (modeText) {
      modeText.textContent = isCloud ? 'CLOUD RUNTIME' : 'DESKTOP MODE';
      modeText.title = isCloud
        ? 'Operating in Cloud Serverless Mode (Desktop Win32 automation restricted)'
        : 'Operating in Local Desktop Mode (Desktop Win32/Playwright automation active)';
    }

    if (n8nText) {
      if (data.n8n_status === 'CONNECTED') {
        const lat = data.n8n_latency_ms ? ` (${data.n8n_latency_ms.toFixed(0)}ms)` : '';
        n8nText.textContent = `n8n: CONNECTED${lat}`;
        n8nText.style.color = 'var(--accent-emerald)';
      } else if (data.n8n_status === 'UNAUTHORIZED') {
        n8nText.textContent = 'n8n: UNAUTHORIZED';
        n8nText.style.color = 'var(--accent-amber)';
      } else if (data.n8n_status === 'MISCONFIGURED') {
        n8nText.textContent = 'n8n: MISCONFIGURED';
        n8nText.style.color = 'var(--accent-amber)';
      } else {
        n8nText.textContent = 'n8n: DISCONNECTED';
        n8nText.style.color = 'var(--accent-rose)';
      }
    }

    if (statDb) {
      statDb.textContent = data.database_connected ? 'CONNECTED' : 'DISCONNECTED';
      statDb.style.color = data.database_connected ? 'var(--accent-emerald)' : 'var(--accent-rose)';
    }

    if (statN8n) {
      const isOnline = data.n8n_status === 'CONNECTED';
      statN8n.textContent = isOnline ? 'ONLINE' : (data.n8n_status || 'DISCONNECTED');
      statN8n.style.color = isOnline
        ? 'var(--accent-emerald)'
        : (data.n8n_status === 'UNAUTHORIZED' ? 'var(--accent-amber)' : 'var(--accent-rose)');

      const sub = statN8n.parentElement ? statN8n.parentElement.querySelector('.stat-sub') : null;
      if (sub) {
        if (isOnline) {
          sub.textContent = 'Webhooks & REST Active';
        } else if (data.n8n_message) {
          sub.textContent = data.n8n_message.length > 40 ? data.n8n_message.slice(0, 37) + '...' : data.n8n_message;
          sub.title = data.n8n_message;
        } else {
          sub.textContent = 'Instance Unreachable';
        }
      }
    }

    // Render Actionable System Diagnostics Guidance in Tab 7
    if (diagnosticsBox) {
      const nowStr = new Date().toLocaleTimeString();
      if (diagnosticsBadge) diagnosticsBadge.textContent = `Probed ${nowStr}`;

      let guidanceHtml = `
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 1rem; margin-bottom: 1rem;">
          <div style="background: rgba(255,255,255,0.02); border: 1px solid var(--border-subtle); padding: 0.85rem; border-radius: var(--radius-md);">
            <div style="font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase;">Runtime Execution Mode</div>
            <div style="font-weight: 700; color: ${isCloud ? 'var(--accent-cyan)' : 'var(--accent-emerald)'}; font-size: 1rem;">
              ${isCloud ? 'Cloud Serverless (Vercel)' : 'Desktop Local Workstation'}
            </div>
            <div style="font-size: 0.8rem; color: var(--text-secondary); margin-top: 0.25rem;">
              ${isCloud ? 'Desktop OS Win32 automation restricted. Financial research, market briefs, watchlists & webhooks fully active.' : 'Full local Playwright & Win32 desktop automation available.'}
            </div>
          </div>

          <div style="background: rgba(255,255,255,0.02); border: 1px solid var(--border-subtle); padding: 0.85rem; border-radius: var(--radius-md);">
            <div style="font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase;">n8n Workflow Engine</div>
            <div style="font-weight: 700; color: ${data.n8n_status === 'CONNECTED' ? 'var(--accent-emerald)' : 'var(--accent-rose)'}; font-size: 1rem;">
              ${data.n8n_status || 'DISCONNECTED'}
            </div>
            <div style="font-size: 0.8rem; color: var(--text-secondary); margin-top: 0.25rem;">
              ${data.n8n_status === 'CONNECTED' ? 'Connected and polling workflows' : (data.n8n_message || 'Local container offline')}
            </div>
          </div>

          <div style="background: rgba(255,255,255,0.02); border: 1px solid var(--border-subtle); padding: 0.85rem; border-radius: var(--radius-md);">
            <div style="font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase;">Financial Guardrails & Safety</div>
            <div style="font-weight: 700; color: var(--accent-emerald); font-size: 1rem;">
              PERMANENTLY ENFORCED
            </div>
            <div style="font-size: 0.8rem; color: var(--text-secondary); margin-top: 0.25rem;">
              Brokerage order placement and fund transfers blocked with ProhibitedActionError.
            </div>
          </div>
        </div>
      `;

      if (data.n8n_status !== 'CONNECTED') {
        guidanceHtml += `
          <div class="remediation-box">
            <strong>⚠️ Actionable Remediation: n8n Workflow Engine is Offline</strong>
            To enable production n8n workflows (MP-01 through MP-05), launch the local container:
            <br>
            <code>docker compose -f workflows/n8n/docker-compose.yml up -d</code>
            <br>
            <span style="display:inline-block; margin-top:0.35rem; color:var(--text-muted);">
              Note: You can still execute financial research tasks, generate market briefs, and evaluate watchlists directly using the dashboard or REST API.
            </span>
          </div>
        `;
      }

      diagnosticsBox.innerHTML = guidanceHtml;
    }

  } catch (err) {
    console.warn('Health probe query warning:', err.message);
    if (n8nText) {
      n8nText.textContent = 'API: OFFLINE';
      n8nText.style.color = 'var(--accent-rose)';
    }
    if (statDb) {
      statDb.textContent = 'UNREACHABLE';
      statDb.style.color = 'var(--accent-rose)';
    }
  }
}

// ---------------------------------------------------------------------------
// Emergency Stop (Non-blocking confirmation modal)
// ---------------------------------------------------------------------------
function initEmergencyStop() {
  const btn = document.getElementById('btn-emergency-stop');
  if (!btn) return;

  btn.addEventListener('click', async () => {
    const confirmed = await showConfirmModal({
      title: 'Global Emergency Stop',
      message: 'Are you sure you want to trigger the global EMERGENCY STOP?\nAll running automation tasks will immediately halt and all pending steps will be rejected.',
      confirmText: 'HALT ALL TASKS',
      cancelText: 'Resume Operation',
      isDestructive: true,
    });

    if (!confirmed) return;

    try {
      const res = await fetch(`${API_BASE}/webhook/notify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          event_type: 'EMERGENCY_STOP_TRIGGERED',
          message: 'Operator pressed UI Emergency Stop button',
          details: { origin: 'Web Dashboard' },
        }),
      });

      if (!res.ok) throw new Error('Server returned HTTP ' + res.status);
      showToast('Emergency Stop Active', 'Global halt signal dispatched. Active execution steps have been terminated.', 'warning', 6000);
      loadTasks();
    } catch (err) {
      showToast('Emergency Stop Failed', 'Error triggering emergency stop: ' + err.message, 'error', 6000);
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
          auto_approve: autoApprove,
        };

        const res = await fetch(`${API_BASE}/webhook/task`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });

        if (!res.ok) throw new Error('Task creation failed: ' + (await res.text()));
        const data = await res.json();

        activeTaskId = data.task_id;
        showToast('Task Launched', `Task queued successfully [ID: ${activeTaskId.slice(0, 8)}...]`, 'success', 3500);
        startActiveTaskPolling(activeTaskId, prompt);
        loadTasks();
        form.reset();
      } catch (err) {
        showToast('Task Submission Error', err.message, 'error', 5000);
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
      const res = await fetch(`${API_BASE}/webhook/task/${taskId}`);
      if (!res.ok) return;
      const data = await res.json();

      const rawStatus = data.status || (data.task && data.task.status) || 'PENDING';
      const status = String(rawStatus).toUpperCase();
      const currentStep = data.current_step !== undefined ? data.current_step : (data.task ? data.task.current_step : 0);
      const stepLimit = data.step_limit !== undefined ? data.step_limit : (data.task ? data.task.step_limit : 25);
      const summary = data.result_summary || (data.task && data.task.result_summary);
      const errorMsg = data.error_message || (data.task && data.task.error_message);
      const artifacts = data.artifacts || [];

      const progressBar = document.getElementById('active-task-progress-bar');
      const statusText = document.getElementById('active-task-status-text');

      if (statusText) {
        statusText.textContent = `Status: ${status} (Step: ${currentStep}/${stepLimit})`;
      }

      if (progressBar) {
        const pct = Math.min(100, Math.max(10, (currentStep / stepLimit) * 100));
        progressBar.style.width = `${pct}%`;
      }

      if (['COMPLETED', 'FAILED', 'CANCELLED', 'AWAITING_APPROVAL'].includes(status)) {
        if (['COMPLETED', 'FAILED', 'CANCELLED'].includes(status)) {
          clearInterval(pollTimer);
          pollTimer = null;
        }

        if (status === 'COMPLETED') {
          pill.className = 'pill pill-completed';
          pill.textContent = 'COMPLETED';

          let artifactsHtml = '';
          if (artifacts.length > 0) {
            artifactsHtml = `
              <div style="margin-top: 0.5rem; font-size: 0.8rem; color: var(--text-muted);">
                <strong>Artifacts Generated:</strong>
                <ul style="margin: 0.25rem 0 0 1.2rem; padding: 0;">
                  ${artifacts.map(a => `<li><code>${escapeHtml(a.name)}</code> (${a.size_bytes || 0} bytes)</li>`).join('')}
                </ul>
              </div>
            `;
          }

          cardBody.innerHTML += `
            <div style="margin-top: 1rem; padding: 0.75rem; background: rgba(0,255,136,0.06); border-left: 3px solid var(--accent-emerald); border-radius: 4px; font-size: 0.85rem;">
              <strong style="color: var(--accent-emerald);">Execution Result:</strong> ${escapeHtml(summary || 'Pipeline completed successfully.')}
              ${artifactsHtml}
            </div>
          `;
          showToast('Task Completed', summary || 'Execution finished successfully', 'success', 4000);
        } else if (status === 'FAILED') {
          pill.className = 'pill pill-failed';
          pill.textContent = 'FAILED';
          cardBody.innerHTML += `
            <div style="margin-top: 1rem; padding: 0.75rem; background: rgba(255,77,106,0.08); border-left: 3px solid var(--accent-rose); border-radius: 4px; font-size: 0.85rem; color: var(--accent-rose);">
              <strong>Execution Error:</strong> ${escapeHtml(errorMsg || 'Task failed during execution.')}
            </div>
          `;
          showToast('Task Failed', errorMsg || 'Task encountered an error during execution', 'error', 5000);
        } else if (status === 'AWAITING_APPROVAL') {
          pill.className = 'pill pill-pending';
          pill.textContent = 'APPROVAL REQUIRED';
          if (!cardBody.querySelector('.approval-notice')) {
            cardBody.innerHTML += `
              <div class="approval-notice" style="margin-top: 1rem; padding: 0.75rem; background: rgba(255,184,0,0.08); border-left: 3px solid var(--accent-amber); border-radius: 4px; font-size: 0.85rem;">
                <strong>Gatekeeper:</strong> High-risk step requires human approval. Go to the <button class="btn-sm btn-secondary" onclick="document.getElementById('nav-approvals').click()">Approvals Tab</button> to review.
              </div>
            `;
            showToast('Approval Required', 'High-risk task step requires human authorization.', 'warning', 6000);
          }
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
  const confirmed = await showConfirmModal({
    title: 'Cancel Active Task',
    message: `Are you sure you want to terminate task ${taskId}? Any in-progress step will be halted.`,
    confirmText: 'Cancel Task',
    cancelText: 'Keep Running',
    isDestructive: true,
  });

  if (!confirmed) return;

  try {
    const res = await fetch(`${API_BASE}/tasks/${taskId}/cancel`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason: 'Cancelled from Dashboard UI' }),
    });
    if (res.ok) {
      showToast('Task Cancelled', 'Task has been cancelled successfully.', 'info', 3500);
      if (pollTimer) clearInterval(pollTimer);
      loadTasks();
    } else {
      throw new Error(await res.text());
    }
  } catch (err) {
    showToast('Cancellation Failed', err.message, 'error', 4500);
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
      tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--text-muted);">No automation tasks recorded yet.</td></tr>`;
      return;
    }

    tbody.innerHTML = tasks.map(t => {
      return `
        <tr>
          <td><code>${t.id.slice(0, 8)}...</code></td>
          <td><span class="pill pill-info">${t.task_type || 'GENERAL'}</span></td>
          <td>${getStatusPill(t.status)}</td>
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
      const ticker = r.ticker || r.company_symbol || 'INDIAN_MARKET';
      const sector = r.sector || r.sector_name || 'Broad Market';
      const title = r.title || r.query || `${ticker} Research Dossier`;
      const verifiedCount = (r.evidence_references && r.evidence_references.length) || (r.verified_facts && r.verified_facts.length) || 0;
      const genTime = r.generated_at || r.created_at;

      return `
        <tr>
          <td><code>${r.id ? r.id.slice(0, 8) : '-'}...</code></td>
          <td><strong style="color: var(--accent-cyan);">${ticker}</strong></td>
          <td>${sector}</td>
          <td style="font-weight: 600; color: var(--text-primary); max-width: 280px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
            ${escapeHtml(title)}
          </td>
          <td><span class="pill pill-completed">${verifiedCount} Facts Verified</span></td>
          <td style="font-size: 0.75rem;">${formatDate(genTime)}</td>
          <td>
            <button class="btn-secondary btn-sm" onclick="openReportModal('${r.id}')">View</button>
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

    const ticker = rep.ticker || rep.company_symbol || 'GENERAL';
    const sector = rep.sector || rep.sector_name || 'Broad Market';
    const reportTitle = rep.title || rep.query || `${ticker} Institutional Research Report`;

    title.textContent = reportTitle;

    const bull = rep.bull_scenario || (rep.scenarios && rep.scenarios.bull_case);
    const base = rep.base_scenario || (rep.scenarios && rep.scenarios.base_case);
    const bear = rep.bear_scenario || (rep.scenarios && rep.scenarios.bear_case);

    const verifiedFacts = rep.verified_facts || [];
    const evidenceRefs = rep.evidence_references || [];

    body.innerHTML = `
      <div style="margin-bottom: 1.25rem;">
        <span class="pill pill-info">${ticker}</span>
        <span class="pill pill-completed" style="margin-left: 0.5rem;">${sector}</span>
        <span style="font-size: 0.8rem; color: var(--text-muted); margin-left: 0.75rem;">
          Generated: ${formatDate(rep.generated_at)}
        </span>
      </div>

      <div style="margin-bottom: 1.5rem;">
        <h4 style="color: var(--text-secondary); text-transform: uppercase; font-size: 0.8rem; margin-bottom: 0.5rem; letter-spacing: 0.05em;">
          Executive Summary
        </h4>
        <div style="background: rgba(255,255,255,0.03); padding: 1rem; border-radius: var(--radius-md); font-size: 0.9rem; line-height: 1.6; white-space: pre-wrap;">
          ${escapeHtml(rep.executive_summary || 'No summary available.')}
        </div>
      </div>

      ${(bull || base || bear) ? `
        <div style="margin-bottom: 1.5rem;">
          <h4 style="color: var(--text-secondary); text-transform: uppercase; font-size: 0.8rem; margin-bottom: 0.5rem; letter-spacing: 0.05em;">
            Scenario Analysis
          </h4>
          <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 0.75rem; font-size: 0.85rem;">
            ${bull ? `
              <div style="background: rgba(0,255,136,0.05); border: 1px solid rgba(0,255,136,0.2); padding: 0.75rem; border-radius: var(--radius-md);">
                <strong style="color: var(--accent-emerald);">Bull Case:</strong><br>${escapeHtml(bull)}
              </div>
            ` : ''}
            ${base ? `
              <div style="background: rgba(0,240,255,0.05); border: 1px solid rgba(0,240,255,0.2); padding: 0.75rem; border-radius: var(--radius-md);">
                <strong style="color: var(--accent-cyan);">Base Case:</strong><br>${escapeHtml(base)}
              </div>
            ` : ''}
            ${bear ? `
              <div style="background: rgba(255,51,102,0.05); border: 1px solid rgba(255,51,102,0.2); padding: 0.75rem; border-radius: var(--radius-md);">
                <strong style="color: var(--accent-rose);">Bear Case:</strong><br>${escapeHtml(bear)}
              </div>
            ` : ''}
          </div>
        </div>
      ` : ''}

      <div style="margin-bottom: 1.5rem;">
        <h4 style="color: var(--text-secondary); text-transform: uppercase; font-size: 0.8rem; margin-bottom: 0.5rem; letter-spacing: 0.05em;">
          Verified Primary Facts & Evidence Citations
        </h4>
        <div class="data-table-container">
          <table class="data-table">
            <thead><tr><th>Verified Fact Statement</th><th>Source Citation / URL</th><th>Confidence</th></tr></thead>
            <tbody>
              ${evidenceRefs.length > 0 ? evidenceRefs.map(ev => `
                <tr>
                  <td>${escapeHtml(ev.fact_statement || ev.fact || '-')}</td>
                  <td>${ev.source_url ? `<a href="${ev.source_url}" target="_blank" rel="noopener noreferrer" style="color: var(--accent-cyan); text-decoration: none;">Link ↗</a>` : '<span style="color:var(--text-muted);">-</span>'}</td>
                  <td><span class="pill pill-info">${ev.confidence_score ? (ev.confidence_score * 100).toFixed(0) + '%' : '100%'}</span></td>
                </tr>
              `).join('') : (verifiedFacts.length > 0 ? verifiedFacts.map(fact => `
                <tr>
                  <td>${escapeHtml(fact)}</td>
                  <td><span style="color:var(--text-muted);">Verified Primary Record</span></td>
                  <td><span class="pill pill-info">100%</span></td>
                </tr>
              `).join('') : `<tr><td colspan="3" style="color: var(--text-muted); text-align: center;">No individual evidence records linked.</td></tr>`)}
            </tbody>
          </table>
        </div>
      </div>
    `;
  } catch (err) {
    body.innerHTML = `<p style="color: var(--accent-rose);">Error loading report: ${err.message}</p>`;
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
      if (!res.ok) throw new Error('Brief generation failed: ' + (await res.text()));
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
      showToast('Market Brief Generated', 'Verified market session brief compiled successfully.', 'success', 3500);
    } catch (err) {
      showToast('Brief Generation Error', err.message, 'error', 4500);
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
  const container = document.getElementById('watchlists-container');
  if (!container) return;

  try {
    const res = await fetch(`${API_BASE}/watchlists`);
    if (!res.ok) throw new Error('Failed to load watchlists');
    const watchlists = await res.json();

    if (!watchlists || watchlists.length === 0) {
      container.innerHTML = `<p style="color: var(--text-muted); font-size: 0.9rem;">No active watchlists found.</p>`;
      return;
    }

    container.innerHTML = watchlists.map(w => {
      const items = w.items || [];
      return `
        <div style="background: rgba(255,255,255,0.02); border: 1px solid var(--border-subtle); border-radius: var(--radius-md); padding: 1rem; margin-bottom: 0.75rem;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
            <strong style="color: var(--text-primary);">${escapeHtml(w.name)}</strong>
            <span class="pill pill-info">${items.length} Tracked</span>
          </div>
          <div style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 0.5rem;">
            ${escapeHtml(w.description || 'Watchlist criteria active')}
          </div>
          <div style="display: flex; flex-wrap: wrap; gap: 0.4rem;">
            ${items.map(it => `
              <span style="background: rgba(0,240,255,0.08); color: var(--accent-cyan); font-family: var(--font-mono); font-size: 0.75rem; padding: 0.2rem 0.5rem; border-radius: 4px;">
                ${it.company_symbol || it.symbol}
              </span>
            `).join('')}
          </div>
        </div>
      `;
    }).join('');
  } catch (err) {
    container.innerHTML = `<p style="color: var(--accent-rose); font-size: 0.85rem;">Error loading watchlists: ${err.message}</p>`;
  }
}

async function loadAlerts() {
  const tbody = document.getElementById('alerts-tbody');
  const evalBtn = document.getElementById('btn-evaluate-alerts');

  if (evalBtn && !evalBtn.dataset.bound) {
    evalBtn.dataset.bound = 'true';
    evalBtn.addEventListener('click', async () => {
      evalBtn.disabled = true;
      evalBtn.textContent = 'Evaluating...';
      try {
        const res = await fetch(`${API_BASE}/alerts/evaluate`, { method: 'POST' });
        if (!res.ok) throw new Error('Evaluation failed');
        const resData = await res.json();
        showToast('Alert Evaluation Complete', `Triggered ${resData.alerts_triggered_count || 0} alert conditions`, 'success', 3500);
        loadAlerts();
      } catch (e) {
        showToast('Alert Evaluation Failed', e.message, 'error', 4500);
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
      return `
        <tr>
          <td style="font-size: 0.75rem;">${formatDate(a.triggered_at)}</td>
          <td><strong style="color: var(--accent-cyan);">${a.company_symbol || '-'}</strong></td>
          <td><span class="pill ${a.severity === 'HIGH' ? 'pill-failed' : 'pill-pending'}">${a.severity || 'MEDIUM'}</span></td>
          <td style="font-size: 0.85rem;">${escapeHtml(a.headline || a.message)}</td>
          <td style="font-size: 0.8rem; color: var(--text-muted);">${escapeHtml(a.rule_name || 'Watchlist Filter')}</td>
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
  const refreshBtn = document.getElementById('btn-refresh-schedules');
  if (refreshBtn) refreshBtn.addEventListener('click', loadSchedules);
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
      return `
        <tr>
          <td><strong style="color: var(--text-primary);">${escapeHtml(s.name)}</strong></td>
          <td><code style="color: var(--accent-cyan);">${s.cron_expression}</code></td>
          <td><span class="pill pill-info">${s.job_type}</span></td>
          <td><span class="pill ${s.is_active ? 'pill-completed' : 'pill-failed'}">${s.is_active ? 'ACTIVE' : 'PAUSED'}</span></td>
          <td><span class="pill ${s.is_dry_run ? 'pill-pending' : 'pill-completed'}">${s.is_dry_run ? 'SIMULATION' : 'LIVE'}</span></td>
          <td style="font-size: 0.75rem;">${formatDate(s.last_run_at)}</td>
          <td style="font-size: 0.75rem;">${formatDate(s.next_run_at)}</td>
          <td>
            <button class="btn-primary btn-sm" onclick="triggerSchedule('${s.id}')">Run Now</button>
            <button class="btn-secondary btn-sm" style="margin-left: 4px;" onclick="toggleSchedule('${s.id}', ${!s.is_active})">
              ${s.is_active ? 'Pause' : 'Resume'}
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
    showToast(
      'Schedule Dispatched',
      `Schedule '${data.name}' dispatched [Mode: ${data.is_dry_run ? 'SIMULATION' : 'LIVE'}]. Status: ${data.status}`,
      'success',
      4500
    );
    loadTasks();
  } catch (e) {
    showToast('Trigger Failed', e.message, 'error', 4500);
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
      showToast('Schedule Updated', `Schedule status set to ${newState ? 'ACTIVE' : 'PAUSED'}`, 'info', 3000);
      loadSchedules();
    } else {
      throw new Error(await res.text());
    }
  } catch (e) {
    showToast('Update Failed', e.message, 'error', 4500);
  }
}

// ---------------------------------------------------------------------------
// Human Approvals Gate (Non-blocking institutional workflow)
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
  const isDestructive = decision === 'REJECTED';
  const confirmed = await showConfirmModal({
    title: `${decision === 'APPROVED' ? 'Approve' : 'Reject'} Action Step`,
    message: `Are you sure you want to mark approval request ${approvalId.slice(0, 8)} as ${decision}?`,
    confirmText: decision,
    cancelText: 'Cancel',
    isDestructive: isDestructive,
  });

  if (!confirmed) return;

  try {
    const res = await fetch(`${API_BASE}/approvals/${approvalId}/resolve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        status: decision,
        resolution_reason: `Resolved via Analyst Dashboard UI [${decision}]`,
        resolved_by: 'Analyst Dashboard UI',
      }),
    });

    if (res.ok) {
      showToast('Approval Resolved', `Step ${approvalId.slice(0, 8)} marked as ${decision}.`, 'success', 3500);
      loadApprovals();
      loadTasks();
    } else {
      throw new Error(await res.text());
    }
  } catch (e) {
    showToast('Resolution Failed', e.message, 'error', 4500);
  }
}

// ---------------------------------------------------------------------------
// Security & Provenance Audit Trail
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
  if (s === 'AWAITING_APPROVAL') return '<span class="pill pill-pending">AWAITING APPROVAL</span>';
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
