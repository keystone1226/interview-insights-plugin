/* ── State ──────────────────────────────────────── */
let currentUser = null;
let allUsers = [];
let columns = [];
let tasks = [];
let notifPanelOpen = false;

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
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...opts.headers },
    ...opts,
  });
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
    startApp();
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
    startApp();
  } catch (e) {
    alert('Error: ' + e.message);
  }
});

document.getElementById('nicknameInput').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') document.getElementById('nicknameSubmit').click();
});

/* ── Start App ──────────────────────────────────── */
async function startApp() {
  try {
    document.getElementById('currentUserName').textContent = currentUser.nickname;
    await Promise.all([loadColumns(), loadUsers()]);
    await loadTasks();
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

  // Card event listeners
  board.querySelectorAll('.task-card').forEach(card => {
    card.addEventListener('dragstart', e => {
      e.dataTransfer.setData('text/plain', card.dataset.id);
      card.classList.add('dragging');
    });
    card.addEventListener('dragend', () => card.classList.remove('dragging'));
    card.addEventListener('click', () => {
      const task = tasks.find(t => t.id === parseInt(card.dataset.id));
      if (task) openTaskModal(task);
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
  const commentsSection = document.getElementById('commentsSection');

  // Populate assignee dropdown
  const assigneeSelect = document.getElementById('taskAssignee');
  assigneeSelect.innerHTML = '<option value="">Unassigned</option>' +
    allUsers.map(u => `<option value="${u.id}">${escHtml(u.nickname)}</option>`).join('');

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
    commentsSection.style.display = 'block';
    loadComments(task.id);

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
    commentsSection.style.display = 'none';
    document.getElementById('imagePreview').style.display = 'none';
  }

  modal.classList.add('active');
  document.getElementById('taskTitle').focus();
}

function closeTaskModal() {
  document.getElementById('taskModal').classList.remove('active');
}

document.getElementById('cancelTaskBtn').addEventListener('click', closeTaskModal);
document.getElementById('taskModal').addEventListener('click', e => {
  if (e.target === e.currentTarget) closeTaskModal();
});

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
      await fetch(`/api/tasks/${savedTask.id}/image`, { method: 'POST', body: formData });
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

/* ── Weekly Report ─────────────────────────────── */
document.getElementById('reportBtn').addEventListener('click', () => {
  document.getElementById('reportModal').classList.add('active');
  document.getElementById('reportResultGroup').style.display = 'none';
  document.getElementById('changesPreviewGroup').style.display = 'none';
  document.getElementById('reportLoading').style.display = 'none';
  loadChangesPreview();
});

document.getElementById('closeReportBtn').addEventListener('click', () => {
  document.getElementById('reportModal').classList.remove('active');
});

document.getElementById('reportModal').addEventListener('click', e => {
  if (e.target === e.currentTarget) {
    document.getElementById('reportModal').classList.remove('active');
  }
});

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
        }[h.field_name] || h.field_name;

        let detail = '';
        if (h.field_name === 'created') {
          detail = `→ ${h.new_value}`;
        } else if (h.field_name === 'deleted') {
          detail = '(deleted)';
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

document.getElementById('saveTemplateBtn').addEventListener('click', async () => {
  const content = document.getElementById('reportTemplate').value.trim();
  if (!content) return alert('Please enter an example report.');
  try {
    await api('/api/reports/templates', {
      method: 'POST',
      body: JSON.stringify({ name: 'default', content }),
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

  // Save template automatically
  try {
    await api('/api/reports/templates', {
      method: 'POST',
      body: JSON.stringify({ name: 'default', content: template }),
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

document.getElementById('copyReportBtn').addEventListener('click', () => {
  const text = document.getElementById('reportResult').textContent;
  navigator.clipboard.writeText(text).then(() => {
    const btn = document.getElementById('copyReportBtn');
    btn.textContent = 'Copied!';
    setTimeout(() => { btn.textContent = 'Copy to Clipboard'; }, 2000);
  });
});

/* ── Close panels on outside click ──────────────── */
document.addEventListener('click', e => {
  const bell = document.getElementById('notifBell');
  const panel = document.getElementById('notifPanel');
  if (notifPanelOpen && !bell.contains(e.target) && !panel.contains(e.target)) {
    notifPanelOpen = false;
    panel.classList.remove('active');
  }
});
