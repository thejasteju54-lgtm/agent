/**
 * Personal AI Automation Dashboard - Core Client Application
 */

const API_BASE = window.location.origin;

// State
let allTasks = [];
let allArtifacts = [];
let allClipboard = [];
let activeTab = 'tab-tasks';

// DOM Elements
document.addEventListener('DOMContentLoaded', () => {
  initNavigation();
  initTaskRunner();
  initModals();
  initClipboardActions();
  initDesktopActions();

  // Initial Data Load
  refreshAllData();

  // Auto-refresh interval (5 seconds)
  setInterval(() => {
    if (activeTab === 'tab-tasks') loadTasks();
    if (activeTab === 'tab-approvals') loadApprovals();
    if (activeTab === 'tab-clipboard') loadClipboard();
    if (activeTab === 'tab-desktop') loadDesktopInfo();
  }, 5000);
});

/* ==========================================================================
   Navigation
   ========================================================================== */

function initNavigation() {
  const navButtons = document.querySelectorAll('.nav-item');
  const tabPanes = document.querySelectorAll('.tab-pane');
  const pageTitle = document.getElementById('page-title');
  const pageSubtitle = document.getElementById('page-subtitle');

  const titles = {
    'tab-tasks': { title: 'Tasks & Runner', sub: 'Natural language task execution, live planning, and step history' },
    'tab-approvals': { title: 'Human Approvals', sub: 'Review and approve pending high-risk automation actions' },
    'tab-artifacts': { title: 'Artifacts Gallery', sub: 'Inspect generated screenshots, extracted texts, and output files' },
    'tab-clipboard': { title: 'Clipboard Memory', sub: 'Search, classify, and restore Windows clipboard history' },
    'tab-desktop': { title: 'Desktop & Screen', sub: 'Windows display state, window management, and screen capture' },
    'tab-settings': { title: 'Logs & Settings', sub: 'Runtime configuration and application log stream' },
  };

  navButtons.forEach(btn => {
    btn.addEventListener('click', () => {
      const target = btn.dataset.tab;
      activeTab = target;

      navButtons.forEach(b => b.classList.remove('active'));
      tabPanes.forEach(p => p.classList.remove('active'));

      btn.classList.add('active');
      document.getElementById(target).classList.add('active');

      if (titles[target]) {
        pageTitle.textContent = titles[target].title;
        pageSubtitle.textContent = titles[target].sub;
      }

      // Tab specific refresh
      if (target === 'tab-artifacts') loadArtifacts();
      if (target === 'tab-clipboard') loadClipboard();
      if (target === 'tab-desktop') loadDesktopInfo();
      if (target === 'tab-settings') { loadSettings(); loadLogs(); }
    });
  });

  document.getElementById('btn-refresh-all')?.addEventListener('click', () => {
    refreshAllData();
    showToast('Dashboard refreshed');
  });
}

function refreshAllData() {
  loadTasks();
  loadApprovals();
  loadArtifacts();
  loadDesktopInfo();
}

/* ==========================================================================
   Task Runner & History
   ========================================================================== */

function initTaskRunner() {
  const form = document.getElementById('task-runner-form');
  const input = document.getElementById('task-prompt-input');
  const autoApproveCheck = document.getElementById('check-auto-approve');
  const quickBtns = document.querySelectorAll('.btn-chip');

  quickBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      input.value = btn.dataset.prompt;
      input.focus();
    });
  });

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const prompt = input.value.trim();
    if (!prompt) return;

    const autoApprove = autoApproveCheck.checked;
    await executeTask(prompt, autoApprove);
  });

  // Task filter change
  document.getElementById('filter-task-status')?.addEventListener('change', (e) => {
    renderTasksTable(e.target.value);
  });
}

