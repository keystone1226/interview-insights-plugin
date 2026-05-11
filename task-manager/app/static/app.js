/* ── State ──────────────────────────────────────── */
let currentUser = null;
let currentWorkspace = null;
let allUsers = [];
let columns = [];
let tasks = [];
let notifPanelOpen = false;
let archivedCount = 0;
let claudeLeftPx = 0;
let claudeDir = 'left';
let claudeHovered = false;
let claudeWalkTimer = null;
let claudeLegTimer = null;
let claudeClickTimes = [];
let taskGenItems = [];

const TAG_COLORS = [
  '#6366f1', '#ec4899', '#14b8a6', '#f59e0b', '#8b5cf6',
  '#ef4444', '#06b6d4', '#84cc16', '#f97316', '#64748b',
];

function tagColor(tag) {
  let hash = 0;
  for (let i = 0; i < tag.length; i++) hash = tag.charCodeAt(i) + ((hash << 5) - hash);
  return TAG_COLORS[Math.abs(hash) % TAG_COLORS.length];
}

/* ── API helpers ────────────────────────────────── */
async function api(path, opts = {}) {
  const headers = { 'Content-Type': 'application/json', ...opts.headers };
  if (currentWorkspace) {
    headers['X-Workspace-Id'] = String(currentWorkspace.id);
  }
  if (currentUser && currentUser.id) {
    headers['X-User-Id'] = String(currentUser.id);
  }
  const res = await fetch(path, { headers, ...opts });
  if (res.status === 204) return null;
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || res.statusText);
  }
  return res.json();
}

/* ── Init ───────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', async () => {
  const saved = localStorage.getItem('taskmanager_user');
  if (saved) {
    try {
      currentUser = JSON.parse(saved);
      // Re-register (idempotent)
      currentUser = await api('/api/users', {
        method: 'POST',
        body: JSON.stringify({ nickname: currentUser.nickname, email: currentUser.email }),
      });
      localStorage.setItem('taskmanager_user', JSON.stringify(currentUser));
    } catch {
      localStorage.removeItem('taskmanager_user');
      currentUser = null;
    }
  }

  if (!currentUser) {
    showNicknameModal();
  } else {
    // Check for saved workspace
    const savedWs = localStorage.getItem('taskmanager_workspace');
    if (savedWs) {
      try {
        currentWorkspace = JSON.parse(savedWs);
        // Verify it still exists
        const ws = await api(`/api/workspaces/${currentWorkspace.id}`);
        currentWorkspace = ws;
        localStorage.setItem('taskmanager_workspace', JSON.stringify(ws));

        // If the workspace is now password-protected and we don't
        // have a cached unlock for this browser session, re-prompt.
        if (ws.has_password) {
          const cached = sessionStorage.getItem(`taskmanager_ws_unlocked_${ws.id}`);
          if (!cached) {
            const pw = await promptWorkspaceUnlock(ws.id, ws.name);
            if (!pw) {
              currentWorkspace = null;
              localStorage.removeItem('taskmanager_workspace');
              showWorkspaceModal();
              return;
            }
          }
        }
        startApp();
      } catch {
        localStorage.removeItem('taskmanager_workspace');
        currentWorkspace = null;
        showWorkspaceModal();
      }
    } else {
      showWorkspaceModal();
    }
  }
});

/* ── Nickname Modal ─────────────────────────────── */
function showNicknameModal() {
  document.getElementById('nicknameModal').classList.add('active');
  document.getElementById('nicknameInput').focus();
}

document.getElementById('nicknameSubmit').addEventListener('click', async () => {
  const nickname = document.getElementById('nicknameInput').value.trim();
  if (!nickname) return;
  const email = document.getElementById('emailInput').value.trim() || null;
  try {
    currentUser = await api('/api/users', {
      method: 'POST',
      body: JSON.stringify({ nickname, email }),
    });
    localStorage.setItem('taskmanager_user', JSON.stringify(currentUser));
    document.getElementById('nicknameModal').classList.remove('active');
    showWorkspaceModal();
  } catch (e) {
    alert('Error: ' + e.message);
  }
});

document.getElementById('nicknameInput').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') document.getElementById('nicknameSubmit').click();
});

/* ── Workspace Modal ────────────────────────────── */
function showWorkspaceModal() {
  document.getElementById('workspaceModal').classList.add('active');
  loadWorkspaceList();
}

async function loadWorkspaceList() {
  const list = document.getElementById('workspaceList');
  try {
    const workspaces = await api('/api/workspaces');
    if (workspaces.length === 0) {
      list.innerHTML = '<div class="workspace-empty">No workspaces yet. Create one below.</div>';
    } else {
      list.innerHTML = workspaces.map(ws => {
        const lockBadge = ws.has_password
          ? '<span class="ws-lock-badge" title="Password protected">&#128274;</span>'
          : '';
        const pwLabel = ws.has_password ? 'Password' : 'Lock';
        return `
        <div class="workspace-item" data-id="${ws.id}" data-name="${escHtml(ws.name)}" data-has-password="${ws.has_password ? '1' : '0'}">
          <div class="workspace-item-top">
            <div>
              <div class="workspace-item-name">${lockBadge}${escHtml(ws.name)}</div>
              <div class="workspace-item-desc">${escHtml(ws.description || '')}</div>
            </div>
            <div class="workspace-item-actions" onclick="event.stopPropagation()">
              <button class="btn btn-sm btn-secondary ws-password-btn" data-id="${ws.id}" data-name="${escHtml(ws.name)}" data-has-password="${ws.has_password ? '1' : '0'}" title="Set / change password">${pwLabel}</button>
              <button class="btn btn-sm btn-secondary ws-backup-btn" data-id="${ws.id}" data-name="${escHtml(ws.name)}" title="Download Backup">Backup</button>
              <button class="btn btn-sm btn-danger ws-delete-btn" data-id="${ws.id}" data-name="${escHtml(ws.name)}" title="Delete">Delete</button>
            </div>
          </div>
        </div>
      `;
      }).join('');

      list.querySelectorAll('.workspace-item').forEach(el => {
        el.addEventListener('click', async () => {
          const wsId = parseInt(el.dataset.id);
          const hasPassword = el.dataset.hasPassword === '1';
          const wsName = el.dataset.name;
          let password = null;

          if (hasPassword) {
            // Skip the unlock prompt if we've already verified this workspace
            // in the current browser session.
            const cached = sessionStorage.getItem(`taskmanager_ws_unlocked_${wsId}`);
            if (cached) {
              password = cached;
            } else {
              password = await promptWorkspaceUnlock(wsId, wsName);
              if (!password) return; // user cancelled
            }
          }

          try {
            const joinUrl = `/api/workspaces/${wsId}/join?user_id=${currentUser.id}` +
              (password ? `&password=${encodeURIComponent(password)}` : '');
            await api(joinUrl, { method: 'POST' });
          } catch (err) {
            if (hasPassword) {
              // Cached password was wrong (e.g. password changed elsewhere)
              sessionStorage.removeItem(`taskmanager_ws_unlocked_${wsId}`);
            }
            alert('Workspace join failed: ' + err.message);
            return;
          }
          const ws = await api(`/api/workspaces/${wsId}`);
          currentWorkspace = ws;
          localStorage.setItem('taskmanager_workspace', JSON.stringify(ws));
          document.getElementById('workspaceModal').classList.remove('active');
          startApp();
        });
      });

      // Password buttons
      list.querySelectorAll('.ws-password-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          openWsPasswordModal(
            parseInt(btn.dataset.id),
            btn.dataset.name,
            btn.dataset.hasPassword === '1',
          );
        });
      });

      // Backup buttons
      list.querySelectorAll('.ws-backup-btn').forEach(btn => {
        btn.addEventListener('click', async (e) => {
          e.stopPropagation();
          const wsId = btn.dataset.id;
          const wsName = btn.dataset.name;
          btn.textContent = '...';
          btn.disabled = true;
          try {
            const res = await fetch(`/api/workspaces/${wsId}/backup`);
            if (!res.ok) throw new Error('Backup failed');
            const blob = await res.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `${wsName.replace(/ /g, '_')}_backup_${new Date().toISOString().slice(0,10)}.md`;
            a.click();
            URL.revokeObjectURL(url);
          } catch (err) {
            alert('Backup error: ' + err.message);
          } finally {
            btn.textContent = 'Backup';
            btn.disabled = false;
          }
        });
      });

      // Delete buttons
      list.querySelectorAll('.ws-delete-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          openDeleteWsModal(parseInt(btn.dataset.id), btn.dataset.name);
        });
      });
    }
  } catch (e) {
    list.innerHTML = '<div class="workspace-empty">Error loading workspaces</div>';
  }
}

/* ── Workspace Password: Set / Change / Clear ──── */
let wsPasswordTarget = null;

function openWsPasswordModal(wsId, wsName, hasPassword) {
  wsPasswordTarget = { id: wsId, name: wsName, hasPassword };
  document.getElementById('wsPasswordTitle').textContent = hasPassword
    ? `Change Password — ${wsName}`
    : `Set Password — ${wsName}`;
  document.getElementById('wsPasswordSubtitle').textContent = hasPassword
    ? '현재 비밀번호를 입력한 뒤, 새 비밀번호를 설정하거나 비워서 해제하세요.'
    : '워크스페이스에 접근할 때 입력해야 하는 비밀번호를 설정합니다.';
  document.getElementById('wsPasswordCurrentGroup').style.display = hasPassword ? 'block' : 'none';
  document.getElementById('wsPasswordCurrent').value = '';
  document.getElementById('wsPasswordNew').value = '';
  document.getElementById('wsPasswordModal').classList.add('active');
  setTimeout(() => {
    (hasPassword
      ? document.getElementById('wsPasswordCurrent')
      : document.getElementById('wsPasswordNew')
    ).focus();
  }, 50);
}

function closeWsPasswordModal() {
  document.getElementById('wsPasswordModal').classList.remove('active');
  wsPasswordTarget = null;
}

document.getElementById('wsPasswordCancelBtn').addEventListener('click', closeWsPasswordModal);

document.getElementById('wsPasswordSaveBtn').addEventListener('click', async () => {
  if (!wsPasswordTarget) return;
  const { id, hasPassword } = wsPasswordTarget;
  const current = document.getElementById('wsPasswordCurrent').value;
  const next = document.getElementById('wsPasswordNew').value;
  try {
    const res = await api(`/api/workspaces/${id}/password`, {
      method: 'PUT',
      body: JSON.stringify({
        current_password: hasPassword ? current : null,
        new_password: next || null,
      }),
    });
    alert(res.message || 'Saved.');
    // Clear any cached unlock state for this workspace — it may be stale now.
    sessionStorage.removeItem(`taskmanager_ws_unlocked_${id}`);
    closeWsPasswordModal();
    loadWorkspaceList();
  } catch (err) {
    alert('Error: ' + err.message);
  }
});

document.getElementById('wsPasswordNew').addEventListener('keydown', e => {
  if (e.key === 'Enter') document.getElementById('wsPasswordSaveBtn').click();
});

/* ── Workspace Unlock Prompt ──────────────────── */
let wsUnlockResolver = null;

