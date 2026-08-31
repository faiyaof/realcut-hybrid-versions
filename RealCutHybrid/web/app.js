const state = {
  bootstrap: null,
  tasks: [],
  activeTab: 'queue',
  pathPicker: null,
  selectedTask: '',
  selectedLog: '',
  reportMode: false,
  drafts: [],
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[char]
));
const api = async (path, options = {}) => {
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
  const response = await fetch(path, { ...options, headers });
  let data = {};
  try { data = await response.json(); } catch {}
  if (!response.ok) throw new Error(data.error || `请求失败 (${response.status})`);
  return data;
};
const toast = (message) => {
  const node = $('#toast');
  node.textContent = message;
  node.classList.add('show');
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => node.classList.remove('show'), 2600);
};

const statusLabel = {
  queued: '排队中',
  pending: '待处理',
  running: '处理中',
  completed: '已完成',
  failed: '失败',
};
const statusClass = (status) => (
  ['queued', 'pending', 'running', 'completed', 'failed'].includes(status) ? status : 'queued'
);
const formatTime = (value) => value ? new Date(value).toLocaleString('zh-CN', {
  month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit',
}) : '—';
const fileIcon = (status) => status === 'failed' ? 'file-x-2' : status === 'completed' ? 'file-check-2' : 'file-video-2';

function setTab(tab) {
  state.activeTab = tab;
  $$('.nav-item').forEach((item) => item.classList.toggle('active', item.dataset.tab === tab));
  $$('.tab-panel').forEach((panel) => panel.classList.toggle('active', panel.id === `${tab}-tab`));
  const titles = { queue: '任务队列', details: '任务详情', logs: '运行日志', settings: '设置' };
  $('#page-title').textContent = titles[tab] || '任务队列';
  if (tab === 'details') {
    renderDetailSelect();
    if (state.selectedTask) loadDetail();
  }
  if (tab === 'logs') loadLog();
  window.lucide?.createIcons();
}

function renderEnvironment(environment = state.bootstrap?.environment) {
  const list = $('#environment-list');
  if (!list) return;
  if (!environment || !environment.checks?.length) {
    list.innerHTML = '<div class="env-row"><span class="env-name">尚未检查</span><small>点击重新检查</small></div>';
    return;
  }
  list.innerHTML = environment.checks.map((check) => `
    <div class="env-row">
      <i data-lucide="${check.ok ? 'check-circle-2' : 'circle-alert'}" class="${check.ok ? 'env-ok' : 'env-bad'}"></i>
      <span class="env-name">${esc(check.name)}</span>
      <small title="${esc(check.detail)}">${esc(check.detail)}</small>
    </div>
  `).join('');
  window.lucide?.createIcons();
}

function renderApiSettings(settings = state.bootstrap?.settings) {
  if (!settings) return;
  const providers = [
    ['deepseek_api_key', '#deepseek-key-status', '#deepseek-api-key'],
    ['dashscope_api_key', '#dashscope-key-status', '#dashscope-api-key'],
  ];
  providers.forEach(([key, statusSelector, inputSelector]) => {
    const status = settings[key] || {};
    const node = $(statusSelector);
    const input = $(inputSelector);
    if (node) {
      node.textContent = status.configured ? `已配置 · ${status.source}` : '未配置';
      node.classList.toggle('configured', status.configured === true);
    }
    if (input) input.placeholder = status.configured ? '留空则保持现有 Key' : '输入新的 API Key';
  });
  const model = $('#deepseek-model');
  if (model && document.activeElement !== model) {
    model.value = settings.deepseek_model || 'deepseek-chat';
  }
}

function renderStyleOptions(styles = state.bootstrap?.styles) {
  const list = $('#job-style-options');
  if (!list || !styles) return;
  list.replaceChildren(...(styles.available || []).map((name) => {
    const option = document.createElement('option');
    option.value = name;
    return option;
  }));
}

function renderProjectPaths(paths = state.bootstrap?.paths) {
  const target = $('#project-paths');
  if (!target || !paths) return;
  target.innerHTML = Object.entries(paths).map(([key, value]) => `
    <div class="project-path-row"><span>${esc(key)}</span><code>${esc(value)}</code></div>
  `).join('');
}