async function executeTask(prompt, autoApprove) {
  const runBtn = document.getElementById('btn-run-task');
  const progressCard = document.getElementById('task-progress-card');
  const progressFill = document.getElementById('live-progress-fill');
  const statusBadge = document.getElementById('live-task-status');
  const stepsContainer = document.getElementById('live-steps-container');

  runBtn.disabled = true;
  runBtn.innerHTML = '<span>Running...</span>';
  progressCard.classList.remove('hidden');
  progressFill.style.width = '30%';
  statusBadge.textContent = 'EXECUTING';
  statusBadge.className = 'badge badge-running';
  stepsContainer.innerHTML = `<div class="live-step-item">Planning execution steps for "${escapeHtml(prompt)}"...</div>`;

  try {
    const res = await fetch('/api/tasks/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt, auto_approve: autoApprove }),
    });

    const data = await res.json();
    progressFill.style.width = '100%';

    if (res.ok) {
      statusBadge.textContent = data.status || 'COMPLETED';
      statusBadge.className = `badge badge-${(data.status || 'completed').toLowerCase()}`;
      
      const completedSteps = data.report?.completed_steps || 1;
      const totalSteps = data.report?.total_steps || 1;
      stepsContainer.innerHTML = `
        <div class="live-step-item">✓ Execution Finished: ${escapeHtml(data.summary || 'Task completed')}</div>
        <div class="live-step-item text-muted">Steps: ${completedSteps}/${totalSteps} verified. Task ID: ${data.task_id}</div>
      `;
      showToast('Task executed successfully!');
    } else {
      statusBadge.textContent = 'FAILED';
      statusBadge.className = 'badge badge-failed';
      stepsContainer.innerHTML = `<div class="live-step-item text-danger">✕ Error: ${escapeHtml(data.error || 'Execution failed')}</div>`;
      showToast(data.error || 'Task execution failed', 'error');
    }

    // Refresh history and artifacts
    loadTasks();
    loadArtifacts();
  } catch (err) {
    statusBadge.textContent = 'ERROR';
    statusBadge.className = 'badge badge-failed';
    stepsContainer.innerHTML = `<div class="live-step-item text-danger">Network Error: ${escapeHtml(err.message)}</div>`;
  } finally {
    runBtn.disabled = false;
    runBtn.innerHTML = '<span>Run Task</span><span class="btn-arrow">→</span>';
  }
}

async function loadTasks() {
  try {
    const res = await fetch('/api/tasks');
    if (!res.ok) return;
    allTasks = await res.json();

    const runningCount = allTasks.filter(t => t.status === 'RUNNING').length;
    document.getElementById('badge-running-tasks').textContent = runningCount;

    const filter = document.getElementById('filter-task-status')?.value || '';
    renderTasksTable(filter);
  } catch (e) {
    console.error('Failed to load tasks', e);
  }
}

function renderTasksTable(filterStatus = '') {
  const tbody = document.getElementById('tasks-table-body');
  if (!tbody) return;

  const filtered = filterStatus 
    ? allTasks.filter(t => t.status === filterStatus)
    : allTasks;

  if (filtered.length === 0) {
    tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted">No tasks found.</td></tr>';
    return;
  }

  tbody.innerHTML = filtered.map(t => {
    const statusClass = `badge badge-${t.status.toLowerCase()}`;
    const dateStr = t.created_at ? t.created_at.replace('T', ' ').substring(0, 19) : '-';
    const summary = t.result_summary || (t.error_message ? `Error: ${t.error_message}` : '-');

    return `
      <tr>
        <td><span class="${statusClass}">${t.status}</span></td>
        <td style="font-weight: 500; color: #fff;">${escapeHtml(t.prompt)}</td>
        <td style="font-family: var(--font-mono); font-size: 11px;">${dateStr}</td>
        <td>${t.plan_json ? JSON.parse(t.plan_json).steps?.length || 1 : 1}</td>
        <td style="max-width: 280px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${escapeHtml(summary)}</td>
        <td>
          <button class="btn btn-secondary btn-sm" onclick="showTaskDetails('${t.id}')">Inspect</button>
        </td>
      </tr>
    `;
  }).join('');
}