function promptWorkspaceUnlock(wsId, wsName) {
  document.getElementById('wsUnlockName').textContent = wsName;
  document.getElementById('wsUnlockInput').value = '';
  document.getElementById('wsUnlockError').style.display = 'none';
  document.getElementById('wsUnlockModal').classList.add('active');
  setTimeout(() => document.getElementById('wsUnlockInput').focus(), 50);
  return new Promise(resolve => {
    wsUnlockResolver = async (password) => {
      if (password === null) {
        document.getElementById('wsUnlockModal').classList.remove('active');
        wsUnlockResolver = null;
        resolve(null);
        return;
      }
      // Verify against server before accepting.
      try {
        await api(`/api/workspaces/${wsId}/verify-password`, {
          method: 'POST',
          body: JSON.stringify({ password }),
        });
        sessionStorage.setItem(`taskmanager_ws_unlocked_${wsId}`, password);
        document.getElementById('wsUnlockModal').classList.remove('active');
        wsUnlockResolver = null;
        resolve(password);
      } catch (err) {
        const errEl = document.getElementById('wsUnlockError');
        errEl.textContent = err.message || '비밀번호가 일치하지 않습니다.';
        errEl.style.display = 'block';
      }
    };
  });
}

document.getElementById('wsUnlockSubmitBtn').addEventListener('click', () => {
  if (!wsUnlockResolver) return;
  const pw = document.getElementById('wsUnlockInput').value;
  if (!pw) return;
  wsUnlockResolver(pw);
});

document.getElementById('wsUnlockCancelBtn').addEventListener('click', () => {
  if (wsUnlockResolver) wsUnlockResolver(null);
});

document.getElementById('wsUnlockInput').addEventListener('keydown', e => {
  if (e.key === 'Enter') document.getElementById('wsUnlockSubmitBtn').click();
});

/* ── Delete Workspace Confirmation ─────────────── */
let deleteWsTarget = null;

function openDeleteWsModal(wsId, wsName) {
  deleteWsTarget = { id: wsId, name: wsName };
  document.getElementById('deleteWsTargetName').textContent = wsName;
  document.getElementById('deleteWsConfirmInput').value = '';
  document.getElementById('deleteWsConfirmBtn').disabled = true;
  document.getElementById('deleteWsModal').classList.add('active');
  document.getElementById('deleteWsConfirmInput').focus();
}

document.getElementById('deleteWsConfirmInput').addEventListener('input', () => {
  const val = document.getElementById('deleteWsConfirmInput').value;
  document.getElementById('deleteWsConfirmBtn').disabled = (val !== deleteWsTarget?.name);
});

document.getElementById('deleteWsCancelBtn').addEventListener('click', () => {
  document.getElementById('deleteWsModal').classList.remove('active');
  deleteWsTarget = null;
});

document.getElementById('deleteWsConfirmBtn').addEventListener('click', async () => {
  if (!deleteWsTarget) return;
  const confirmName = document.getElementById('deleteWsConfirmInput').value;
  try {
    await api(`/api/workspaces/${deleteWsTarget.id}?confirm_name=${encodeURIComponent(confirmName)}`, { method: 'DELETE' });
    // If we deleted the current workspace, reset
    if (currentWorkspace && currentWorkspace.id === deleteWsTarget.id) {
      currentWorkspace = null;
      localStorage.removeItem('taskmanager_workspace');
    }
    document.getElementById('deleteWsModal').classList.remove('active');
    deleteWsTarget = null;
    loadWorkspaceList();
  } catch (err) {
    alert('Delete error: ' + err.message);
  }
});

// Intentionally no overlay-click handler on deleteWsModal —
// the Cancel button is the only way to dismiss it to avoid
// accidentally losing the typed confirmation name.

/* ── Restore Backup ────────────────────────────── */
document.getElementById('restoreBackupBtn').addEventListener('click', () => {
  document.getElementById('restoreFileInput').click();
});

document.getElementById('restoreFileInput').addEventListener('change', async () => {
  const fileInput = document.getElementById('restoreFileInput');
  if (!fileInput.files.length) return;
  const file = fileInput.files[0];

  // .db file → DB file restore
  if (file.name.endsWith('.db')) {
    const confirmed = confirm(
      `DB 파일을 업로드하면 현재 모든 데이터가 교체됩니다.\n\n` +
      `파일: ${file.name} (${(file.size / 1024).toFixed(1)} KB)\n\n` +
      `기존 DB는 자동 백업됩니다.\n업로드 후 서버 재시작이 필요합니다.\n\n계속하시겠습니까?`
    );
    if (!confirmed) { fileInput.value = ''; return; }
    const formData = new FormData();
    formData.append('file', file);
    try {
      const res = await fetch('/api/backup/db', { method: 'POST', body: formData });
      const result = await res.json();
      if (!res.ok) throw new Error(result.detail || 'Upload failed');
      alert(`${result.message}\n\n서버 관리자에게 재시작을 요청하세요.`);
    } catch (err) {
      alert('DB restore error: ' + err.message);
    } finally { fileInput.value = ''; }
    return;
  }

  // .md file → Workspace markdown restore
  const text = await file.text();
  const metaMatch = text.match(/<!-- BACKUP_META\s*([\s\S]*?)\s*BACKUP_META -->/);
  let wsName = file.name;
  let existingWarning = '';
  if (metaMatch) {
    try {
      const meta = JSON.parse(metaMatch[1]);
      wsName = meta.workspace_name || wsName;
    } catch {}
  }

  try {
    const workspaces = await api('/api/workspaces');
    const existing = workspaces.find(w => w.name === wsName);
    if (existing) {
      existingWarning = `\n\n[WARNING] Workspace "${wsName}" already exists. All existing data will be overwritten!`;
    }
  } catch {}

  const confirmed = confirm(
    `Restore workspace from backup file?\n\nFile: ${file.name}\nWorkspace: ${wsName}${existingWarning}\n\nContinue?`
  );
  if (!confirmed) { fileInput.value = ''; return; }

  const formData = new FormData();
  formData.append('file', file);

  try {
    const res = await fetch(`/api/workspaces/restore?owner_id=${currentUser.id}`, {
      method: 'POST',
      body: formData,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Restore failed');
    }
    const result = await res.json();
    alert(`Restore complete: ${result.workspace_name}`);

    const ws = await api(`/api/workspaces/${result.workspace_id}`);
    await api(`/api/workspaces/${result.workspace_id}/join?user_id=${currentUser.id}`, { method: 'POST' });
    currentWorkspace = ws;
    localStorage.setItem('taskmanager_workspace', JSON.stringify(ws));
    document.getElementById('workspaceModal').classList.remove('active');
    startApp();
  } catch (err) {
    alert('Restore error: ' + err.message);
  } finally {
    fileInput.value = '';
  }
});

document.getElementById('createWorkspaceBtn').addEventListener('click', async () => {
  const name = document.getElementById('newWorkspaceName').value.trim();
  if (!name) return;
  try {
    const ws = await api(`/api/workspaces?owner_id=${currentUser.id}`, {
      method: 'POST',
      body: JSON.stringify({ name }),
    });
    currentWorkspace = ws;
    localStorage.setItem('taskmanager_workspace', JSON.stringify(ws));
    document.getElementById('workspaceModal').classList.remove('active');
    document.getElementById('newWorkspaceName').value = '';
    startApp();
  } catch (e) {
    alert('Error: ' + e.message);
  }
});

document.getElementById('newWorkspaceName').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') document.getElementById('createWorkspaceBtn').click();
});

/* ── DB File Backup / Restore ──────────────────── */
document.getElementById('downloadDbBtn').addEventListener('click', async () => {
  const btn = document.getElementById('downloadDbBtn');
  btn.textContent = '...';
  btn.disabled = true;
  try {
    const res = await fetch('/api/backup/db');
    if (!res.ok) throw new Error('Download failed');
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `tasks_backup_${new Date().toISOString().slice(0,10)}.db`;
    a.click();
    URL.revokeObjectURL(url);
  } catch (err) {
    alert('DB download error: ' + err.message);
  } finally {
    btn.textContent = 'Download DB';
    btn.disabled = false;
  }
});

document.getElementById('uploadDbBtn').addEventListener('click', () => {
  document.getElementById('dbFileInput').click();
});

document.getElementById('dbFileInput').addEventListener('change', async () => {
  const fileInput = document.getElementById('dbFileInput');
  if (!fileInput.files.length) return;
  const file = fileInput.files[0];

  const confirmed = confirm(
    `DB 파일을 업로드하면 현재 모든 데이터가 교체됩니다.\n\n` +
    `파일: ${file.name} (${(file.size / 1024).toFixed(1)} KB)\n\n` +
    `기존 DB는 자동 백업됩니다.\n업로드 후 서버 재시작이 필요합니다.\n\n계속하시겠습니까?`
  );
  if (!confirmed) {
    fileInput.value = '';
    return;
  }

  const formData = new FormData();
  formData.append('file', file);
  try {
    const res = await fetch('/api/backup/db', { method: 'POST', body: formData });
    const result = await res.json();
    if (!res.ok) throw new Error(result.detail || 'Upload failed');
    alert(`${result.message}\n\n서버 관리자에게 재시작을 요청하세요.`);
  } catch (err) {
    alert('DB upload error: ' + err.message);
  } finally {
    fileInput.value = '';
  }
});

document.getElementById('logoutBtn').addEventListener('click', () => {
  localStorage.removeItem('taskmanager_user');
  localStorage.removeItem('taskmanager_workspace');
  currentUser = null;
  currentWorkspace = null;
  document.getElementById('workspaceModal').classList.remove('active');
  showNicknameModal();
});

document.getElementById('switchWorkspaceBtn').addEventListener('click', () => {
  showWorkspaceModal();
});

/* ── Start App ──────────────────────────────────── */
async function startApp() {
  try {
    document.getElementById('currentUserName').textContent = currentUser.nickname;
    if (currentWorkspace) {
      document.getElementById('workspaceName').textContent = '/ ' + currentWorkspace.name;
    }
    document.getElementById('switchWorkspaceBtn').style.display = '';
    document.getElementById('restoreBackupBtn').style.display = '';
    await Promise.all([loadColumns(), loadUsers()]);
    await Promise.all([loadTasks(), refreshArchivedCount()]);
    console.log('Loaded columns:', columns.length, 'users:', allUsers.length, 'tasks:', tasks.length);
    renderBoard();
    console.log('Board rendered successfully');
    pollNotifications();
    setInterval(pollNotifications, 30000);
  } catch (err) {
    console.error('startApp error:', err);
    alert('App initialization error: ' + err.message);
  }
}

/* ── Data Loading ───────────────────────────────── */
async function loadColumns() {
  columns = await api('/api/columns');
}

async function loadUsers() {
  allUsers = await api('/api/users');
}

async function loadTasks() {
  tasks = await api('/api/tasks');
}

/* ── Notifications ──────────────────────────────── */
async function pollNotifications() {
  if (!currentUser) return;
  try {
    const data = await api(`/api/users/${currentUser.id}/notifications/count`);
    const badge = document.getElementById('notifBadge');
    if (data.unread_count > 0) {
      badge.textContent = data.unread_count;
      badge.style.display = 'flex';
    } else {
      badge.style.display = 'none';
    }
  } catch {}
}

document.getElementById('notifBell').addEventListener('click', async () => {
  notifPanelOpen = !notifPanelOpen;
  const panel = document.getElementById('notifPanel');
  if (notifPanelOpen) {
    panel.classList.add('active');
    const notifications = await api(`/api/users/${currentUser.id}/notifications`);
    renderNotifications(notifications);
  } else {
    panel.classList.remove('active');
  }
});