function renderSelects() {
  const jobs = state.tasks || [];
  const options = jobs.map((job) => `<option value="${esc(job.id)}">${esc(job.video_name)} · ${statusLabel[job.status] || job.status}</option>`).join('');
  const detail = $('#detail-job-select');
  if (detail) {
    detail.innerHTML = `<option value="">选择任务</option>${options}`;
    if (state.selectedTask) detail.value = state.selectedTask;
  }
  const log = $('#log-job-select');
  if (log) {
    log.innerHTML = `<option value="">选择任务</option>${options}`;
    if (state.selectedLog) log.value = state.selectedLog;
  }
}

function renderTasks() {
  if (!state.bootstrap) return;
  state.tasks = state.bootstrap.tasks || [];
  const counts = { queued: 0, running: 0, completed: 0, failed: 0 };
  state.tasks.forEach((job) => {
    if (job.status === 'queued' || job.status === 'pending') counts.queued += 1;
    else if (counts[job.status] !== undefined) counts[job.status] += 1;
  });
  $('#queue-count').textContent = counts.queued + counts.running;
  $('#metric-queued').textContent = counts.queued;
  $('#metric-running').textContent = counts.running;
  $('#metric-completed').textContent = counts.completed;
  $('#metric-failed').textContent = counts.failed;
  const queue = state.bootstrap.queue || {};
  const maxConcurrency = Math.min(3, Math.max(1, Number(queue.max_concurrency || 1)));
  $('#queue-caption').textContent = maxConcurrency > 1 ? `并行队列 · 最多 ${maxConcurrency} 个同时执行` : '单任务队列 · 按提交顺序执行';
  const runningSub = $('#metric-running-sub') || $('#metric-running')?.closest('.metric-card')?.querySelector('small');
  if (runningSub) runningSub.textContent = maxConcurrency > 1 ? `运行中 / 最多 ${maxConcurrency}` : '单任务队列';

  const tbody = $('#job-list');
  const empty = $('#empty-state');
  empty.classList.toggle('visible', state.tasks.length === 0);
  tbody.innerHTML = state.tasks.length ? state.tasks.map((job) => {
    const cls = statusClass(job.status);
    const label = statusLabel[job.status] || job.status;
    const progress = Number(job.progress || 0);
    const actions = [];
    actions.push(`<button class="row-action" data-action="detail" data-id="${esc(job.id)}" title="查看步骤详情"><i data-lucide="list-checks"></i></button>`);
    actions.push(`<button class="row-action" data-action="log" data-id="${esc(job.id)}" title="查看日志"><i data-lucide="scroll-text"></i></button>`);
    actions.push(`<button class="row-action" data-action="report" data-id="${esc(job.id)}" title="查看报告"><i data-lucide="file-text"></i></button>`);
    if (job.status === 'queued' || job.status === 'running') {
      actions.push(`<button class="row-action" data-action="cancel" data-id="${esc(job.id)}" title="停止任务"><i data-lucide="square"></i></button>`);
    }
    if (job.status === 'failed' || job.status === 'pending') {
      actions.push(`<button class="row-action" data-action="resume" data-id="${esc(job.id)}" title="断点续跑"><i data-lucide="play"></i></button>`);
    }
    if (job.draft_name && (job.status === 'failed' || job.status === 'completed')) {
      actions.push(`<button class="row-action" data-action="phase2" data-id="${esc(job.id)}" title="重跑音频平滑+字幕+风格后处理"><i data-lucide="subtitles"></i></button>`);
    }
    if (job.draft_name && (job.status === 'failed' || job.status === 'completed')) {
      actions.push(`<button class="row-action" data-action="gaps" data-id="${esc(job.id)}" title="只补字幕空隙"><i data-lucide="align-justify"></i></button>`);
    }
    if (job.status === 'failed' || job.status === 'completed') {
      actions.push(`<button class="row-action" data-action="retry" data-id="${esc(job.id)}" title="新建任务并从头执行"><i data-lucide="rotate-ccw"></i></button>`);
    }
    return `<tr>
      <td><div class="job-title"><span class="file-icon"><i data-lucide="${fileIcon(job.status)}"></i></span><div><strong title="${esc(job.video)}">${esc(job.video_name)}</strong><small>${esc(job.id)}${job.draft_name ? ` · 草稿 ${esc(job.draft_name)}` : ''}</small></div></div></td>
      <td><span class="status-pill ${cls}"><i></i>${label}</span></td>
      <td><div class="task-progress"><span style="width:${Math.min(100, Math.max(0, progress))}%"></span></div><small class="progress-label">${progress}%</small></td>
      <td>${formatTime(job.updated_at)}</td>
      <td><div class="row-actions">${actions.join('')}</div></td>
    </tr>`;
  }).join('') : '';
  renderSelects();
  window.lucide?.createIcons();
}