window.showTaskDetails = async function(taskId) {
  try {
    const res = await fetch(`/api/tasks/${taskId}`);
    if (!res.ok) return;
    const data = await res.json();

    const modal = document.getElementById('task-modal');
    const title = document.getElementById('modal-task-title');
    const body = document.getElementById('modal-task-body');

    title.textContent = `Task: ${data.task.prompt}`;

    const plan = data.task.plan_json ? JSON.parse(data.task.plan_json) : null;
    const stepsHtml = (data.steps || []).map((s, idx) => `
      <div style="background: rgba(255,255,255,0.03); border: 1px solid var(--border-subtle); border-radius: var(--radius-md); padding: 12px; margin-bottom: 8px;">
        <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
          <strong style="color: #fff;">Step ${idx + 1}: ${s.tool_name}</strong>
          <span class="badge badge-${s.status.toLowerCase()}">${s.status}</span>
        </div>
        <div style="font-size: 12px; color: var(--text-muted); font-family: var(--font-mono); margin-bottom: 4px;">Input: ${escapeHtml(s.input_params || '{}')}</div>
        ${s.output_result ? `<div style="font-size: 12px; color: var(--accent-cyan); font-family: var(--font-mono);">Output: ${escapeHtml(s.output_result.substring(0, 160))}...</div>` : ''}
      </div>
    `).join('');

    body.innerHTML = `
      <div style="margin-bottom: 16px;">
        <div class="metric-row"><span class="metric-name">Task ID:</span><span class="metric-val">${data.task.id}</span></div>
        <div class="metric-row"><span class="metric-name">Status:</span><span class="metric-val">${data.task.status}</span></div>
        <div class="metric-row"><span class="metric-name">Created:</span><span class="metric-val">${data.task.created_at}</span></div>
        <div class="metric-row"><span class="metric-name">Summary:</span><span class="metric-val">${escapeHtml(data.task.result_summary || '-')}</span></div>
      </div>
      <h4 style="margin-bottom: 10px; color: #fff;">Executed Steps (${data.steps?.length || 0})</h4>
      ${stepsHtml || '<div class="text-muted">No step details available.</div>'}
    `;

    modal.classList.remove('hidden');
  } catch (err) {
    showToast('Failed to load task details', 'error');
  }
};

/* ==========================================================================
   Human Approvals
   ========================================================================== */

async function loadApprovals() {
  try {
    const res = await fetch('/api/approvals');
    if (!res.ok) return;
    const approvals = await res.json();

    const badge = document.getElementById('badge-pending-approvals');
    badge.textContent = approvals.length;

    const container = document.getElementById('approvals-container');
    if (approvals.length === 0) {
      container.innerHTML = '<div class="empty-state">No pending approvals. All actions are clear.</div>';
      return;
    }

    container.innerHTML = approvals.map(app => `
      <div style="background: rgba(245, 158, 11, 0.05); border: 1px solid rgba(245, 158, 11, 0.3); border-radius: var(--radius-lg); padding: 18px; margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center;">
        <div>
          <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 6px;">
            <span class="badge badge-awaiting">RISK: ${app.risk_level.toUpperCase()}</span>
            <span style="font-family: var(--font-mono); font-size: 11px; color: var(--text-muted);">${app.created_at.substring(0, 19)}</span>
          </div>
          <div style="font-size: 14px; font-weight: 600; color: #fff;">${escapeHtml(app.action_description)}</div>
          <div style="font-size: 12px; font-family: var(--font-mono); color: var(--text-muted); margin-top: 4px;">Task ID: ${app.task_id}</div>
        </div>
        <div style="display: flex; gap: 10px;">
          <button class="btn btn-danger btn-sm" onclick="resolveApproval('${app.id}', 'rejected')">Reject</button>
          <button class="btn btn-success btn-sm" onclick="resolveApproval('${app.id}', 'approved')">Approve Action</button>
        </div>
      </div>
    `).join('');
  } catch (e) {
    console.error('Failed to load approvals', e);
  }
}