document.getElementById('markAllRead').addEventListener('click', async () => {
  await api(`/api/users/${currentUser.id}/notifications/read-all`, { method: 'POST' });
  pollNotifications();
  const notifications = await api(`/api/users/${currentUser.id}/notifications`);
  renderNotifications(notifications);
});

function renderNotifications(notifications) {
  const list = document.getElementById('notifList');
  if (!notifications.length) {
    list.innerHTML = '<div class="notification-empty">No notifications</div>';
    return;
  }
  list.innerHTML = notifications.map(n => `
    <div class="notification-item ${n.is_read ? '' : 'unread'}"
         data-id="${n.id}" data-task-id="${n.task_id}">
      <div>${n.message}</div>
      <div class="notif-time">${timeAgo(n.created_at)}</div>
    </div>
  `).join('');

  list.querySelectorAll('.notification-item').forEach(el => {
    el.addEventListener('click', async () => {
      await api(`/api/notifications/${el.dataset.id}/read`, { method: 'PATCH' });
      el.classList.remove('unread');
      pollNotifications();
      const taskId = parseInt(el.dataset.taskId);
      const task = tasks.find(t => t.id === taskId);
      if (task) openTaskModal(task);
    });
  });
}

/* ── Board Rendering ────────────────────────────── */
function renderBoard() {
  const board = document.getElementById('board');
  board.innerHTML = '';

  columns.forEach(col => {
    const colTasks = tasks.filter(t => t.status === col.name)
      .sort((a, b) => a.sort_order - b.sort_order);

    const colEl = document.createElement('div');
    colEl.className = 'column';
    colEl.innerHTML = `
      <div class="column-color-bar" style="background:${col.color || '#6b7280'}"></div>
      <div class="column-header">
        <span>${col.name.replace(/_/g, ' ')}</span>
        <span class="count">${colTasks.length}</span>
      </div>
      <div class="column-body" data-status="${col.name}">
        ${colTasks.map(t => renderTaskCard(t)).join('')}
        <button class="add-task-btn" data-status="${col.name}">+ Add Task</button>
      </div>
    `;
    board.appendChild(colEl);

    // Drag & drop
    const body = colEl.querySelector('.column-body');
    body.addEventListener('dragover', e => {
      e.preventDefault();
      body.classList.add('drag-over');
    });
    body.addEventListener('dragleave', () => body.classList.remove('drag-over'));
    body.addEventListener('drop', async e => {
      e.preventDefault();
      body.classList.remove('drag-over');
      const taskId = parseInt(e.dataTransfer.getData('text/plain'));
      const newStatus = body.dataset.status;
      try {
        await api(`/api/tasks/${taskId}/status`, {
          method: 'PATCH',
          body: JSON.stringify({ status: newStatus, sort_order: 0 }),
        });
        await loadTasks();
        renderBoard();
      } catch {}
    });

    // Add task button
    colEl.querySelector('.add-task-btn').addEventListener('click', (e) => {
      e.stopPropagation();
      try {
        openTaskModal(null, col.name);
      } catch (err) {
        console.error('openTaskModal error:', err);
        alert('Error opening modal: ' + err.message);
      }
    });
  });

  // Archive column
  const archiveCol = document.createElement('div');
  archiveCol.className = 'column column-archive';
  archiveCol.innerHTML = `
    <div class="column-color-bar" style="background:#78716c"></div>
    <div class="column-header">
      <span>ARCHIVE</span>
      <span class="count" id="archiveCount">${archivedCount}</span>
    </div>
    <div class="column-body archive-body" id="archiveDropZone">
      <div class="claude-walk-area" id="claudeWalkArea">
        <div class="claude-character-wrapper" id="claudeCharacter">
          <div class="claude-emoji" id="claudeEmoji"></div>
          <svg class="claude-svg" viewBox="0 0 120 100">
            <rect x="30" y="41" width="60" height="44" fill="#E88B5F"/>
            <rect x="22" y="56" width="8" height="15" fill="#E88B5F"/>
            <rect x="90" y="56" width="8" height="15" fill="#E88B5F"/>
            <rect class="claude-leg" x="30" y="85" width="8" height="15" fill="#E88B5F"/>
            <rect class="claude-leg" x="44" y="85" width="8" height="15" fill="#E88B5F"/>
            <rect class="claude-leg" x="68" y="85" width="8" height="15" fill="#E88B5F"/>
            <rect class="claude-leg" x="82" y="85" width="8" height="15" fill="#E88B5F"/>
            <rect id="claudeEyeL" x="36" y="50" width="8" height="8" fill="#111"/>
            <rect id="claudeEyeR" x="71" y="50" width="8" height="8" fill="#111"/>
            <path id="claudeHeartPath" class="claude-heart-path" d="M60.2727 29.2727L51.5114 20.5114C50.8125 19.8125 50.3466 19 50.1136 18.0739C49.8864 17.1477 49.8892 16.2273 50.1222 15.3125C50.3551 14.392 50.8182 13.5909 51.5114 12.9091C52.2216 12.2102 53.0313 11.7472 53.9403 11.5199C54.8551 11.2869 55.767 11.2869 56.6761 11.5199C57.5909 11.7528 58.4034 12.2159 59.1136 12.9091L60.2727 14.0341L61.4318 12.9091C62.1477 12.2159 62.9602 11.7528 63.8693 11.5199C64.7784 11.2869 65.6875 11.2869 66.5966 11.5199C67.5114 11.7472 68.3239 12.2102 69.0341 12.9091C69.7273 13.5909 70.1903 14.392 70.4233 15.3125C70.6563 16.2273 70.6563 17.1477 70.4233 18.0739C70.196 19 69.733 19.8125 69.0341 20.5114L60.2727 29.2727Z" fill="#FF0000" opacity="0"/>
          </svg>
        </div>
      </div>
      <div class="archive-drop-target">
        Drop Here to Archive
      </div>
      <button class="btn btn-primary archive-browse-btn" id="openArchiveBtn">Browse Archived</button>
    </div>
  `;
  board.appendChild(archiveCol);

  // Archive drag-drop on entire body
  const archiveBody = archiveCol.querySelector('.archive-body');
  archiveBody.addEventListener('dragover', e => {
    e.preventDefault();
    archiveBody.classList.add('drag-over');
  });
  archiveBody.addEventListener('dragleave', () => archiveBody.classList.remove('drag-over'));
  archiveBody.addEventListener('drop', async e => {
    e.preventDefault();
    archiveBody.classList.remove('drag-over');
    const taskId = parseInt(e.dataTransfer.getData('text/plain'));
    try {
      await api(`/api/tasks/${taskId}/archive`, { method: 'POST' });
      await loadTasks();
      await refreshArchivedCount();
      renderBoard();
      showClaudeHeart();
    } catch {}
  });

  archiveCol.querySelector('#openArchiveBtn').addEventListener('click', () => {
    openArchiveModal();
  });

  initClaudeCharacter();

  // Card event listeners
  board.querySelectorAll('.task-card').forEach(card => {
    card.addEventListener('dragstart', e => {
      e.dataTransfer.setData('text/plain', card.dataset.id);
      card.classList.add('dragging');
    });
    card.addEventListener('dragend', () => card.classList.remove('dragging'));
    card.addEventListener('click', () => {
      const task = tasks.find(t => t.id === parseInt(card.dataset.id));
      if (!task) return;
      // Clicking a still-present onboarding task resumes the tour at the
      // matching step instead of opening the regular task modal.
      if (
        typeof Onboarding !== 'undefined' &&
        Onboarding.isOnboardingTaskTitle(task.title) &&
        parseTags(task.tags).includes('onboarding')
      ) {
        Onboarding.startAtKey(Onboarding.stepKeyForTaskTitle(task.title));
        return;
      }
      openTaskModal(task);
    });
  });
}

function renderTaskCard(task) {
  const tags = parseTags(task.tags);
  const dueDateHtml = task.due_date ? renderDueDate(task.due_date) : '';
  const assignee = task.assignee_user ? task.assignee_user.nickname : '';
  const coverImg = task.image_path
    ? `<img class="task-card-cover" src="${task.image_path}" alt="cover">`
    : '';

  const linkIcons = [];
  if (task.figma_url) {
    linkIcons.push(`<a class="link-icon" href="${escHtml(task.figma_url)}" target="_blank" title="Figma" onclick="event.stopPropagation()">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M5 5.5A3.5 3.5 0 0 1 8.5 2H12v7H8.5A3.5 3.5 0 0 1 5 5.5zM12 2h3.5a3.5 3.5 0 1 1 0 7H12V2zm0 12.5a3.5 3.5 0 1 1-7 0 3.5 3.5 0 0 1 7 0zm0-5.5h3.5a3.5 3.5 0 1 1 0 7H12V9zM5 12a3.5 3.5 0 0 1 3.5-3.5H12V12H8.5A3.5 3.5 0 0 1 5 12z"/></svg>
    </a>`);
  }
  if (task.confluence_url) {
    linkIcons.push(`<a class="link-icon" href="${escHtml(task.confluence_url)}" target="_blank" title="Confluence" onclick="event.stopPropagation()">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M2.046 18.395c-.345.575-.223.924.272 1.244l4.143 2.567c.494.32.843.198 1.188-.377.794-1.33 1.825-2.712 3.614-2.712 1.51 0 2.392.897 4.156 3.052.377.46.726.5 1.22.18l4.142-2.927c.494-.345.395-.694.05-1.193-2.138-3.076-4.583-6.48-9.548-6.48-4.74 0-7.51 3.107-9.237 6.646zM21.954 5.605c.345-.575.223-.924-.272-1.244L17.54 1.794c-.494-.32-.843-.198-1.188.377-.794 1.33-1.825 2.712-3.614 2.712-1.51 0-2.392-.897-4.156-3.052-.377-.46-.726-.5-1.22-.18L3.22 4.578c-.494.345-.395.694-.05 1.193 2.138 3.076 4.583 6.48 9.548 6.48 4.74 0 7.51-3.107 9.237-6.646z"/></svg>
    </a>`);
  }

  return `
    <div class="task-card" draggable="true" data-id="${task.id}">
      ${coverImg}
      <div class="task-card-title">${escHtml(task.title)}</div>
      <div class="task-card-meta">
        <span class="priority-badge priority-${task.priority}">${task.priority}</span>
        ${tags.map(t => `<span class="tag-badge" style="background:${tagColor(t)}22;color:${tagColor(t)}">${escHtml(t)}</span>`).join('')}
        ${linkIcons.join('')}
        ${dueDateHtml}
        ${assignee ? `<span class="assignee-badge">${escHtml(assignee)}</span>` : ''}
      </div>
    </div>
  `;
}