function renderDetailSelect() {
  const select = $('#detail-job-select');
  if (!select) return;
  const jobs = state.tasks || [];
  const options = jobs.map((job) => `<option value="${esc(job.id)}">${esc(job.video_name)} · ${statusLabel[job.status] || job.status}</option>`).join('');
  select.innerHTML = `<option value="">选择任务</option>${options}`;
  if (state.selectedTask) select.value = state.selectedTask;
}

async function loadDetail() {
  const id = state.selectedTask;
  const target = $('#detail-summary');
  const stepsTarget = $('#detail-steps');
  const reportTarget = $('#detail-report');
  if (!id) {
    if (target) target.innerHTML = '<div class="empty-state visible"><div class="empty-icon"><i data-lucide="list-checks"></i></div><h3>选择任务查看详情</h3></div>';
    if (stepsTarget) stepsTarget.hidden = true;
    if (reportTarget) reportTarget.hidden = true;
    const reviewTarget = $('#detail-subtitle-review');
    if (reviewTarget) reviewTarget.hidden = true;
    return;
  }
  let task = state.tasks.find((item) => item.id === id);
  try {
    const data = await api(`/api/tasks/${encodeURIComponent(id)}`);
    task = data.task || task;
  } catch {}
  if (!task) {
    if (target) target.innerHTML = '<div class="empty-state visible"><div class="empty-icon"><i data-lucide="file-question"></i></div><h3>任务不存在</h3></div>';
    return;
  }
  state.selectedTask = task.id;
  renderDetail(task);
  await loadSubtitleReview();
  if (state.reportMode) await loadReport();
}

function renderDetail(task) {
  const cls = statusClass(task.status);
  const label = statusLabel[task.status] || task.status;
  const summary = $('#detail-summary');
  summary.innerHTML = `
    <div class="detail-summary-grid">
      <div class="detail-summary-main">
        <span class="status-pill ${cls}"><i></i>${label}</span>
        <strong title="${esc(task.video)}">${esc(task.video_name)}</strong>
        <small>${esc(task.id)}</small>
      </div>
      <div><span>草稿</span><strong>${esc(task.draft_name || '尚未创建')}</strong></div>
      <div><span>进度</span><strong>${Math.min(100, Math.max(0, Number(task.progress || 0)))}%</strong></div>
      <div><span>更新</span><strong>${formatTime(task.updated_at)}</strong></div>
      <div><span>当前断点</span><strong>${esc(task.current_step ? `步骤 ${task.current_step}` : '未开始')}</strong></div>
    </div>
    ${task.error ? `<div class="detail-error"><i data-lucide="triangle-alert"></i><span>${esc(task.error)}</span></div>` : ''}
  `;
  window.lucide?.createIcons();

  const stepsTarget = $('#detail-steps');
  stepsTarget.hidden = false;
  if (!task.steps?.length) {
    stepsTarget.innerHTML = '<div class="empty-state visible"><div class="empty-icon"><i data-lucide="loader-circle"></i></div><h3>任务尚未生成步骤状态</h3><p>队列启动后会自动写入步骤检查点。</p></div>';
    window.lucide?.createIcons();
    return;
  }
  stepsTarget.innerHTML = `
    <div class="section-heading"><div><h3>步骤状态</h3><span>音频平滑 + 步骤7/12 + 风格后处理</span></div></div>
    <div class="step-table-wrap"><table class="step-table">
      <thead><tr><th>步骤</th><th>状态</th><th>尝试</th><th>耗时</th><th>错误 / 输出</th></tr></thead>
      <tbody>${task.steps.map((step) => {
        const stepCls = step.status === 'completed' ? 'completed' : step.status === 'failed' ? 'failed' : step.status === 'skipped' ? 'cancelled' : 'queued';
        return `<tr>
          <td><strong>${esc(step.label)}</strong><small>order ${step.order} · ${step.key}</small></td>
          <td><span class="status-pill ${stepCls}"><i></i>${statusLabel[step.status] || step.status}</span></td>
          <td>${step.attempts || 0}</td>
          <td>${step.duration_s == null ? '—' : `${step.duration_s}s`}</td>
          <td class="step-error">${esc(step.error || (step.status === 'completed' ? '通过' : '等待执行'))}</td>
        </tr>`;
      }).join('')}</tbody>
    </table></div>
  `;
  window.lucide?.createIcons();
  const reportTarget = $('#detail-report');
  reportTarget.hidden = !state.reportMode;
  const reviewTarget = $('#detail-subtitle-review');
  if (reviewTarget) reviewTarget.hidden = true;
}