window.resolveApproval = async function(approvalId, decision) {
  try {
    const res = await fetch(`/api/approvals/${approvalId}/resolve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision, reason: `Resolved via Web Dashboard as ${decision}` }),
    });

    if (res.ok) {
      showToast(`Approval marked as ${decision.toUpperCase()}`);
      loadApprovals();
      loadTasks();
    } else {
      showToast('Failed to resolve approval', 'error');
    }
  } catch (e) {
    showToast('Network error resolving approval', 'error');
  }
};

/* ==========================================================================
   Artifacts Gallery
   ========================================================================== */

async function loadArtifacts() {
  try {
    const res = await fetch('/api/artifacts');
    if (!res.ok) return;
    allArtifacts = await res.json();

    document.getElementById('badge-artifacts-count').textContent = allArtifacts.length;
    renderArtifactsGrid();
  } catch (e) {
    console.error('Failed to load artifacts', e);
  }
}

function renderArtifactsGrid() {
  const grid = document.getElementById('artifacts-grid');
  if (!grid) return;

  const typeFilter = document.getElementById('filter-artifact-type')?.value || '';
  const filtered = typeFilter
    ? allArtifacts.filter(a => a.mime_type.includes(typeFilter))
    : allArtifacts;

  if (filtered.length === 0) {
    grid.innerHTML = '<div class="empty-state">No artifacts generated yet. Run a screenshot or file task to create one.</div>';
    return;
  }

  grid.innerHTML = filtered.map(a => {
    const isImage = a.mime_type.startsWith('image/');
    const previewUrl = `/api/artifacts/file/${encodeURIComponent(a.id)}`;

    return `
      <div class="artifact-card">
        <div class="artifact-preview-wrap" onclick="previewArtifact('${a.id}', '${escapeHtml(a.file_name)}', ${isImage})">
          ${isImage 
            ? `<img src="${previewUrl}" class="artifact-thumb" alt="${escapeHtml(a.file_name)}" loading="lazy">` 
            : `<div class="artifact-file-icon">📄</div>`
          }
        </div>
        <div class="artifact-meta">
          <div class="artifact-title" title="${escapeHtml(a.file_name)}">${escapeHtml(a.file_name)}</div>
          <div class="artifact-sub">${(a.size_bytes / 1024).toFixed(1)} KB • ${a.mime_type}</div>
          <div style="margin-top: 10px;">
            <a href="${previewUrl}" target="_blank" class="btn btn-secondary btn-sm" style="width: 100%; justify-content: center;">Open File</a>
          </div>
        </div>
      </div>
    `;
  }).join('');
}

window.previewArtifact = function(artifactId, fileName, isImage) {
  if (isImage) {
    const modal = document.getElementById('image-modal');
    document.getElementById('modal-image-title').textContent = fileName;
    document.getElementById('modal-preview-img').src = `/api/artifacts/file/${encodeURIComponent(artifactId)}`;
    modal.classList.remove('hidden');
  } else {
    window.open(`/api/artifacts/file/${encodeURIComponent(artifactId)}`, '_blank');
  }
};

/* ==========================================================================
   Clipboard Memory
   ========================================================================== */

function initClipboardActions() {
  document.getElementById('btn-clipboard-capture-now')?.addEventListener('click', async () => {
    try {
      const res = await fetch('/api/clipboard/capture', { method: 'POST' });
      const data = await res.json();
      if (data.captured) {
        showToast(`Captured: ${data.captured.content_type.toUpperCase()}`);
        loadClipboard();
      } else {
        showToast('No new content on clipboard');
      }
    } catch (e) {
      showToast('Failed to capture clipboard', 'error');
    }
  });

  const searchInput = document.getElementById('clipboard-search-input');
  const typeFilter = document.getElementById('clipboard-type-filter');

  searchInput?.addEventListener('input', () => renderClipboardStream());
  typeFilter?.addEventListener('change', () => renderClipboardStream());
}

async function loadClipboard() {
  try {
    const res = await fetch('/api/clipboard');
    if (!res.ok) return;
    allClipboard = await res.json();
    renderClipboardStream();
  } catch (e) {
    console.error('Failed to load clipboard', e);
  }
}

function renderClipboardStream() {
  const container = document.getElementById('clipboard-stream-container');
  if (!container) return;

  const query = document.getElementById('clipboard-search-input')?.value.toLowerCase() || '';
  const typeFilter = document.getElementById('clipboard-type-filter')?.value || '';

  const filtered = allClipboard.filter(c => {
    const matchesQuery = !query || (c.content_text && c.content_text.toLowerCase().includes(query));
    const matchesType = !typeFilter || c.content_type === typeFilter;
    return matchesQuery && matchesType;
  });

  if (filtered.length === 0) {
    container.innerHTML = '<div class="empty-state">No clipboard entries found.</div>';
    return;
  }

  container.innerHTML = filtered.map(c => {
    const snippet = c.content_text ? escapeHtml(c.content_text) : '';
    const dateStr = c.updated_at ? c.updated_at.replace('T', ' ').substring(0, 19) : '';

    return `
      <div class="clip-item">
        <div style="flex: 1; overflow: hidden;">
          <div class="clip-meta-row">
            <span class="clip-type-badge">${c.content_type}</span>
            <span class="clip-date">${dateStr}</span>
          </div>
          <div class="clip-content">${snippet}</div>
        </div>
        <button class="btn btn-secondary btn-sm" onclick="copyToWindowsClipboard('${c.id}')">Copy</button>
      </div>
    `;
  }).join('');
}

window.copyToWindowsClipboard = async function(entryId) {
  try {
    const res = await fetch('/api/clipboard/copy', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ entry_id: entryId }),
    });
    if (res.ok) {
      showToast('Copied back to Windows clipboard!');
    } else {
      showToast('Failed to copy', 'error');
    }
  } catch (e) {
    showToast('Network error', 'error');
  }
};

/* ==========================================================================
   Desktop & Screen
   ========================================================================== */

function initDesktopActions() {
  document.getElementById('btn-refresh-desktop')?.addEventListener('click', () => {
    loadDesktopInfo();
    showToast('Desktop info refreshed');
  });

  document.getElementById('btn-desktop-capture-screen')?.addEventListener('click', async () => {
    try {
      showToast('Capturing desktop screenshot...');
      const res = await fetch('/api/desktop/screenshot', { method: 'POST' });
      const data = await res.json();
      if (res.ok) {
        showToast('Screenshot saved to artifacts!');
        loadArtifacts();
      } else {
        showToast('Screenshot failed', 'error');
      }
    } catch (e) {
      showToast('Failed to capture screenshot', 'error');
    }
  });
}

async function loadDesktopInfo() {
  try {
    // 1. Screen resolution & active window
    const res = await fetch('/api/desktop/screen');
    if (res.ok) {
      const info = await res.json();
      document.getElementById('disp-resolution').textContent = `${info.screen_width} x ${info.screen_height}`;
      document.getElementById('disp-active-window').textContent = info.active_window?.title || '(None)';
      document.getElementById('disp-active-hwnd').textContent = info.active_window?.hwnd || '0';
      document.getElementById('disp-active-geom').textContent = `${info.active_window?.width}x${info.active_window?.height} at (${info.active_window?.left}, ${info.active_window?.top})`;
    }

    // 2. Open windows table
    const winRes = await fetch('/api/desktop/windows');
    if (winRes.ok) {
      const windows = await winRes.json();
      document.getElementById('windows-count-badge').textContent = `${windows.length} visible`;
      const tbody = document.getElementById('windows-table-body');
      tbody.innerHTML = windows.map(w => `
        <tr>
          <td><span class="badge ${w.is_active ? 'badge-completed' : (w.is_minimized ? 'badge-cancelled' : 'badge-running')}">${w.is_active ? 'ACTIVE' : (w.is_minimized ? 'MIN' : 'VISIBLE')}</span></td>
          <td style="font-family: var(--font-mono); font-size: 11px;">${w.width}x${w.height}@${w.left},${w.top}</td>
          <td style="font-weight: 500; color: #fff;">${escapeHtml(w.title)}</td>
          <td>
            <button class="btn btn-secondary btn-sm" onclick="focusDesktopWindow('${escapeHtml(w.title)}')">Focus</button>
          </td>
        </tr>
      `).join('');
    }
  } catch (e) {
    console.error('Failed to load desktop info', e);
  }
}

window.focusDesktopWindow = async function(title) {
  try {
    const res = await fetch('/api/desktop/focus', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title }),
    });
    if (res.ok) {
      showToast(`Focused window: ${title}`);
      loadDesktopInfo();
    }
  } catch (e) {
    showToast('Failed to focus window', 'error');
  }
};

/* ==========================================================================
   Logs & Settings
   ========================================================================== */

async function loadSettings() {
  try {
    const res = await fetch('/api/settings');
    if (!res.ok) return;
    const s = await res.json();

    document.getElementById('chip-approval-mode').textContent = (s.approval_mode || 'SAFE').toUpperCase();

    const container = document.getElementById('settings-container');
    container.innerHTML = Object.entries(s).map(([k, v]) => `
      <div class="metric-row">
        <span class="metric-name">${k}:</span>
        <span class="metric-val">${escapeHtml(String(v))}</span>
      </div>
    `).join('');
  } catch (e) {
    console.error('Failed to load settings', e);
  }
}

async function loadLogs() {
  try {
    const res = await fetch('/api/logs');
    if (!res.ok) return;
    const data = await res.json();
    const codeBlock = document.getElementById('log-code-block');
    codeBlock.textContent = data.logs || 'No log entries available.';
    const scrollWin = document.getElementById('log-stream-container');
    scrollWin.scrollTop = scrollWin.scrollHeight;
  } catch (e) {
    console.error('Failed to load logs', e);
  }
}

document.getElementById('btn-refresh-logs')?.addEventListener('click', () => {
  loadLogs();
  showToast('Logs refreshed');
});

/* ==========================================================================
   Modals & Helpers
   ========================================================================== */

function initModals() {
  document.getElementById('btn-close-modal')?.addEventListener('click', () => {
    document.getElementById('task-modal').classList.add('hidden');
  });

  document.getElementById('btn-close-image-modal')?.addEventListener('click', () => {
    document.getElementById('image-modal').classList.add('hidden');
  });
}

function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.textContent = message;
  container.appendChild(toast);

  setTimeout(() => {
    toast.remove();
  }, 3500);
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