/* ── Task Modal ─────────────────────────────────── */
function openTaskModal(task, defaultStatus) {
  const modal = document.getElementById('taskModal');
  const title = document.getElementById('taskModalTitle');
  const form = document.getElementById('taskForm');
  const deleteBtn = document.getElementById('deleteTaskBtn');
  const rightCol = document.getElementById('taskModalRight');
  const modalColumns = document.getElementById('taskModalColumns');

  // Populate assignee dropdown
  const assigneeSelect = document.getElementById('taskAssignee');
  assigneeSelect.innerHTML = '<option value="">Unassigned</option>' +
    allUsers.map(u => `<option value="${u.id}">${escHtml(u.nickname)}</option>`).join('');

  const createdAtEl = document.getElementById('taskCreatedAt');
  const archiveBtn = document.getElementById('archiveTaskBtn');

  if (task) {
    title.textContent = 'Edit Task';
    document.getElementById('taskId').value = task.id;
    document.getElementById('taskStatus').value = task.status;
    document.getElementById('taskTitle').value = task.title;
    document.getElementById('taskDesc').value = task.description || '';
    document.getElementById('taskPriority').value = task.priority;
    document.getElementById('taskAssignee').value = task.assignee_id || '';
    document.getElementById('taskDueDate').value = task.due_date || '';
    document.getElementById('taskTags').value = parseTags(task.tags).join(', ');
    document.getElementById('taskFigma').value = task.figma_url || '';
    document.getElementById('taskConfluence').value = task.confluence_url || '';
    deleteBtn.style.display = 'block';
    archiveBtn.style.display = 'block';
    if (rightCol) rightCol.style.display = '';
    if (modalColumns) modalColumns.classList.remove('single-col');
    loadComments(task.id);

    // Show created_at
    const created = new Date(task.created_at);
    createdAtEl.textContent = `Created: ${created.toLocaleDateString('ko-KR')} ${created.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })}`;
    createdAtEl.style.display = 'block';

    if (task.image_path) {
      const preview = document.getElementById('imagePreview');
      preview.src = task.image_path;
      preview.style.display = 'block';
    } else {
      document.getElementById('imagePreview').style.display = 'none';
    }
  } else {
    title.textContent = 'New Task';
    form.reset();
    document.getElementById('taskId').value = '';
    document.getElementById('taskStatus').value = defaultStatus || 'TODO';
    deleteBtn.style.display = 'none';
    archiveBtn.style.display = 'none';
    if (rightCol) rightCol.style.display = 'none';
    if (modalColumns) modalColumns.classList.add('single-col');
    createdAtEl.style.display = 'none';
    document.getElementById('imagePreview').style.display = 'none';
  }

  modal.classList.add('active');
  document.getElementById('taskTitle').focus();
}

function closeTaskModal() {
  document.getElementById('taskModal').classList.remove('active');
}

document.getElementById('cancelTaskBtn').addEventListener('click', closeTaskModal);
// Intentionally NOT closing the task modal on overlay click —
// clicking outside the dialog used to wipe out in-progress input.
// Close/Cancel/Delete buttons are the only way to dismiss it now.

document.getElementById('taskForm').addEventListener('submit', async e => {
  e.preventDefault();
  const id = document.getElementById('taskId').value;
  const tagsRaw = document.getElementById('taskTags').value;
  const tags = tagsRaw
    ? JSON.stringify(tagsRaw.split(',').map(t => t.trim()).filter(Boolean))
    : null;

  const data = {
    title: document.getElementById('taskTitle').value,
    description: document.getElementById('taskDesc').value || null,
    status: document.getElementById('taskStatus').value,
    priority: document.getElementById('taskPriority').value,
    assignee_id: document.getElementById('taskAssignee').value || null,
    due_date: document.getElementById('taskDueDate').value || null,
    tags,
    figma_url: document.getElementById('taskFigma').value || null,
    confluence_url: document.getElementById('taskConfluence').value || null,
  };

  if (data.assignee_id) data.assignee_id = parseInt(data.assignee_id);

  try {
    let savedTask;
    if (id) {
      savedTask = await api(`/api/tasks/${id}`, { method: 'PATCH', body: JSON.stringify(data) });
    } else {
      savedTask = await api('/api/tasks', { method: 'POST', body: JSON.stringify(data) });
    }

    // Upload image if selected
    const imageInput = document.getElementById('imageInput');
    if (imageInput.files.length > 0) {
      const formData = new FormData();
      formData.append('file', imageInput.files[0]);
      const imgHeaders = {};
      if (currentWorkspace) imgHeaders['X-Workspace-Id'] = String(currentWorkspace.id);
      if (currentUser && currentUser.id) imgHeaders['X-User-Id'] = String(currentUser.id);
      await fetch(`/api/tasks/${savedTask.id}/image`, { method: 'POST', body: formData, headers: imgHeaders });
    }

    await loadTasks();
    renderBoard();
    closeTaskModal();
  } catch (err) {
    alert('Error: ' + err.message);
  }
});

document.getElementById('deleteTaskBtn').addEventListener('click', async () => {
  const id = document.getElementById('taskId').value;
  if (!id || !confirm('Delete this task?')) return;
  await api(`/api/tasks/${id}`, { method: 'DELETE' });
  await loadTasks();
  renderBoard();
  closeTaskModal();
});

document.getElementById('archiveTaskBtn').addEventListener('click', async () => {
  const id = document.getElementById('taskId').value;
  if (!id) return;
  try {
    await api(`/api/tasks/${id}/archive`, { method: 'POST' });
    closeTaskModal();
    await loadTasks();
    await refreshArchivedCount();
    renderBoard();
    showClaudeHeart();
  } catch (err) {
    alert('Archive error: ' + err.message);
  }
});

/* ── Image Upload ───────────────────────────────── */
const imageUploadArea = document.getElementById('imageUploadArea');
const imageInput = document.getElementById('imageInput');

imageUploadArea.addEventListener('click', () => imageInput.click());
imageUploadArea.addEventListener('dragover', e => { e.preventDefault(); });
imageUploadArea.addEventListener('drop', e => {
  e.preventDefault();
  if (e.dataTransfer.files.length) {
    imageInput.files = e.dataTransfer.files;
    previewImage(e.dataTransfer.files[0]);
  }
});
imageInput.addEventListener('change', () => {
  if (imageInput.files.length) previewImage(imageInput.files[0]);
});

function previewImage(file) {
  const reader = new FileReader();
  reader.onload = e => {
    const preview = document.getElementById('imagePreview');
    preview.src = e.target.result;
    preview.style.display = 'block';
  };
  reader.readAsDataURL(file);
}

/* ── Comments ───────────────────────────────────── */
async function loadComments(taskId) {
  const comments = await api(`/api/tasks/${taskId}/comments`);
  const list = document.getElementById('commentsList');
  if (!comments.length) {
    list.innerHTML = '<div style="color:var(--text-muted);font-size:13px;padding:8px 0">No comments yet</div>';
    return;
  }
  list.innerHTML = comments.map(c => {
    const content = c.content.replace(/@(\S+)/g, '<span class="mention">@$1</span>');
    return `
      <div class="comment">
        <span class="comment-author">${escHtml(c.author?.nickname || 'Unknown')}</span>
        <span class="comment-time">${timeAgo(c.created_at)}</span>
        <div class="comment-content">${content}</div>
      </div>
    `;
  }).join('');
}

document.getElementById('addCommentBtn').addEventListener('click', async () => {
  const input = document.getElementById('commentInput');
  const content = input.value.trim();
  if (!content) return;
  const taskId = document.getElementById('taskId').value;
  if (!taskId) return;

  await api(`/api/tasks/${taskId}/comments`, {
    method: 'POST',
    body: JSON.stringify({ content, author_id: currentUser.id }),
  });
  input.value = '';
  await loadComments(taskId);
  pollNotifications();
});

document.getElementById('commentInput').addEventListener('keydown', e => {
  if (e.key === 'Enter') {
    e.preventDefault();
    document.getElementById('addCommentBtn').click();
  }
});

/* ── Mention Autocomplete ───────────────────────── */
const commentInput = document.getElementById('commentInput');
const mentionDropdown = document.getElementById('mentionDropdown');
let mentionStart = -1;

commentInput.addEventListener('input', () => {
  const val = commentInput.value;
  const cursor = commentInput.selectionStart;
  const beforeCursor = val.substring(0, cursor);
  const atMatch = beforeCursor.match(/@(\S*)$/);

  if (atMatch) {
    mentionStart = atMatch.index;
    const query = atMatch[1].toLowerCase();
    const matches = allUsers.filter(u =>
      u.nickname.toLowerCase().includes(query) && u.id !== currentUser.id
    );
    if (matches.length > 0) {
      mentionDropdown.innerHTML = matches.map(u =>
        `<div class="mention-option" data-nickname="${escHtml(u.nickname)}">${escHtml(u.nickname)}</div>`
      ).join('');
      mentionDropdown.classList.add('active');

      mentionDropdown.querySelectorAll('.mention-option').forEach(opt => {
        opt.addEventListener('click', () => {
          const before = val.substring(0, mentionStart);
          const after = val.substring(cursor);
          commentInput.value = before + '@' + opt.dataset.nickname + ' ' + after;
          mentionDropdown.classList.remove('active');
          commentInput.focus();
        });
      });
      return;
    }
  }
  mentionDropdown.classList.remove('active');
});