async function loadReport() {
  if (!state.selectedTask) return;
  const data = await api(`/api/tasks/${encodeURIComponent(state.selectedTask)}/report`);
  const content = data.report_md || (data.report_json ? JSON.stringify(data.report_json, null, 2) : '');
  $('#report-content').textContent = content || '暂无报告';
  $('#detail-report').hidden = false;
}

async function loadSubtitleReview() {
  const target = $('#detail-subtitle-review');
  if (!target || !state.selectedTask) return;
  try {
    const data = await api(`/api/tasks/${encodeURIComponent(state.selectedTask)}/subtitle-review`);
    if (!data.exists || !data.review) {
      target.hidden = true;
      return;
    }
    const items = data.review.items || [];
    const needs = items.filter((item) => item.needs_review);
    const provider = data.review.ai_provider || '本地修正';
    $('#subtitle-review-summary').textContent = `总 ${data.review.summary?.total ?? items.length} 条，需复核 ${data.review.summary?.needs_review ?? needs.length} · ${provider}`;
    const price = data.price_roles;
    if (price && (price.original_text || price.current_text)) {
      $('#subtitle-review-summary').textContent += ` · 原价: ${esc(price.original_text || '未识别')} · 上车价: ${esc(price.current_text || '未识别')}`;
    }
    const list = $('#subtitle-review-list');
    list.innerHTML = needs.length ? needs.map((item) => `
      <div class="review-row">
        <strong>${esc(item.final || item.raw || '')}</strong>
        <small>${esc(String(item.start_ms ?? ''))}-${esc(String(item.end_ms ?? ''))}ms · ${esc(item.reason || '')}</small>
      </div>
    `).join('') : '<div class="review-empty">没有可疑字幕，清单已生成</div>';
    target.hidden = false;
  } catch {
    target.hidden = true;
  }
}

async function loadLog() {
  const id = $('#log-job-select')?.value || state.selectedLog;
  if (!id) {
    $('#log-content').textContent = '暂无日志';
    return;
  }
  state.selectedLog = id;
  const data = await api(`/api/tasks/${encodeURIComponent(id)}/log`);
  $('#log-content').textContent = data.log || '暂无日志';
}

async function actionJob(action, id) {
  const task = state.tasks.find((item) => item.id === id);
  if (action === 'detail') {
    state.reportMode = false;
    state.selectedTask = id;
    setTab('details');
    return;
  }
  if (action === 'log') {
    state.selectedLog = id;
    $('#log-job-select').value = id;
    setTab('logs');
    await loadLog();
    return;
  }
  if (action === 'report') {
    state.reportMode = true;
    state.selectedTask = id;
    setTab('details');
    return;
  }
  if (action === 'resume') {
    await api(`/api/tasks/${encodeURIComponent(id)}/resume`, { method: 'POST', body: JSON.stringify({ options: {} }) });
    await refresh();
    toast('已加入断点续跑队列');
    return;
  }
  if (action === 'phase2') {
    await api(`/api/tasks/${encodeURIComponent(id)}/resume`, {
      method: 'POST',
      body: JSON.stringify({ options: { phase2: true, force: true, smooth_audio: true, review_subtitles: true } }),
    });
    await refresh();
    toast('已加入字幕阶段重跑队列');
    return;
  }
  if (action === 'gaps') {
    await api(`/api/tasks/${encodeURIComponent(id)}/resume`, {
      method: 'POST',
      body: JSON.stringify({ options: { phase2: true, force: true, start_from: 15.5, stop_after: 15.5 } }),
    });
    await refresh();
    toast('已加入只补字幕空隙队列');
    return;
  }
  if (action === 'retry') {
    if (!task || !task.video) throw new Error('找不到源视频');
    await api('/api/run', {
      method: 'POST',
      body: JSON.stringify({ path: task.video, options: { fresh: true, force: true } }),
    });
    await refresh();
    toast('已提交重跑任务');
    return;
  }
  if (action === 'cancel') {
    await api(`/api/tasks/${encodeURIComponent(id)}/cancel`, { method: 'POST', body: '{}' });
    await refresh();
    toast('已请求停止任务');
  }
}

function openJobModal() {
  $('#manual-job-path').value = '';
  $('#modal-video-name').textContent = '尚未选择素材';
  $('#modal-video-path').textContent = '选择单个视频或包含视频的文件夹';
  $('#job-mode').value = 'full';
  $('#job-draft').value = '';
  $('#job-style').value = state.bootstrap?.styles?.default || '';
  $('#job-bgm').value = '10';
  $('#job-snapshot').value = 'json';
  $('#job-max-attempts').value = '2';
  $('#job-recursive').checked = true;
  $('#job-watermark').checked = false;
  $('#job-flower').checked = false;
  $('#job-smooth-audio').checked = true;
  $('#job-review-subtitles').checked = true;
  $('#job-visual-match').checked = true;
  $('#job-dry-run').checked = false;
  $('#job-no-close').checked = false;
  $('#job-no-restore').checked = false;
  $('#job-modal').classList.add('open');
  $('#job-modal').setAttribute('aria-hidden', 'false');
  state.drafts = [];
  clearDraftSelection();
  renderDraftMode();
  window.lucide?.createIcons();
}

function closeJobModal() {
  $('#job-modal').classList.remove('open');
  $('#job-modal').setAttribute('aria-hidden', 'true');
}

function renderDraftMode() {
  const phase2 = $('#job-mode')?.value === 'phase2';
  const picker = $('#draft-picker');
  const loadBtn = $('#load-drafts-btn');
  if (picker) picker.hidden = !phase2;
  if (loadBtn) loadBtn.hidden = !phase2;
}

function selectedDraftPaths() {
  return [...$$('#draft-list input[type="checkbox"]:checked')].map((input) => input.value);
}

function updateDraftCount() {
  const count = $('#draft-count');
  if (count) count.textContent = `${selectedDraftPaths().length} 个已选`;
}

function clearDraftSelection() {
  $$('#draft-list input[type="checkbox"]').forEach((input) => { input.checked = false; });
  updateDraftCount();
}

async function loadDrafts() {
  const data = await api('/api/drafts');
  state.drafts = data.drafts || [];
  const list = $('#draft-list');
  if (!list) return;
  list.innerHTML = state.drafts.length ? state.drafts.map((draft) => `
    <label class="draft-item">
      <input type="checkbox" value="${esc(draft.path)}" ${draft.video ? '' : 'disabled'}>
      <span class="draft-item-main">
        <strong>${esc(draft.name)}</strong>
        <small>${draft.video_name ? esc(draft.video_name) : '未识别源视频'}</small>
      </span>
      <span class="draft-path" title="${esc(draft.path)}">${esc(draft.path)}</span>
    </label>
  `).join('') : '<div class="draft-empty">没有找到剪映草稿</div>';
  updateDraftCount();
  window.lucide?.createIcons();
}