/* ── Utilities ──────────────────────────────────── */
function escHtml(str) {
  if (!str) return '';
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function parseTags(tagsStr) {
  if (!tagsStr) return [];
  try { return JSON.parse(tagsStr); } catch { return []; }
}

function renderDueDate(dateStr) {
  const due = new Date(dateStr);
  const now = new Date();
  now.setHours(0, 0, 0, 0);
  const diff = (due - now) / (1000 * 60 * 60 * 24);
  let cls = 'due-date';
  if (diff < 0) cls += ' overdue';
  else if (diff <= 2) cls += ' soon';
  const formatted = dateStr;
  return `<span class="${cls}">${formatted}</span>`;
}

function timeAgo(dateStr) {
  const date = new Date(dateStr);
  const now = new Date();
  const seconds = Math.floor((now - date) / 1000);
  if (seconds < 60) return 'just now';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

/* ── Claude Character ─────────────────────────── */
function initClaudeCharacter() {
  if (claudeWalkTimer) clearInterval(claudeWalkTimer);
  if (claudeLegTimer) clearInterval(claudeLegTimer);
  claudeHovered = false;

  const walkArea = document.getElementById('claudeWalkArea');
  const el = document.getElementById('claudeCharacter');
  if (!walkArea || !el) return;

  const charW = el.offsetWidth || 60;
  const maxLeft = walkArea.offsetWidth - charW;
  claudeLeftPx = Math.random() * Math.max(0, maxLeft);
  el.style.left = claudeLeftPx + 'px';
  updateClaudeEyes();

  claudeWalkTimer = setInterval(() => {
    if (claudeHovered) return;
    const area = document.getElementById('claudeWalkArea');
    const ch = document.getElementById('claudeCharacter');
    if (!area || !ch) return;
    const max = area.offsetWidth - (ch.offsetWidth || 60);
    const newLeft = Math.random() * Math.max(0, max);
    claudeDir = newLeft > claudeLeftPx ? 'right' : 'left';
    claudeLeftPx = newLeft;
    ch.classList.remove('claude-fast');
    ch.style.left = claudeLeftPx + 'px';
    updateClaudeEyes();
  }, 2000);

  claudeLegTimer = setInterval(() => {
    document.querySelectorAll('.claude-leg').forEach(leg => {
      if (Math.random() < 0.3) {
        leg.setAttribute('height', '13.5');
        setTimeout(() => leg.setAttribute('height', '15'), 200);
      }
    });
  }, 300);

  walkArea.addEventListener('mousemove', onClaudeMouseMove);
  walkArea.addEventListener('mouseleave', onClaudeMouseLeave);

  el.addEventListener('click', () => {
    const now = Date.now();
    claudeClickTimes.push(now);
    claudeClickTimes = claudeClickTimes.filter(t => now - t < 1000);
    if (claudeClickTimes.length >= 3) {
      claudeClickTimes = [];
      openTaskGenModal();
    }
  });
}

function updateClaudeEyes() {
  const eyeL = document.getElementById('claudeEyeL');
  const eyeR = document.getElementById('claudeEyeR');
  if (!eyeL || !eyeR) return;
  if (claudeDir === 'right') {
    eyeL.setAttribute('x', '42');
    eyeR.setAttribute('x', '76');
  } else {
    eyeL.setAttribute('x', '36');
    eyeR.setAttribute('x', '71');
  }
}

function onClaudeMouseMove(e) {
  const el = document.getElementById('claudeCharacter');
  const walkArea = document.getElementById('claudeWalkArea');
  if (!el || !walkArea) return;
  const r = el.getBoundingClientRect();
  const pad = 10;
  const over = e.clientX >= r.left - pad && e.clientX <= r.right + pad &&
               e.clientY >= r.top - pad && e.clientY <= r.bottom + pad;
  if (!over) {
    if (claudeHovered) {
      claudeHovered = false;
      setClaudeEmoji('');
      el.classList.remove('claude-tremble');
    }
    return;
  }
  if (!claudeHovered) {
    claudeHovered = true;
    setClaudeEmoji('😱');
  }
  const charW = el.offsetWidth || 60;
  const max = walkArea.offsetWidth - charW;
  const cx = r.left + r.width / 2;
  if (e.clientX <= cx) {
    claudeLeftPx = Math.min(max, claudeLeftPx + max * 0.4);
    claudeDir = 'right';
  } else {
    claudeLeftPx = Math.max(0, claudeLeftPx - max * 0.4);
    claudeDir = 'left';
  }
  if (claudeLeftPx <= 2 || claudeLeftPx >= max - 2) {
    el.classList.add('claude-tremble');
  } else {
    el.classList.remove('claude-tremble');
  }
  el.classList.add('claude-fast');
  el.style.left = claudeLeftPx + 'px';
  updateClaudeEyes();
}

function onClaudeMouseLeave() {
  claudeHovered = false;
  setClaudeEmoji('');
  const el = document.getElementById('claudeCharacter');
  if (el) el.classList.remove('claude-tremble');
}

function setClaudeEmoji(emoji) {
  const el = document.getElementById('claudeEmoji');
  if (!el) return;
  el.textContent = emoji;
  el.className = emoji ? 'claude-emoji visible' : 'claude-emoji';
}

function showClaudeHeart() {
  const heart = document.getElementById('claudeHeartPath');
  if (!heart) return;
  heart.classList.remove('show');
  heart.style.opacity = '0';
  void heart.offsetWidth;
  heart.classList.add('show');
  setTimeout(() => {
    heart.classList.remove('show');
    heart.style.opacity = '0';
  }, 1500);
}

/* ── Task Generator (Easter Egg) ──────────────── */

const DEFAULT_TASK_GEN_PROMPT = `당신은 프로젝트 매니저 어시스턴트입니다. 사용자가 입력한 목표/과업을 팀원들이 바로 착수할 수 있는 작은 단위의 일감으로 분해해주세요.

규칙:
1. 반드시 아래 JSON 형식으로만 응답하세요. 다른 텍스트나 마크다운을 포함하지 마세요.
2. 각 일감은 독립적으로 수행 가능한 단위여야 합니다.
3. 제목은 구체적이고 행동 중심(동사로 시작)으로 작성하세요.
4. 설명은 1-2문장으로 무엇을 해야 하는지, 왜 필요한지 간결하게 적으세요.
5. 우선순위는 HIGH, MEDIUM, LOW 중 하나를 선택하세요.
6. 일감 수는 목표 규모에 맞게 5~15개 사이로 생성하세요.

응답 형식:
[{"title": "일감 제목", "description": "일감 설명", "priority": "MEDIUM"}, ...]`;

function openTaskGenModal() {
  const modal = document.getElementById('taskGenModal');
  const sysPromptEl = document.getElementById('taskGenSysPrompt');
  if (sysPromptEl && !sysPromptEl.value) {
    sysPromptEl.value = DEFAULT_TASK_GEN_PROMPT;
  }
  modal.classList.add('active');
  document.getElementById('taskGenGoal').focus();
}

function closeTaskGenModal() {
  document.getElementById('taskGenModal').classList.remove('active');
}

function renderTaskGenItems() {
  const list = document.getElementById('taskGenList');
  const priorityColors = { HIGH: 'var(--high)', MEDIUM: 'var(--medium)', LOW: 'var(--low)' };
  const priorityBgs = { HIGH: 'rgba(239,68,68,0.15)', MEDIUM: 'rgba(245,158,11,0.15)', LOW: 'rgba(107,114,128,0.15)' };

  list.innerHTML = taskGenItems.map((item, i) => `
    <div class="task-gen-item ${item.checked ? '' : 'unchecked'}" data-idx="${i}">
      <div class="task-gen-item-header">
        <input type="checkbox" ${item.checked ? 'checked' : ''} data-gen-check="${i}">
        <div class="task-gen-item-body">
          <input type="text" class="task-gen-item-title" value="${escHtml(item.title)}" data-gen-title="${i}">
          <textarea class="task-gen-item-desc" rows="1" data-gen-desc="${i}">${escHtml(item.description || '')}</textarea>
          <span class="task-gen-item-priority" style="color:${priorityColors[item.priority] || priorityColors.MEDIUM};background:${priorityBgs[item.priority] || priorityBgs.MEDIUM}">${item.priority || 'MEDIUM'}</span>
        </div>
      </div>
    </div>
  `).join('');

  list.querySelectorAll('[data-gen-check]').forEach(cb => {
    cb.addEventListener('change', e => {
      const idx = parseInt(e.target.dataset.genCheck);
      taskGenItems[idx].checked = e.target.checked;
      e.target.closest('.task-gen-item').classList.toggle('unchecked', !e.target.checked);
      updateTaskGenCounts();
    });
  });

  list.querySelectorAll('[data-gen-title]').forEach(el => {
    el.addEventListener('input', e => {
      taskGenItems[parseInt(e.target.dataset.genTitle)].title = e.target.value;
    });
  });

  list.querySelectorAll('[data-gen-desc]').forEach(el => {
    el.addEventListener('input', e => {
      taskGenItems[parseInt(e.target.dataset.genDesc)].description = e.target.value;
      e.target.style.height = 'auto';
      e.target.style.height = e.target.scrollHeight + 'px';
    });
    el.style.height = 'auto';
    el.style.height = el.scrollHeight + 'px';
  });

  updateTaskGenCounts();
}

function updateTaskGenCounts() {
  const checked = taskGenItems.filter(i => i.checked).length;
  const total = taskGenItems.length;
  document.getElementById('taskGenSelectedCount').textContent = checked;
  document.getElementById('taskGenSelectAll').checked = checked === total;
  const createBtn = document.getElementById('taskGenCreateBtn');
  createBtn.textContent = `Create Selected (${checked})`;
  createBtn.disabled = checked === 0;
}

document.getElementById('taskGenCloseBtn').addEventListener('click', closeTaskGenModal);

document.getElementById('taskGenSysPromptToggle').addEventListener('click', () => {
  const section = document.getElementById('taskGenSysPromptSection');
  const icon = document.getElementById('taskGenSysPromptIcon');
  const visible = section.style.display !== 'none';
  section.style.display = visible ? 'none' : 'block';
  icon.innerHTML = visible ? '&#9660;' : '&#9650;';
});

document.getElementById('taskGenSelectAll').addEventListener('change', e => {
  const checked = e.target.checked;
  taskGenItems.forEach(item => item.checked = checked);
  renderTaskGenItems();
});

document.getElementById('taskGenRunBtn').addEventListener('click', async () => {
  const goal = document.getElementById('taskGenGoal').value.trim();
  if (!goal) return;

  const sysPrompt = document.getElementById('taskGenSysPrompt').value.trim();
  const loading = document.getElementById('taskGenLoading');
  const runBtn = document.getElementById('taskGenRunBtn');
  const resultEmpty = document.getElementById('taskGenResultEmpty');
  const resultArea = document.getElementById('taskGenResultArea');

  loading.style.display = 'block';
  runBtn.disabled = true;

  try {
    const res = await api('/api/tasks/generate', {
      method: 'POST',
      body: JSON.stringify({
        goal,
        system_prompt: sysPrompt || null,
      }),
    });
    taskGenItems = (res.items || []).map(item => ({ ...item, checked: true }));
    resultEmpty.style.display = 'none';
    resultArea.style.display = 'block';
    document.getElementById('taskGenRefreshBtn').style.display = '';
    document.getElementById('taskGenCreateBtn').style.display = '';
    renderTaskGenItems();
  } catch (err) {
    alert('일감 생성 실패: ' + (err.message || err));
  } finally {
    loading.style.display = 'none';
    runBtn.disabled = false;
  }
});

document.getElementById('taskGenRefreshBtn').addEventListener('click', async () => {
  const unchecked = taskGenItems.filter(i => !i.checked);
  if (unchecked.length === 0) {
    alert('재생성할 항목이 없습니다. 체크 해제된 항목만 재생성됩니다.');
    return;
  }

  const goal = document.getElementById('taskGenGoal').value.trim();
  const sysPrompt = document.getElementById('taskGenSysPrompt').value.trim();
  const loading = document.getElementById('taskGenLoading');
  const refreshBtn = document.getElementById('taskGenRefreshBtn');

  loading.style.display = 'block';
  refreshBtn.disabled = true;

  try {
    const res = await api('/api/tasks/generate', {
      method: 'POST',
      body: JSON.stringify({
        goal,
        system_prompt: sysPrompt || null,
        reject_items: unchecked.map(i => ({ title: i.title, description: i.description })),
      }),
    });
    const kept = taskGenItems.filter(i => i.checked);
    const newItems = (res.items || []).map(item => ({ ...item, checked: true }));
    taskGenItems = [...kept, ...newItems];
    renderTaskGenItems();
  } catch (err) {
    alert('재생성 실패: ' + (err.message || err));
  } finally {
    loading.style.display = 'none';
    refreshBtn.disabled = false;
  }
});

document.getElementById('taskGenCreateBtn').addEventListener('click', async () => {
  const selected = taskGenItems.filter(i => i.checked);
  if (selected.length === 0) return;

  const createBtn = document.getElementById('taskGenCreateBtn');
  createBtn.disabled = true;
  createBtn.textContent = 'Creating...';

  let created = 0;
  for (const item of selected) {
    try {
      await api('/api/tasks', {
        method: 'POST',
        body: JSON.stringify({
          title: item.title,
          description: item.description || '',
          priority: item.priority || 'MEDIUM',
          status: 'TODO',
        }),
      });
      created++;
    } catch (err) {
      console.error('Failed to create task:', item.title, err);
    }
  }

  taskGenItems = taskGenItems.filter(i => !i.checked);
  if (taskGenItems.length === 0) {
    document.getElementById('taskGenResultArea').style.display = 'none';
    document.getElementById('taskGenResultEmpty').style.display = 'block';
    document.getElementById('taskGenRefreshBtn').style.display = 'none';
    document.getElementById('taskGenCreateBtn').style.display = 'none';
  } else {
    renderTaskGenItems();
  }

  createBtn.disabled = false;
  updateTaskGenCounts();

  await loadTasks();
  renderBoard();

  alert(`${created}개의 태스크가 생성되었습니다.`);
});

/* ── Archive ───────────────────────────────────── */
async function refreshArchivedCount() {
  try {
    const data = await api('/api/tasks/archived/count');
    archivedCount = data.count;
    const el = document.getElementById('archiveCount');
    if (el) el.textContent = archivedCount;
  } catch {}
}

function openArchiveModal() {
  const modal = document.getElementById('archiveModal');
  modal.classList.add('active');
  // Populate assignee filter
  const sel = document.getElementById('archiveAssignee');
  sel.innerHTML = '<option value="">All assignees</option>' +
    allUsers.map(u => `<option value="${u.id}">${escHtml(u.nickname)}</option>`).join('');
  // Reset filters
  document.getElementById('archiveKeyword').value = '';
  document.getElementById('archiveDateFrom').value = '';
  document.getElementById('archiveDateTo').value = '';
  document.querySelectorAll('.archive-date-btn').forEach(b => b.classList.remove('active'));
  searchArchivedTasks();
}

document.getElementById('closeArchiveBtn').addEventListener('click', () => {
  document.getElementById('archiveModal').classList.remove('active');
});

async function searchArchivedTasks() {
  const keyword = document.getElementById('archiveKeyword').value.trim();
  const assigneeId = document.getElementById('archiveAssignee').value;
  const dateFrom = document.getElementById('archiveDateFrom').value;
  const dateTo = document.getElementById('archiveDateTo').value;

  let url = '/api/tasks/archived/search?';
  const params = [];
  if (keyword) params.push(`keyword=${encodeURIComponent(keyword)}`);
  if (assigneeId) params.push(`assignee_id=${assigneeId}`);
  if (dateFrom) params.push(`date_from=${dateFrom}`);
  if (dateTo) params.push(`date_to=${dateTo}`);
  url += params.join('&');

  try {
    const archived = await api(url);
    renderArchiveList(archived);
  } catch (err) {
    document.getElementById('archiveList').innerHTML =
      `<div class="archive-empty">Error: ${escHtml(err.message)}</div>`;
  }
}

function renderArchiveList(archived) {
  const list = document.getElementById('archiveList');
  if (!archived.length) {
    list.innerHTML = '<div class="archive-empty">No archived tasks found</div>';
    return;
  }
  list.innerHTML = archived.map(t => {
    const assignee = t.assignee_user ? t.assignee_user.nickname : '';
    const created = new Date(t.created_at).toLocaleDateString('ko-KR');
    const tags = parseTags(t.tags);
    return `
      <div class="archive-item" data-id="${t.id}">
        <div class="archive-item-main">
          <div class="archive-item-title">
            <span class="priority-badge priority-${t.priority}">${t.priority}</span>
            ${escHtml(t.title)}
          </div>
          <div class="archive-item-meta">
            <span class="archive-item-status">${t.status.replace(/_/g, ' ')}</span>
            ${assignee ? `<span class="assignee-badge">${escHtml(assignee)}</span>` : ''}
            <span style="color:var(--text-muted)">${created}</span>
            ${tags.map(tag => `<span class="tag-badge" style="background:${tagColor(tag)}22;color:${tagColor(tag)}">${escHtml(tag)}</span>`).join('')}
          </div>
        </div>
        <button class="btn btn-sm btn-secondary archive-restore-btn" data-id="${t.id}" title="Restore to board">Restore</button>
      </div>
    `;
  }).join('');

  list.querySelectorAll('.archive-restore-btn').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const taskId = btn.dataset.id;
      try {
        await api(`/api/tasks/${taskId}/unarchive`, { method: 'POST' });
        await loadTasks();
        await refreshArchivedCount();
        renderBoard();
        searchArchivedTasks();
      } catch (err) {
        alert('Restore error: ' + err.message);
      }
    });
  });
}

// Archive filter event listeners
let archiveSearchTimer = null;
document.getElementById('archiveKeyword').addEventListener('input', () => {
  clearTimeout(archiveSearchTimer);
  archiveSearchTimer = setTimeout(searchArchivedTasks, 300);
});
document.getElementById('archiveAssignee').addEventListener('change', searchArchivedTasks);
document.getElementById('archiveDateFrom').addEventListener('change', searchArchivedTasks);
document.getElementById('archiveDateTo').addEventListener('change', searchArchivedTasks);

document.querySelectorAll('.archive-date-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.archive-date-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const days = parseInt(btn.dataset.days);
    if (days === 0) {
      document.getElementById('archiveDateFrom').value = '';
      document.getElementById('archiveDateTo').value = '';
    } else {
      const to = new Date();
      const from = new Date();
      from.setDate(from.getDate() - days);
      document.getElementById('archiveDateFrom').value = from.toISOString().slice(0, 10);
      document.getElementById('archiveDateTo').value = to.toISOString().slice(0, 10);
    }
    searchArchivedTasks();
  });
});

/* ── Weekly Report ─────────────────────────────── */
const DEFAULT_SYSTEM_PROMPT = `당신은 UX디자인팀의 주간보고서를 작성하는 어시스턴트입니다.

규칙:
1. 마크다운 문법(#, *, **, \`\`\`, | 등)을 절대 사용하지 마세요. 일반 텍스트로만 작성하세요.
2. 예시 보고서는 형식과 구조만 참고하세요. 예시의 내용(텍스트)을 그대로 복사하거나 포함하지 마세요.
3. 오직 태스크 변동사항(description, 상태 변화, 댓글)을 근거로 새로운 내용을 작성하세요.
4. 한국어 경어체로 작성하세요.
5. 각 태스크의 description과 댓글을 활용하여 구체적으로 무엇을 완료/진행했는지 서술하세요.
6. DONE으로 변경된 항목은 description과 관련 댓글 기반으로 완료 내용을 요약하세요.
7. TODO/BACKLOG 항목은 '다음 주 계획'에 반영하세요.
8. field가 'comment'인 변동사항은 해당 태스크에 대한 팀원의 논의/결정/진행 내역입니다. 변경 관리 기록으로 취급하고 주요 내용을 보고서에 반영하세요.`;

document.getElementById('reportBtn').addEventListener('click', () => {
  document.getElementById('reportModal').classList.add('active');
  document.getElementById('reportResultGroup').style.display = 'none';
  document.getElementById('changesPreviewGroup').style.display = 'none';
  document.getElementById('reportLoading').style.display = 'none';
  // Set default system prompt if empty
  const sysPromptEl = document.getElementById('systemPrompt');
  if (!sysPromptEl.value.trim()) {
    sysPromptEl.value = DEFAULT_SYSTEM_PROMPT;
  }
  checkLlmStatus();
  loadChangesPreview();
});

/* System Prompt toggle */
document.getElementById('systemPromptToggle').addEventListener('click', () => {
  const section = document.getElementById('systemPromptSection');
  const icon = document.getElementById('systemPromptToggleIcon');
  if (section.style.display === 'none') {
    section.style.display = 'block';
    icon.innerHTML = '&#9650;';
  } else {
    section.style.display = 'none';
    icon.innerHTML = '&#9660;';
  }
});

async function checkLlmStatus() {
  const banner = document.getElementById('llmStatusBanner');
  banner.style.display = 'block';
  banner.style.background = '#f3f4f6';
  banner.style.color = '#6b7280';
  banner.textContent = 'LLM API 연결 상태 확인 중...';

  try {
    const res = await api('/api/reports/llm-status');
    if (res.reachable) {
      banner.style.background = '#ecfdf5';
      banner.style.color = '#059669';
      banner.textContent = 'LLM API 연결 성공';
      setTimeout(() => { banner.style.display = 'none'; }, 3000);
    } else {
      banner.style.background = '#fef2f2';
      banner.style.color = '#dc2626';
      banner.textContent = 'LLM API 연결 실패: ' + (res.error || 'Unknown error');
    }
  } catch (e) {
    banner.style.background = '#fef2f2';
    banner.style.color = '#dc2626';
    banner.textContent = 'LLM 상태 확인 실패: ' + e.message;
  }
}

document.getElementById('closeReportBtn').addEventListener('click', () => {
  document.getElementById('reportModal').classList.remove('active');
});

// Intentionally no overlay-click close for the report modal —
// the Close button is the only way to dismiss it so users
// don't lose their system prompt / template input.

async function loadChangesPreview() {
  const days = document.getElementById('reportDays').value;
  try {
    const histories = await api(`/api/reports/history?days=${days}`);
    const group = document.getElementById('changesPreviewGroup');
    const preview = document.getElementById('changesPreview');
    document.getElementById('changesCount').textContent = histories.length;

    if (histories.length === 0) {
      preview.innerHTML = '<div style="color:var(--text-muted)">No changes in this period</div>';
    } else {
      preview.innerHTML = histories.map(h => {
        const fieldLabel = {
          created: 'Created', deleted: 'Deleted', status: 'Status',
          title: 'Title', priority: 'Priority', assignee_id: 'Assignee',
          description: 'Description', due_date: 'Due Date', tags: 'Tags',
          comment: 'Comment',
        }[h.field_name] || h.field_name;

        let detail = '';
        if (h.field_name === 'created') {
          detail = `→ ${h.new_value}`;
        } else if (h.field_name === 'deleted') {
          detail = '(deleted)';
        } else if (h.field_name === 'comment') {
          detail = h.new_value || '';
        } else {
          detail = `${h.old_value || '(empty)'} → ${h.new_value || '(empty)'}`;
        }

        return `<div class="change-item">
          <span class="change-date">${h.created_at.substring(0, 16).replace('T', ' ')}</span>
          <strong>${escHtml(h.task_title)}</strong>
          — <span class="change-field">${fieldLabel}</span>: ${escHtml(detail)}
        </div>`;
      }).join('');
    }
    group.style.display = 'block';
  } catch (e) {
    console.error('Failed to load changes:', e);
  }
}

document.getElementById('reportDays').addEventListener('change', loadChangesPreview);

document.getElementById('clearHistoryBtn').addEventListener('click', async () => {
  if (!confirm('모든 태스크 변동 히스토리를 삭제하시겠습니까?\n(태스크 자체는 유지됩니다)')) return;
  try {
    await api('/api/reports/history', { method: 'DELETE' });
    loadChangesPreview();
  } catch (e) {
    alert('Error: ' + e.message);
  }
});

document.getElementById('saveTemplateBtn').addEventListener('click', async () => {
  const content = document.getElementById('reportTemplate').value.trim();
  if (!content) return alert('Please enter an example report.');
  const systemPrompt = document.getElementById('systemPrompt').value.trim() || null;
  try {
    await api('/api/reports/templates', {
      method: 'POST',
      body: JSON.stringify({ name: 'default', content, system_prompt: systemPrompt }),
    });
    alert('Template saved!');
  } catch (e) {
    alert('Error: ' + e.message);
  }
});