function closePathPicker() {
  $('#path-modal').classList.remove('open');
  $('#path-modal').setAttribute('aria-hidden', 'true');
  state.pathPicker = null;
}

async function openPathPicker(mode, target, initial = '') {
  state.pathPicker = { mode, target, current: '', parent: '' };
  $('#path-modal-title').textContent = mode === 'video' ? '选择本地视频' : '选择素材目录';
  $('#path-picker-help').textContent = mode === 'video' ? '进入文件夹后单击视频完成选择' : '进入文件夹后点击“选择当前目录”';
  $('#path-modal').classList.add('open');
  $('#path-modal').setAttribute('aria-hidden', 'false');
  await loadPath(initial);
}

async function loadPath(path = '') {
  const picker = state.pathPicker;
  if (!picker) return;
  const data = await api('/api/browse', {
    method: 'POST',
    body: JSON.stringify({ mode: picker.mode, path }),
  });
  picker.current = data.current;
  picker.parent = data.parent;
  $('#path-current-input').value = data.current || '';
  $('#path-parent-btn').disabled = !data.parent;
  const confirm = $('#select-current-folder-btn');
  confirm.style.display = (picker.mode === 'folder' && data.current) ? '' : 'none';
  const rows = [...data.roots, ...data.entries];
  $('#path-list').innerHTML = rows.length ? rows.map((entry) => `
    <button class="path-entry ${entry.kind}" data-path="${esc(entry.path)}" data-kind="${entry.kind}">
      <i data-lucide="${entry.kind === 'video' ? 'file-video-2' : 'folder'}"></i><span>${esc(entry.name)}</span>
    </button>
  `).join('') : '<div class="path-empty">当前目录没有可选择的内容</div>';
  window.lucide?.createIcons();
}

function applyPickedPath(path) {
  const picker = state.pathPicker;
  if (!picker) return;
  if (picker.target === 'draft') {
    $('#job-draft').value = path;
  } else {
    $('#manual-job-path').value = path;
    const name = path.split(/[\\/]/).pop() || path;
    $('#modal-video-name').textContent = name;
    $('#modal-video-path').textContent = picker.mode === 'folder' ? `${path}（将加入其中支持的视频）` : path;
    if (picker.mode === 'folder') $('#job-recursive').checked = true;
  }
  closePathPicker();
}

async function createJob() {
  const mode = $('#job-mode').value;
  const rawPath = $('#manual-job-path').value.trim();
  const options = {
    recursive: $('#job-recursive').checked,
    bgm: Number($('#job-bgm').value),
    snapshot_mode: $('#job-snapshot').value,
    max_attempts: Number($('#job-max-attempts').value),
    watermark: $('#job-watermark').checked,
    enable_flower_text: $('#job-flower').checked,
    smooth_audio: $('#job-smooth-audio').checked,
    review_subtitles: $('#job-review-subtitles').checked,
    visual_match: $('#job-visual-match').checked,
    dry_run: $('#job-dry-run').checked,
    no_close_jianying: $('#job-no-close').checked,
    no_restore: $('#job-no-restore').checked,
  };
  const style = $('#job-style').value.trim();
  if (style) options.style = style;
  const draft = $('#job-draft').value.trim();
  let body;
  if (mode === 'phase2') {
    options.phase2 = true;
    options.force = true;
    const drafts = selectedDraftPaths();
    if (draft && !drafts.includes(draft)) drafts.push(draft);
    if (!drafts.length) throw new Error('请选择至少一个剪映草稿，或填写草稿名');
    body = JSON.stringify({ drafts, options });
  } else {
    if (!rawPath) throw new Error('请选择视频或文件夹，或粘贴完整路径');
    if (draft) options.draft = draft;
    body = JSON.stringify({ path: rawPath, options });
  }
  const data = await api('/api/run', { method: 'POST', body });
  closeJobModal();
  await refresh();
  if (data.errors?.length) toast(data.errors[0]);
  else toast(data.queued_count > 1 ? `已加入 ${data.queued_count} 个任务` : '任务已加入队列');
}