document.getElementById('loadTemplateBtn').addEventListener('click', async () => {
  try {
    const templates = await api('/api/reports/templates');
    if (templates.length > 0) {
      document.getElementById('reportTemplate').value = templates[0].content;
      document.getElementById('systemPrompt').value = templates[0].system_prompt || '';
    } else {
      alert('No saved templates.');
    }
  } catch (e) {
    alert('Error: ' + e.message);
  }
});

document.getElementById('generateReportBtn').addEventListener('click', async () => {
  const template = document.getElementById('reportTemplate').value.trim();
  if (!template) return alert('Please enter or load an example report template first.');

  const days = document.getElementById('reportDays').value;
  const loading = document.getElementById('reportLoading');
  const resultGroup = document.getElementById('reportResultGroup');
  const generateBtn = document.getElementById('generateReportBtn');

  // Save template automatically (including system prompt)
  const sysPrompt = document.getElementById('systemPrompt').value.trim() || null;
  try {
    await api('/api/reports/templates', {
      method: 'POST',
      body: JSON.stringify({ name: 'default', content: template, system_prompt: sysPrompt }),
    });
  } catch {}

  loading.style.display = 'block';
  resultGroup.style.display = 'none';
  generateBtn.disabled = true;

  try {
    const result = await api(`/api/reports/generate?days=${days}`, { method: 'POST' });
    document.getElementById('reportResult').textContent = result.report;
    resultGroup.style.display = 'block';
  } catch (e) {
    alert('Error: ' + e.message);
  } finally {
    loading.style.display = 'none';
    generateBtn.disabled = false;
  }
});

async function copyTextToClipboard(text) {
  // Modern clipboard API (requires HTTPS or localhost + page focus).
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (err) {
      console.warn('clipboard.writeText failed, falling back:', err);
    }
  }
  // Fallback: hidden textarea + execCommand. Works on plain HTTP.
  try {
    const ta = document.createElement('textarea');
    ta.value = text;
    // Keep it inside the viewport so iOS will copy, but invisible.
    ta.setAttribute('readonly', '');
    ta.style.position = 'fixed';
    ta.style.top = '0';
    ta.style.left = '0';
    ta.style.width = '1px';
    ta.style.height = '1px';
    ta.style.padding = '0';
    ta.style.border = 'none';
    ta.style.outline = 'none';
    ta.style.boxShadow = 'none';
    ta.style.background = 'transparent';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    ta.setSelectionRange(0, ta.value.length);
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);
    return ok;
  } catch (err) {
    console.error('execCommand copy failed:', err);
    return false;
  }
}

document.getElementById('copyReportBtn').addEventListener('click', async () => {
  const btn = document.getElementById('copyReportBtn');
  const text = document.getElementById('reportResult').textContent;
  if (!text) return;
  const ok = await copyTextToClipboard(text);
  if (ok) {
    btn.textContent = 'Copied!';
    setTimeout(() => { btn.textContent = 'Copy to Clipboard'; }, 2000);
  } else {
    btn.textContent = 'Copy failed';
    alert('클립보드 복사에 실패했습니다. 브라우저 권한을 확인하거나 수동으로 선택해 복사하세요.');
    setTimeout(() => { btn.textContent = 'Copy to Clipboard'; }, 2000);
  }
});

/* ── Help Modal ────────────────────────────────── */
document.getElementById('helpBtn').addEventListener('click', async () => {
  const modal = document.getElementById('helpModal');
  const content = document.getElementById('helpContent');
  modal.classList.add('active');
  content.innerHTML = '<div style="text-align:center;color:var(--text-muted);padding:20px">Loading...</div>';
  try {
    const res = await fetch('/api/help');
    const md = await res.text();
    content.innerHTML = renderMarkdown(md);
  } catch (e) {
    content.innerHTML = '<div style="color:var(--danger)">Failed to load help: ' + escHtml(e.message) + '</div>';
  }
});

document.getElementById('closeHelpBtn').addEventListener('click', () => {
  document.getElementById('helpModal').classList.remove('active');
});
// Help modal is read-only, but we keep the same rule for consistency:
// only the Close button dismisses it.

document.getElementById('restartOnboardingBtn').addEventListener('click', async () => {
  const btn = document.getElementById('restartOnboardingBtn');
  btn.disabled = true;
  const original = btn.textContent;
  btn.textContent = '...';
  try {
    document.getElementById('helpModal').classList.remove('active');
    await Onboarding.restart();
  } finally {
    btn.disabled = false;
    btn.textContent = original;
  }
});

function renderMarkdown(md) {
  const lines = md.split('\n');
  let html = '';
  let inCodeBlock = false;
  let codeBuffer = [];
  let inList = false;
  let listType = '';

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    // Code block
    if (line.startsWith('```')) {
      if (inCodeBlock) {
        html += '<pre><code>' + escHtml(codeBuffer.join('\n')) + '</code></pre>';
        codeBuffer = [];
        inCodeBlock = false;
      } else {
        if (inList) { html += listType === 'ul' ? '</ul>' : '</ol>'; inList = false; }
        inCodeBlock = true;
      }
      continue;
    }
    if (inCodeBlock) {
      codeBuffer.push(line);
      continue;
    }

    // Close list if non-list line
    if (inList && !line.match(/^(\s*[-*]|\s*\d+\.)\s/)) {
      html += listType === 'ul' ? '</ul>' : '</ol>';
      inList = false;
    }

    // Horizontal rule
    if (line.match(/^---+$/)) {
      html += '<hr>';
      continue;
    }

    // Headings
    const hMatch = line.match(/^(#{1,4})\s+(.*)/);
    if (hMatch) {
      const level = hMatch[1].length;
      html += `<h${level}>${inlineFormat(hMatch[2])}</h${level}>`;
      continue;
    }

    // Unordered list
    const ulMatch = line.match(/^(\s*)[-*]\s+(.*)/);
    if (ulMatch) {
      if (!inList || listType !== 'ul') {
        if (inList) html += listType === 'ul' ? '</ul>' : '</ol>';
        html += '<ul>';
        inList = true;
        listType = 'ul';
      }
      html += `<li>${inlineFormat(ulMatch[2])}</li>`;
      continue;
    }

    // Ordered list
    const olMatch = line.match(/^\s*\d+\.\s+(.*)/);
    if (olMatch) {
      if (!inList || listType !== 'ol') {
        if (inList) html += listType === 'ul' ? '</ul>' : '</ol>';
        html += '<ol>';
        inList = true;
        listType = 'ol';
      }
      html += `<li>${inlineFormat(olMatch[1])}</li>`;
      continue;
    }

    // Empty line
    if (line.trim() === '') {
      continue;
    }

    // Paragraph
    html += `<p>${inlineFormat(line)}</p>`;
  }

  if (inList) html += listType === 'ul' ? '</ul>' : '</ol>';
  if (inCodeBlock) html += '<pre><code>' + escHtml(codeBuffer.join('\n')) + '</code></pre>';
  return html;
}

function inlineFormat(text) {
  // Bold
  text = text.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  // Inline code
  text = text.replace(/`([^`]+)`/g, '<code>$1</code>');
  return text;
}

/* ── Close panels on outside click ──────────────── */
document.addEventListener('click', e => {
  const bell = document.getElementById('notifBell');
  const panel = document.getElementById('notifPanel');
  if (notifPanelOpen && !bell.contains(e.target) && !panel.contains(e.target)) {
    notifPanelOpen = false;
    panel.classList.remove('active');
  }
});

/* ── Onboarding ─────────────────────────────────── */
const Onboarding = (() => {
  let stepIndex = 0;
  let active = false;
  let resizeHandler = null;
  let scrollHandler = null;
  let currentTargetGetter = null;

  // Step keys are used to map onboarding task cards → the step where the
  // user can resume after closing the tour mid-way.
  const STEP_WELCOME = 'welcome';
  const STEP_COLUMNS = 'columns';
  const STEP_ADD_TASK = 'add_task';
  const STEP_NOTIF = 'notif';
  const STEP_ARCHIVE = 'archive';
  const STEP_WEEKLY = 'weekly';
  const STEP_QUIZ = 'quiz';
  const STEP_FAREWELL = 'farewell';

  // Mapping: onboarding task title → the step key that introduces that topic.
  const TITLE_TO_STEP = {
    '일감 생성하기': STEP_COLUMNS,
    '일감 아카이브 해보기': STEP_ARCHIVE,
    'AI에게 주간보고 요청하기': STEP_WEEKLY,
    'Task Generator 사용하기 (퀴즈)': STEP_QUIZ,
  };

  // Step definitions.
  const steps = [
    {
      key: STEP_WELCOME,
      title: '환영합니다 👋  Task Manager 둘러보기',
      body:
        '안녕하세요. Task 관리와 주간보고를 동시에 쓸 수 있는 Task Manager에 오신걸 환영합니다.\n\n' +
        '시스템 온보딩을 위해 왼쪽 TODO 컬럼에 미리 만들어 둔 4개의 일감을 함께 살펴볼게요. ' +
        '언제든지 "닫기"로 종료할 수 있어요.',
      target: null,
    },
    {
      key: STEP_COLUMNS,
      title: '드래그로 옮기는 5단계 칸반 보드',
      body:
        '이 화면이 칸반 보드입니다.\n' +
        '• TODO — 아직 시작 안 한 일\n' +
        '• IN PROGRESS — 진행 중\n' +
        '• REVIEW — 검토 대기\n' +
        '• DONE — 완료\n' +
        '• ARCHIVE — 보드에서 치워둔 일\n\n' +
        '카드를 드래그해서 컬럼 사이를 이동할 수 있어요.',
      target: () => document.querySelector('#board .column'),
    },
    {
      key: STEP_ADD_TASK,
      title: '＋ Add Task — 풍성한 일감 생성',
      body:
        '컬럼 하단의 "+ Add Task" 버튼으로 새 일감을 만들 수 있습니다.\n' +
        '제목, 우선순위, 담당자, 마감일, 태그, 커버 이미지까지 자유롭게 채울 수 있어요.',
      target: () => document.querySelector('.add-task-btn'),
    },
    {
      key: STEP_NOTIF,
      title: '@멘션 → 🔔 실시간 알림',
      body:
        '댓글에서 @닉네임으로 팀원을 멘션하면 우측 상단의 🔔로 알림이 전달됩니다.\n' +
        '개인 일감 관리부터 팀 협업까지 모두 한 화면에서 처리할 수 있어요.',
      target: () => document.getElementById('notifBell'),
    },
    {
      key: STEP_ARCHIVE,
      title: 'ARCHIVE 컬럼 & Browse Archived',
      body:
        '완료된 일감은 ARCHIVE로 옮겨 보드를 깔끔하게 유지하세요.\n\n' +
        '카드를 우측 ARCHIVE 영역으로 드래그하거나, 일감을 열고 "Archive" 버튼을 누르면 됩니다.\n' +
        '보관된 일감은 "Browse Archived"에서 언제든 다시 볼 수 있어요.',
      target: () => document.querySelector('.archive-body'),
    },
    {
      key: STEP_WEEKLY,
      title: '✨ AI 주간보고서 자동 생성',
      body:
        '상단 "Weekly Report" 버튼을 누르면 LLM이 한 주 동안의 일감 변동, 댓글, 상태 변화를 종합해 ' +
        '주간보고서를 자동으로 작성해 줍니다.\n\n' +
        '• System Prompt 로 보고서 톤·규칙을 지정\n' +
        '• Example Report Template 에 우리 팀 보고서 한 편을 붙여두면 그 형식을 Few-shot으로 따라합니다.',
      target: () => document.getElementById('reportBtn'),
    },
    {
      key: STEP_QUIZ,
      title: '🎁 숨겨진 Task Generator — 깜짝 퀴즈',
      body:
        'Task Generator는 큰 목표를 LLM이 잘게 나눠 여러 일감으로 만들어주는 이스터에그예요.\n' +
        '아래 셋 중 진짜 여는 방법은 무엇일까요?',
      target: null,
      quiz: {
        options: [
          { label: '1) Claude Code 캐릭터 위에 마우스를 3초 동안 호버한다',  correct: false },
          { label: '2) Task 생성 버튼을 더블클릭 한다',                      correct: false },
          { label: '3) Claude Code 캐릭터를 빠르게 세 번 클릭한다',          correct: true  },
        ],
        // Shown regardless of right/wrong — the user might guess right
        // without knowing why, so we always reveal the actual mechanism and
        // spotlight the character so they can try it immediately.
        praise:
          '정답입니다 🎉 ARCHIVE 컬럼 안의 Claude Code 외계인 친구를 1초 안에 ' +
          '3번 따다닥 클릭하면 Task Generator가 열립니다. 지금 한 번 시도해보세요!',
        reveal:
          '정답은 3번이에요. ARCHIVE 컬럼 안의 Claude Code 외계인 친구를 ' +
          '1초 안에 3번 따다닥 클릭하면 Task Generator가 열립니다 👽',
      },
    },
    {
      key: STEP_FAREWELL,
      title: '🚀 이제 준비 완료!',
      body:
        '온보딩은 여기까지에요.\n\n' +
        '왼쪽 TODO에 남은 온보딩 일감을 다시 클릭하면 해당 단계부터 이어서 볼 수 있고, ' +
        '처음부터 다시 보고 싶으면 우측 상단 ? 버튼의 "온보딩 다시 보기"를 누르세요.\n\n' +
        '아래 "확인"을 누르면 온보딩이 종료됩니다.',
      target: null,
      finalLabel: '확인',
    },
  ];

  function stepIndexByKey(key) {
    return steps.findIndex(s => s.key === key);
  }

  function hasOnboardingTask() {
    return tasks.some(t => {
      try {
        return parseTags(t.tags).includes('onboarding');
      } catch {
        return false;
      }
    });
  }

  function shouldAutoStart() {
    if (!currentUser || !currentWorkspace) return false;
    if (currentUser.onboarded_at) return false;
    const flag = `taskmanager_onboarded_${currentUser.id}`;
    if (localStorage.getItem(flag) === '1') return false;
    return hasOnboardingTask();
  }

  function start(initialStep = 0) {
    stepIndex = Math.max(0, Math.min(initialStep, steps.length - 1));
    if (active) {
      // Already showing → just jump to the requested step
      render();
      return;
    }
    active = true;
    document.getElementById('onboardingRoot').style.display = '';
    bindHandlers();
    render();
  }

  function startAtKey(key) {
    const idx = stepIndexByKey(key);
    if (idx >= 0) start(idx);
  }

  /**
   * Close the tour.
   *  - If the user is not yet on the farewell step, jump to it so they always
   *    see the "다시 볼 수 있어요" reminder one last time.
   *  - If they are already on the farewell step (or we're called from there),
   *    persist and hide everything.
   */
  async function finish() {
    if (!active) return;
    if (stepIndex !== steps.length - 1) {
      stepIndex = steps.length - 1;
      render();
      return;
    }
    active = false;
    document.getElementById('onboardingRoot').style.display = 'none';
    unbindHandlers();
    if (currentUser) {
      localStorage.setItem(`taskmanager_onboarded_${currentUser.id}`, '1');
      try {
        const updated = await api(`/api/users/${currentUser.id}/complete-onboarding`, {
          method: 'POST',
        });
        currentUser = { ...currentUser, ...updated };
        localStorage.setItem('taskmanager_user', JSON.stringify(currentUser));
      } catch (err) {
        console.warn('complete-onboarding failed:', err);
      }
    }
  }

  function next() {
    if (stepIndex >= steps.length - 1) {
      finish();
      return;
    }
    stepIndex += 1;
    render();
  }

  function bindHandlers() {
    resizeHandler = () => positionTarget();
    scrollHandler = () => positionTarget();
    window.addEventListener('resize', resizeHandler);
    window.addEventListener('scroll', scrollHandler, true);
  }
  function unbindHandlers() {
    if (resizeHandler) window.removeEventListener('resize', resizeHandler);
    if (scrollHandler) window.removeEventListener('scroll', scrollHandler, true);
    resizeHandler = scrollHandler = null;
    currentTargetGetter = null;
  }

  function getTargetEl() {
    if (!currentTargetGetter) return null;
    try {
      return currentTargetGetter();
    } catch {
      return null;
    }
  }

  function positionTarget() {
    const overlay = document.getElementById('onboardingOverlay');
    const pulse = document.getElementById('onboardingPulse');
    const arrow = document.getElementById('onboardingArrow');
    const arrowPath = document.getElementById('onboardingArrowPath');
    const mascotWrap = document.getElementById('onboardingMascotWrap');

    const el = getTargetEl();
    if (!el) {
      overlay.style.clipPath = '';
      overlay.style.background = 'rgba(8, 10, 16, 0.55)';
      pulse.style.display = 'none';
      arrow.style.display = 'none';
      return;
    }

    const r = el.getBoundingClientRect();
    const pad = 6;
    const x1 = Math.max(0, r.left - pad);
    const y1 = Math.max(0, r.top - pad);
    const x2 = Math.min(window.innerWidth, r.right + pad);
    const y2 = Math.min(window.innerHeight, r.bottom + pad);

    overlay.style.clipPath = `polygon(
      0 0, 100% 0, 100% 100%, 0 100%, 0 0,
      ${x1}px ${y1}px,
      ${x1}px ${y2}px,
      ${x2}px ${y2}px,
      ${x2}px ${y1}px,
      ${x1}px ${y1}px
    )`;
    overlay.style.background = 'rgba(8, 10, 16, 0.55)';

    pulse.style.display = '';
    pulse.style.left = `${x2 - 9}px`;
    pulse.style.top = `${y1 - 9}px`;

    const mascotRect = mascotWrap.getBoundingClientRect();
    const fromX = mascotRect.left + mascotRect.width / 2;
    const fromY = mascotRect.top - 8;
    const targetCenterY = (y1 + y2) / 2;
    const aimX = Math.max(x1, Math.min(fromX, x2));
    const aimY = fromY < y1 ? y2 : (fromY > y2 ? y1 : targetCenterY);
    const cx = (fromX + aimX) / 2;
    const cy = Math.min(fromY, aimY) - Math.min(180, Math.abs(fromX - aimX) * 0.4 + 60);

    arrow.style.display = '';
    arrowPath.setAttribute(
      'd',
      `M ${fromX} ${fromY} Q ${cx} ${cy} ${aimX} ${aimY}`
    );
  }

  function render() {
    const step = steps[stepIndex];
    currentTargetGetter = step.target;

    const titleEl = document.getElementById('onboardingBubbleTitle');
    const bodyEl = document.getElementById('onboardingBubbleBody');
    titleEl.textContent = step.title || '';
    bodyEl.textContent = step.body || '';

    const indicator = document.getElementById('onboardingStepIndicator');
    indicator.textContent = `${stepIndex + 1} / ${steps.length}`;

    const nextBtn = document.getElementById('onboardingNextBtn');
    const skipBtn = document.getElementById('onboardingSkipBtn');
    nextBtn.textContent = stepIndex === steps.length - 1
      ? (step.finalLabel || '확인')
      : '다음';
    nextBtn.style.display = '';
    // On the farewell step there's nothing to skip — hide "닫기" so the only
    // exit is "확인" after reading the reminder.
    skipBtn.style.display = stepIndex === steps.length - 1 ? 'none' : '';

    const quizEl = document.getElementById('onboardingQuiz');
    const quizOpts = document.getElementById('onboardingQuizOptions');
    const quizFb = document.getElementById('onboardingQuizFeedback');
    quizFb.style.display = 'none';
    quizFb.className = 'onboarding-quiz-feedback';
    quizOpts.innerHTML = '';

    if (step.quiz) {
      quizEl.style.display = '';
      nextBtn.disabled = true;
      nextBtn.style.opacity = '0.5';

      let answered = false;
      step.quiz.options.forEach((opt) => {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'onboarding-quiz-option';
        b.textContent = opt.label;
        b.addEventListener('click', () => {
          if (answered) return;
          if (opt.correct) {
            answered = true;
            b.classList.add('correct');
            quizOpts.querySelectorAll('button').forEach(o => { o.disabled = true; });
            quizFb.textContent = step.quiz.praise;
            quizFb.classList.add('is-correct');
            quizFb.style.display = '';
            // Spotlight the easter-egg location so the user knows where to try
            currentTargetGetter = () => document.getElementById('claudeCharacter');
            positionTarget();
            nextBtn.disabled = false;
            nextBtn.style.opacity = '';
          } else {
            // First wrong click reveals the answer in the feedback area AND
            // visually highlights the correct option. Further clicks do nothing.
            answered = true;
            b.classList.add('wrong');
            quizOpts.querySelectorAll('button').forEach((other, i) => {
              other.disabled = true;
              if (step.quiz.options[i].correct) {
                other.classList.add('correct');
              }
            });
            quizFb.textContent = step.quiz.reveal;
            quizFb.classList.add('is-wrong');
            quizFb.style.display = '';
            // Spotlight the easter-egg location so the user can spot it
            currentTargetGetter = () => document.getElementById('claudeCharacter');
            positionTarget();
            nextBtn.disabled = false;
            nextBtn.style.opacity = '';
          }
        });
        quizOpts.appendChild(b);
      });
    } else {
      quizEl.style.display = 'none';
      nextBtn.disabled = false;
      nextBtn.style.opacity = '';
    }

    requestAnimationFrame(positionTarget);
    setTimeout(positionTarget, 100);
  }

  function bindButtons() {
    document.getElementById('onboardingNextBtn').addEventListener('click', () => {
      if (active) next();
    });
    document.getElementById('onboardingSkipBtn').addEventListener('click', () => {
      if (active) finish();
    });
  }

  bindButtons();

  return {
    maybeStart() { if (shouldAutoStart()) start(0); },
    start,
    startAtKey,
    finish,
    isOnboardingTaskTitle(title) { return TITLE_TO_STEP.hasOwnProperty(title); },
    stepKeyForTaskTitle(title) { return TITLE_TO_STEP[title] || null; },
    async restart() {
      if (!currentWorkspace) return;
      try {
        await api(`/api/workspaces/${currentWorkspace.id}/reseed-onboarding`, {
          method: 'POST',
        });
        await loadTasks();
        renderBoard();
        start(0);
      } catch (err) {
        alert('온보딩 재시작 실패: ' + err.message);
      }
    },
  };
})();

// Hook into startApp lifecycle: after the board is rendered the first time,
// check whether to start onboarding for this user/workspace.
const _origStartApp = startApp;
startApp = async function patchedStartApp() {
  await _origStartApp.apply(this, arguments);
  try {
    Onboarding.maybeStart();
  } catch (err) {
    console.warn('Onboarding start failed:', err);
  }
};