function renderQueueSettings(queue = state.bootstrap?.queue) {
  if (!queue) return;
  const max = Math.min(3, Math.max(1, Number(queue.max_concurrency || 1)));
  const enabled = max > 1;
  const checkbox = $('#parallel-enabled');
  const select = $('#max-concurrency');
  if (checkbox) checkbox.checked = enabled;
  if (select) select.value = String(max);
}

async function saveQueueSettings() {
  const enabled = $('#parallel-enabled')?.checked === true;
  const requested = Number($('#max-concurrency')?.value || 3);
  const max = enabled ? Math.min(3, Math.max(2, requested)) : 1;
  const data = await api('/api/queue/config', {
    method: 'POST',
    body: JSON.stringify({ parallel_enabled: enabled, max_concurrency: max }),
  });
  state.bootstrap.queue = data.queue || {};
  renderQueueSettings(state.bootstrap.queue);
  renderTasks();
  toast(enabled ? `并行队列已开启，最多 ${max} 个任务同时执行` : '已切回单任务队列');
}

async function saveApiSettings(clearKeys = false) {
  const payload = {
    deepseek_model: $('#deepseek-model')?.value.trim() || 'deepseek-chat',
  };
  const deepseek = $('#deepseek-api-key')?.value.trim() || '';
  const dashscope = $('#dashscope-api-key')?.value.trim() || '';
  if (deepseek) payload.deepseek_api_key = deepseek;
  if (dashscope) payload.dashscope_api_key = dashscope;
  if (clearKeys) payload.clear_keys = true;

  const data = await api('/api/settings', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  state.bootstrap.settings = data.settings;
  state.bootstrap.environment = data.environment;
  $('#deepseek-api-key').value = '';
  $('#dashscope-api-key').value = '';
  renderApiSettings(data.settings);
  renderEnvironment(data.environment);
  window.lucide?.createIcons();
  toast(clearKeys ? '已清除本机保存的 API Key' : 'API 设置已保存并生效');
}

async function refresh() {
  const data = await api('/api/bootstrap');
  state.bootstrap = data;
  state.tasks = data.tasks || [];
  renderEnvironment();
  renderApiSettings();
  renderStyleOptions();
  renderProjectPaths();
  renderTasks();
  renderQueueSettings();
  if (state.activeTab === 'details' && state.selectedTask) await loadDetail();
  if (state.activeTab === 'logs') await loadLog();
}

document.addEventListener('click', async (event) => {
  const nav = event.target.closest('[data-tab]');
  if (nav) return setTab(nav.dataset.tab);

  const action = event.target.closest('[data-action]');
  if (action) {
    try { await actionJob(action.dataset.action, action.dataset.id); }
    catch (error) { toast(error.message); }
    return;
  }

  if (event.target.closest('#add-video-btn,#empty-add-btn')) return openJobModal();
  if (event.target.closest('#modal-choose-video-btn')) {
    try { await openPathPicker('video', 'job'); } catch (error) { toast(error.message); }
    return;
  }
  if (event.target.closest('#modal-choose-folder-btn')) {
    try { await openPathPicker('folder', 'job'); } catch (error) { toast(error.message); }
    return;
  }
  const pathEntry = event.target.closest('.path-entry');
  if (pathEntry) {
    try {
      if (pathEntry.dataset.kind === 'folder') await loadPath(pathEntry.dataset.path);
      else applyPickedPath(pathEntry.dataset.path);
    } catch (error) { toast(error.message); }
    return;
  }
  if (event.target.closest('#path-roots-btn')) {
    try { await loadPath(''); } catch (error) { toast(error.message); }
    return;
  }
  if (event.target.closest('#path-parent-btn')) {
    try { await loadPath(state.pathPicker?.parent || ''); } catch (error) { toast(error.message); }
    return;
  }
  if (event.target.closest('#select-current-folder-btn') && state.pathPicker?.current) {
    applyPickedPath(state.pathPicker.current);
    return;
  }
  if (event.target.closest('#close-path-modal-btn') || event.target.id === 'path-modal') return closePathPicker();
  if (event.target.closest('#submit-job-btn')) {
    try { await createJob(); } catch (error) { toast(error.message); }
    return;
  }
  if (event.target.closest('#close-modal-btn,#cancel-modal-btn') || event.target.id === 'job-modal') return closeJobModal();
  if (event.target.closest('#refresh-btn')) {
    try { await refresh(); toast('数据已刷新'); } catch (error) { toast(error.message); }
    return;
  }
  if (event.target.closest('#recheck-btn')) {
    try {
      const data = await api('/api/check', { method: 'POST', body: '{}' });
      state.bootstrap.environment = data;
      renderEnvironment(data);
      toast('环境预检已更新');
    } catch (error) { toast(error.message); }
    return;
  }
  if (event.target.closest('#refresh-log-btn')) {
    try { await loadLog(); } catch (error) { toast(error.message); }
    return;
  }
  if (event.target.closest('#refresh-detail-btn')) {
    try { await loadDetail(); } catch (error) { toast(error.message); }
    return;
  }
  if (event.target.closest('#open-report-btn')) {
    state.reportMode = true;
    try { await loadReport(); } catch (error) { toast(error.message); }
    return;
  }
  if (event.target.closest('#open-review-btn')) {
    state.reportMode = false;
    try {
      $('#detail-report').hidden = true;
      await loadSubtitleReview();
      if ($('#detail-subtitle-review').hidden) toast('该任务暂无字幕复核清单');
    } catch (error) { toast(error.message); }
    return;
  }
  if (event.target.closest('#fix-gaps-btn')) {
    const gapsTask = state.tasks.find((item) => item.id === state.selectedTask);
    if (!gapsTask?.draft_name) { toast('请选择已有草稿的任务'); return; }
    try { await actionJob('gaps', gapsTask.id); } catch (error) { toast(error.message); }
    return;
  }
});

$('#parallel-enabled')?.addEventListener('change', () => saveQueueSettings().catch((error) => toast(error.message)));
$('#max-concurrency')?.addEventListener('change', () => saveQueueSettings().catch((error) => toast(error.message)));
$('#api-settings-form')?.addEventListener('submit', (event) => {
  event.preventDefault();
  saveApiSettings().catch((error) => toast(error.message));
});
$('#clear-api-keys-btn')?.addEventListener('click', () => {
  if (!window.confirm('确定清除当前 Windows 用户保存的 API Key？')) return;
  saveApiSettings(true).catch((error) => toast(error.message));
});

$('#path-current-input')?.addEventListener('keydown', async (event) => {
  if (event.key === 'Enter') {
    try { await loadPath(event.target.value.trim()); } catch (error) { toast(error.message); }
  }
});
$('#detail-job-select')?.addEventListener('change', (event) => {
  state.reportMode = false;
  state.selectedTask = event.target.value;
  loadDetail();
});
$('#log-job-select')?.addEventListener('change', loadLog);

(async function init() {
  try {
    await refresh();
    window.lucide?.createIcons();
    setInterval(async () => {
      try {
        await refresh();
        if (state.selectedLog && $('#logs-tab')?.classList.contains('active')) await loadLog();
      } catch {}
    }, 1500);
  } catch (error) {
    toast(error.message);
  }
})();
$('#job-mode')?.addEventListener('change', renderDraftMode);
$('#load-drafts-btn')?.addEventListener('click', async () => {
  try {
    await loadDrafts();
    toast(state.drafts.length ? `已读取 ${state.drafts.length} 个剪映草稿` : '没有找到剪映草稿');
  } catch (error) { toast(error.message); }
});
$('#clear-drafts-btn')?.addEventListener('click', () => {
  clearDraftSelection();
  window.lucide?.createIcons();
});
$('#draft-list')?.addEventListener('change', updateDraftCount);
