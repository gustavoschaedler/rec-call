const micSelect = document.getElementById('micDevice');
const meetingSelect = document.getElementById('meetingDevice');
const errorBox = document.getElementById('errorBox');
const currentFile = document.getElementById('currentFile');
const recordingsBody = document.getElementById('recordingsBody');
const emptyRecordings = document.getElementById('emptyRecordings');

const transportRow = document.getElementById('transportRow');
const playbackBar = document.getElementById('playbackBar');
const startBtn = document.getElementById('startBtn');
const pauseBtn = document.getElementById('pauseBtn');
const resumeBtn = document.getElementById('resumeBtn');
const stopBtn = document.getElementById('stopBtn');

const recIndicator = document.getElementById('recIndicator');
const recIndicatorText = document.getElementById('recIndicatorText');
const statusIcon = document.getElementById('statusIcon');
const timerEl = document.getElementById('timer');
const recMeta = document.getElementById('recMeta');

const audioPlayer = document.getElementById('audioPlayer');
const closePlayer = document.getElementById('closePlayer');

const confirmDialog = document.getElementById('confirmDialog');
const confirmText = document.getElementById('confirmText');
const confirmCancel = document.getElementById('confirmCancel');
const confirmDelete = document.getElementById('confirmDelete');
const themeToggle = document.getElementById('themeToggle');

const settingsBtn = document.getElementById('settingsBtn');
const settingsDialog = document.getElementById('settingsDialog');
const settingsClose = document.getElementById('settingsClose');
const settingsDone = document.getElementById('settingsDone');
const sampleRateSel = document.getElementById('sampleRate');
const bitDepthSel = document.getElementById('bitDepth');
const pageSizeSel = document.getElementById('pageSize');

const pagination = document.getElementById('pagination');
const prevPageBtn = document.getElementById('prevPage');
const nextPageBtn = document.getElementById('nextPage');
const pageInfo = document.getElementById('pageInfo');

const BARS = 56;

let currentState = 'idle';
let lastStatus = { state: 'idle' };
let timerBase = 0;
let timerBaseAt = 0;
let timerRunning = false;
let currentPlayingPath = null;
let currentPlayingName = null;
let isPlaying = false;
let pendingDelete = null;

let allRecordings = [];
let currentPage = 1;
const PAGESIZE_KEY = 'reccall-pagesize';
let pageSize = Math.max(1, Number(localStorage.getItem(PAGESIZE_KEY)) || 5);

let recBands = null;
let playAnalyser = null;
let playBuf = null;

/* ---------------- Theme ---------------- */

const THEME_KEY = 'reccall-theme';
function applyTheme(t) { document.documentElement.setAttribute('data-theme', t); }
applyTheme(localStorage.getItem(THEME_KEY) || 'dark');
themeToggle.addEventListener('click', () => {
  const next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
  applyTheme(next);
  localStorage.setItem(THEME_KEY, next);
});

/* ---------------- Settings (devices + sound quality) ---------------- */

const QUALITY_KEY = 'reccall-quality';
function loadQuality() {
  try {
    const q = JSON.parse(localStorage.getItem(QUALITY_KEY) || '{}');
    if (q.sampleRate) sampleRateSel.value = q.sampleRate;
    if (q.bitDepth) bitDepthSel.value = q.bitDepth;
  } catch (_) {}
}
function saveQuality() {
  localStorage.setItem(QUALITY_KEY, JSON.stringify({
    sampleRate: sampleRateSel.value,
    bitDepth: bitDepthSel.value,
  }));
}
loadQuality();
sampleRateSel.addEventListener('change', () => { saveQuality(); updateRecChips(); });
bitDepthSel.addEventListener('change', () => { saveQuality(); updateRecChips(); });
micSelect.addEventListener('change', updateRecChips);
meetingSelect.addEventListener('change', updateRecChips);

pageSizeSel.value = String(pageSize);
pageSizeSel.addEventListener('change', () => {
  pageSize = Math.max(1, Number(pageSizeSel.value) || 5);
  localStorage.setItem(PAGESIZE_KEY, String(pageSize));
  currentPage = 1;
  renderRecordings();
});

settingsBtn.addEventListener('click', () => settingsDialog.showModal());
settingsClose.addEventListener('click', () => settingsDialog.close());
settingsDone.addEventListener('click', () => settingsDialog.close());

/* ---------------- Icons (for dynamically built rows) ---------------- */

const ICON = {
  play: '<svg class="icon" viewBox="0 0 24 24"><path d="M8 5v14l11-7z" fill="currentColor"/></svg>',
  pause: '<svg class="icon" viewBox="0 0 24 24"><rect x="6" y="5" width="4" height="14" rx="1" fill="currentColor"/><rect x="14" y="5" width="4" height="14" rx="1" fill="currentColor"/></svg>',
  download: '<svg class="icon" viewBox="0 0 24 24"><path d="M12 3v12m0 0l4-4m-4 4l-4-4M5 21h14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  trash: '<svg class="icon" viewBox="0 0 24 24"><path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2m2 0v12a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V7" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
};

/* ---------------- Spectrum visualiser (shared by record + playback) ---------------- */

function roundedBar(ctx, x, y, w, h, r) {
  const rr = Math.max(0, Math.min(r, w / 2, h));
  ctx.beginPath();
  ctx.moveTo(x, y + h);
  ctx.lineTo(x, y + rr);
  ctx.arcTo(x, y, x + rr, y, rr);
  ctx.lineTo(x + w - rr, y);
  ctx.arcTo(x + w, y, x + w, y + rr, rr);
  ctx.lineTo(x + w, y + h);
  ctx.closePath();
  ctx.fill();
}

function makeVisualizer(canvas) {
  const ctx = canvas.getContext('2d');
  let provider = null;

  function fit() {
    const dpr = window.devicePixelRatio || 1;
    const r = canvas.getBoundingClientRect();
    canvas.width = Math.max(1, Math.floor(r.width * dpr));
    canvas.height = Math.max(1, Math.floor(r.height * dpr));
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    canvas._w = r.width;
    canvas._h = r.height;
  }
  fit();
  window.addEventListener('resize', fit);

  function draw() {
    const w = canvas._w, h = canvas._h;
    if (w <= 1 || h <= 1) { canvas._raf = requestAnimationFrame(draw); return; }
    ctx.clearRect(0, 0, w, h);

    const live = provider ? provider() : null;
    const mags = new Array(BARS);
    if (live && live.length) {
      for (let i = 0; i < BARS; i++) mags[i] = live[i] || 0;
    } else {
      const t = performance.now() / 700;
      for (let i = 0; i < BARS; i++) mags[i] = 0.05 + 0.045 * (Math.sin(t + i * 0.45) + 1) / 2;
    }

    const gap = 3;
    const bw = (w - (BARS - 1) * gap) / BARS;
    for (let i = 0; i < BARS; i++) {
      const bh = Math.max(2, mags[i] * h * 0.92);
      const x = i * (bw + gap);
      const y = h - bh;
      const grad = ctx.createLinearGradient(0, h, 0, y);
      grad.addColorStop(0, '#e11d48');
      grad.addColorStop(1, '#fb7185');
      ctx.fillStyle = grad;
      roundedBar(ctx, x, y, bw, bh, 3);
    }
    canvas._raf = requestAnimationFrame(draw);
  }
  cancelAnimationFrame(canvas._raf);
  draw();

  return { setProvider(fn) { provider = fn; } };
}

const recViz = makeVisualizer(document.getElementById('recSpectrum'));

// One canvas, three sources: recording bands (server WS) while recording,
// playback bands (audio analyser) while playing, idle animation otherwise.
recViz.setProvider(() => {
  if (currentState === 'recording') return recBands;
  if (isPlaying && playAnalyser && playBuf && !audioPlayer.paused && !audioPlayer.ended) {
    playAnalyser.getByteFrequencyData(playBuf);
    const out = new Array(BARS);
    const usable = Math.floor(playBuf.length * 0.85);
    const step = Math.max(1, Math.floor(usable / BARS));
    for (let i = 0; i < BARS; i++) {
      let s = 0;
      for (let j = 0; j < step; j++) s += playBuf[i * step + j] || 0;
      out[i] = (s / step) / 255;
    }
    return out;
  }
  return null;
});

/* Recorder spectrum data: streamed from the server while recording. */
let specWs = null;

function openSpectrumStream() {
  try {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    specWs = new WebSocket(`${proto}://${location.host}/ws/spectrum`);
    specWs.onmessage = (ev) => { try { recBands = JSON.parse(ev.data); } catch (_) {} };
    specWs.onclose = () => { recBands = null; };
  } catch (_) { /* spectrum is best-effort */ }
}

function closeSpectrumStream() {
  recBands = null;
  if (specWs) { try { specWs.close(); } catch (_) {} specWs = null; }
}

/* Playback analyser feeds the same recorder canvas. */
let audioCtx = null;
let playSource = null;

function attachPlayViz() {
  try {
    if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    if (audioCtx.state === 'suspended') audioCtx.resume();
    if (!playSource) {
      playSource = audioCtx.createMediaElementSource(audioPlayer);
      playAnalyser = audioCtx.createAnalyser();
      playAnalyser.fftSize = 256;
      playAnalyser.smoothingTimeConstant = 0.8;
      playSource.connect(playAnalyser);
      playAnalyser.connect(audioCtx.destination);
      playBuf = new Uint8Array(playAnalyser.frequencyBinCount);
    }
  } catch (_) { /* best-effort */ }
}

/* ---------------- Helpers ---------------- */

function showError(message) { errorBox.hidden = false; errorBox.textContent = message; }
function clearError() { errorBox.hidden = true; errorBox.textContent = ''; }

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

async function api(path, options = {}) {
  const res = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...options });
  if (!res.ok) {
    let detail = await res.text();
    try { detail = JSON.parse(detail).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  if (res.status === 204) return null;
  const text = await res.text();
  return text ? JSON.parse(text) : null;
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GB`;
}

function formatDuration(totalSeconds) {
  const s = Math.max(0, Math.floor(totalSeconds));
  const hh = String(Math.floor(s / 3600)).padStart(2, '0');
  const mm = String(Math.floor((s % 3600) / 60)).padStart(2, '0');
  const ss = String(s % 60).padStart(2, '0');
  return `${hh}:${mm}:${ss}`;
}

function formatClock(totalSeconds) {
  if (totalSeconds == null) return '—';
  const s = Math.max(0, Math.round(totalSeconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = String(s % 60).padStart(2, '0');
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${ss}` : `${m}:${ss}`;
}

function formatQuality(r) {
  if (!r.sample_rate) return '—';
  const khz = (r.sample_rate / 1000).toFixed(r.sample_rate % 1000 ? 1 : 0);
  const depth = r.bit_depth || '';
  return `${khz} kHz${depth ? ' · ' + depth : ''}`;
}

function formatModified(iso) {
  if (!iso) return '—';
  const [date, time = ''] = String(iso).split('T');
  return `<div>${escapeHtml(date)}</div><div class="sub">${escapeHtml(time)}</div>`;
}

function recordingUrl(path) {
  return `/api/recordings/download/${encodeURIComponent(path).replaceAll('%2F', '/')}`;
}

/* ---------------- Devices ---------------- */

async function loadDevices() {
  clearError();
  const data = await api('/api/devices');
  const inputDevices = data.devices.filter(d => d.max_input_channels > 0);

  micSelect.innerHTML = '';
  const defaultOption = document.createElement('option');
  defaultOption.value = '';
  defaultOption.textContent = 'macOS Default Input';
  micSelect.appendChild(defaultOption);

  for (const d of inputDevices) {
    const opt = document.createElement('option');
    opt.value = d.id;
    opt.dataset.name = d.name;
    opt.textContent = `${d.name}${d.is_default_input ? ' (default)' : ''}`;
    micSelect.appendChild(opt);
  }

  meetingSelect.innerHTML = '';
  for (const d of inputDevices) {
    const opt = document.createElement('option');
    opt.value = d.id;
    opt.dataset.name = d.name;
    opt.textContent = `${d.name}${d.name.toLowerCase().includes('blackhole') ? ' ← recommended' : ''}`;
    meetingSelect.appendChild(opt);
    if (d.name.toLowerCase().includes('blackhole')) meetingSelect.value = d.id;
  }
  updateRecChips();
}

const RATE_LABEL = { auto: 'Auto', '48000': '48 kHz', '44100': '44.1 kHz', '32000': '32 kHz', '24000': '24 kHz', '16000': '16 kHz' };
const DEPTH_LABEL = { PCM_16: '16-bit', PCM_24: '24-bit', FLOAT: '32-bit float' };

// Reflect the selected devices + quality as chips next to the Recorder title.
function updateRecChips() {
  const micOpt = micSelect.options[micSelect.selectedIndex];
  const meetOpt = meetingSelect.options[meetingSelect.selectedIndex];
  document.getElementById('chipMic').textContent =
    micSelect.value === '' ? 'Default Input' : (micOpt ? (micOpt.dataset.name || micOpt.textContent) : '—');
  document.getElementById('chipMeeting').textContent =
    meetOpt ? (meetOpt.dataset.name || meetOpt.textContent) : '—';
  const rate = RATE_LABEL[sampleRateSel.value] || sampleRateSel.value;
  const depth = DEPTH_LABEL[bitDepthSel.value] || bitDepthSel.value;
  document.getElementById('chipQuality').textContent = `${rate} · ${depth}`;
}

/* ---------------- Recorder display (shared record + playback) ---------------- */

// Status icon shown to the left of the counter.
const STATUS_ICON = {
  idle: '<svg class="icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="5" fill="none" stroke="currentColor" stroke-width="2"/></svg>',
  recording: '<svg class="icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="6" fill="currentColor"/></svg>',
  paused: '<svg class="icon" viewBox="0 0 24 24"><rect x="6" y="5" width="4" height="14" rx="1" fill="currentColor"/><rect x="14" y="5" width="4" height="14" rx="1" fill="currentColor"/></svg>',
  playing: '<svg class="icon" viewBox="0 0 24 24"><path d="M8 5v14l11-7z" fill="currentColor"/></svg>',
};

function effectiveStatus() {
  if (isPlaying) return (audioPlayer.paused || audioPlayer.ended) ? 'paused' : 'playing';
  return currentState;
}

function applyStatusVisual() {
  const st = effectiveStatus();
  statusIcon.className = `statusIcon ${st}`;
  statusIcon.innerHTML = STATUS_ICON[st] || STATUS_ICON.idle;
  timerEl.classList.toggle('live', st === 'recording');
  timerEl.classList.toggle('blink', st === 'paused');
}

function updateRecorderUI() {
  if (isPlaying) {
    transportRow.hidden = true;
    playbackBar.hidden = false;
    recIndicator.className = 'recIndicator playing';
    recIndicatorText.textContent = 'Playing';
    recMeta.textContent = currentPlayingName ? `Playing · ${currentPlayingName}` : 'Playing';
    currentFile.textContent = '';
    applyStatusVisual();
    renderTimer();
    return;
  }

  transportRow.hidden = false;
  playbackBar.hidden = true;

  const s = lastStatus;
  const state = s.state || 'idle';
  const recording = state === 'recording';
  const paused = state === 'paused';
  const active = recording || paused;

  startBtn.disabled = active;
  pauseBtn.disabled = !recording;
  resumeBtn.disabled = !paused;
  stopBtn.disabled = !active;
  micSelect.disabled = active;
  meetingSelect.disabled = active;

  recIndicator.className = `recIndicator ${state}`;
  recIndicatorText.textContent = recording ? 'Recording' : paused ? 'Paused' : 'Idle';

  if (state === 'idle') {
    recMeta.textContent = 'Ready to record';
    currentFile.textContent = '';
  } else {
    const rate = s.sample_rate ? ` · ${(s.sample_rate / 1000).toFixed(s.sample_rate % 1000 ? 1 : 0)} kHz` : '';
    recMeta.textContent = `Stereo · ${s.bit_depth || '16-bit'}${rate}`;
    currentFile.textContent = s.file_path ? `Writing: ${s.file_path}` : '';
  }
  applyStatusVisual();
  renderTimer();
}

function renderTimer() {
  if (isPlaying) {
    timerEl.textContent = formatClock(audioPlayer.currentTime || 0);
    return;
  }
  let elapsed = timerBase;
  if (timerRunning) elapsed += (performance.now() - timerBaseAt) / 1000;
  timerEl.textContent = formatDuration(elapsed);
}

function applyStatus(s) {
  lastStatus = s;
  currentState = s.state || 'idle';
  timerBase = typeof s.elapsed_seconds === 'number' ? s.elapsed_seconds : 0;
  timerBaseAt = performance.now();
  timerRunning = currentState === 'recording';
  if (s.error) showError(s.error);
  if (!isPlaying) updateRecorderUI();
}

async function loadStatus() {
  applyStatus(await api('/api/status'));
}

/* ---------------- Recordings ---------------- */

async function loadRecordings() {
  const data = await api('/api/recordings');
  allRecordings = data.recordings || [];
  renderRecordings();
}

function renderRecordings() {
  const total = allRecordings.length;
  const pages = Math.max(1, Math.ceil(total / pageSize));
  currentPage = Math.min(Math.max(currentPage, 1), pages);
  const start = (currentPage - 1) * pageSize;
  const pageItems = allRecordings.slice(start, start + pageSize);

  recordingsBody.innerHTML = '';
  emptyRecordings.hidden = total > 0;

  for (const r of pageItems) {
    const tr = document.createElement('tr');
    const safePath = escapeHtml(r.path);
    const isCur = r.path === currentPlayingPath;
    const showPause = isCur && isPlaying && !audioPlayer.paused && !audioPlayer.ended;
    if (isCur) tr.classList.add('playingRow');
    tr.innerHTML = `
      <td class="idCol muted">${r.id != null ? '#' + r.id : ''}</td>
      <td class="playCol">
        <button class="iconAct ${isCur ? 'active' : ''}" data-action="play" data-path="${safePath}" title="${showPause ? 'Pause' : 'Play'}" aria-label="${showPause ? 'Pause' : 'Play'}">${showPause ? ICON.pause : ICON.play}</button>
      </td>
      <td class="fileCell">${safePath}</td>
      <td class="mono">${formatClock(r.duration_seconds)}</td>
      <td class="muted">${escapeHtml(formatQuality(r))}</td>
      <td>${formatBytes(r.size_bytes)}</td>
      <td class="modifiedCell">${formatModified(r.modified_at)}</td>
      <td class="rowActions">
        <a class="iconAct btnLink" href="${recordingUrl(r.path)}" download title="Download" aria-label="Download">${ICON.download}</a>
        <button class="iconAct danger" data-action="delete" data-path="${safePath}" title="Delete" aria-label="Delete">${ICON.trash}</button>
      </td>
    `;
    recordingsBody.appendChild(tr);
  }

  pagination.hidden = total <= pageSize;
  pageInfo.textContent = `Page ${currentPage} of ${pages} · ${total} recording${total === 1 ? '' : 's'}`;
  prevPageBtn.disabled = currentPage <= 1;
  nextPageBtn.disabled = currentPage >= pages;
}

function goToPage(delta) {
  currentPage += delta;
  renderRecordings();
}

function playRecording(path) {
  if (currentState === 'recording' || currentState === 'paused') return;
  currentPlayingPath = path;
  currentPlayingName = path.split('/').pop();
  isPlaying = true;
  attachPlayViz();
  audioPlayer.src = recordingUrl(path);
  audioPlayer.play().catch(() => {});
  updateRecorderUI();
  loadRecordings();
  document.querySelector('.recorder').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function stopPlayback() {
  audioPlayer.pause();
  audioPlayer.removeAttribute('src');
  audioPlayer.load();
  isPlaying = false;
  currentPlayingPath = null;
  currentPlayingName = null;
  updateRecorderUI();
  loadRecordings();
}

function togglePlayPause() {
  if (audioPlayer.paused) audioPlayer.play().catch(() => {});
  else audioPlayer.pause();
}

// Reflect the live play/pause state on the current row's button.
function refreshPlayButtons() {
  const playingNow = isPlaying && !audioPlayer.paused && !audioPlayer.ended;
  recordingsBody.querySelectorAll('button[data-action="play"]').forEach((btn) => {
    const isCur = !!currentPlayingPath && btn.dataset.path === currentPlayingPath;
    const showPause = isCur && playingNow;
    btn.innerHTML = showPause ? ICON.pause : ICON.play;
    btn.title = showPause ? 'Pause' : 'Play';
    btn.setAttribute('aria-label', showPause ? 'Pause' : 'Play');
    btn.classList.toggle('active', isCur);
  });
  if (isPlaying) {
    recIndicatorText.textContent = playingNow ? 'Playing' : 'Paused';
    applyStatusVisual();
  }
}

audioPlayer.addEventListener('timeupdate', () => { if (isPlaying) renderTimer(); });
audioPlayer.addEventListener('play', refreshPlayButtons);
audioPlayer.addEventListener('pause', refreshPlayButtons);
audioPlayer.addEventListener('ended', stopPlayback);

function openDeleteDialog(path) {
  pendingDelete = { path };
  confirmText.textContent = `Delete “${path}”?`;
  confirmDialog.showModal();
}

async function confirmDeletion() {
  if (!pendingDelete) return;
  const { path } = pendingDelete;
  try {
    await api(`/api/recordings/${encodeURIComponent(path).replaceAll('%2F', '/')}`, { method: 'DELETE' });
    if (path === currentPlayingPath) stopPlayback();
    confirmDialog.close();
    pendingDelete = null;
    await loadRecordings();
  } catch (e) {
    confirmDialog.close();
    pendingDelete = null;
    showError(e.message);
  }
}

/* ---------------- Transport actions ---------------- */

async function startRecording() {
  clearError();
  if (isPlaying) stopPlayback();
  const micRaw = micSelect.value;
  const meetingRaw = meetingSelect.value;
  if (!meetingRaw) throw new Error('Select the meeting audio device, usually BlackHole 2ch.');

  const micOpt = micSelect.options[micSelect.selectedIndex];
  const meetingOpt = meetingSelect.options[meetingSelect.selectedIndex];

  await api('/api/recordings/start', {
    method: 'POST',
    body: JSON.stringify({
      mic_device: micRaw === '' ? null : Number(micRaw),
      meeting_device: Number(meetingRaw),
      // Names let the server re-resolve indices that shifted since page load.
      mic_name: micRaw === '' ? null : (micOpt ? micOpt.dataset.name : null),
      meeting_name: meetingOpt ? meetingOpt.dataset.name : null,
      sample_rate: sampleRateSel.value === 'auto' ? null : Number(sampleRateSel.value),
      subtype: bitDepthSel.value,
    }),
  });
  await loadStatus();
  openSpectrumStream();
}

async function pauseRecording() { await api('/api/recordings/pause', { method: 'POST' }); await loadStatus(); }
async function resumeRecording() { await api('/api/recordings/resume', { method: 'POST' }); await loadStatus(); }
async function stopRecording() {
  await api('/api/recordings/stop', { method: 'POST' });
  closeSpectrumStream();
  await loadStatus();
  await loadRecordings();
}

recordingsBody.addEventListener('click', (event) => {
  const btn = event.target.closest('button[data-action]');
  if (!btn) return;
  const { action, path } = btn.dataset;
  if (action === 'play') {
    if (path === currentPlayingPath) togglePlayPause();
    else playRecording(path);
  }
  if (action === 'delete') openDeleteDialog(path);
});

closePlayer.addEventListener('click', stopPlayback);
prevPageBtn.addEventListener('click', () => goToPage(-1));
nextPageBtn.addEventListener('click', () => goToPage(1));
confirmCancel.addEventListener('click', () => { confirmDialog.close(); pendingDelete = null; });
confirmDelete.addEventListener('click', confirmDeletion);

for (const [id, fn] of [
  ['refreshDevices', loadDevices],
  ['refreshRecordings', loadRecordings],
  ['startBtn', startRecording],
  ['pauseBtn', pauseRecording],
  ['resumeBtn', resumeRecording],
  ['stopBtn', stopRecording],
]) {
  document.getElementById(id).addEventListener('click', async () => {
    try { await fn(); } catch (e) { showError(e.message); }
  });
}

setInterval(() => { if (timerRunning || isPlaying) renderTimer(); }, 250);

async function loadVersion() {
  try {
    const data = await api('/api/version');
    if (data && data.version) document.getElementById('appVersion').textContent = `v${data.version}`;
  } catch (_) { /* non-critical */ }
}

(async function init() {
  try {
    loadVersion();
    await loadDevices();
    await loadStatus();
    await loadRecordings();
    if (currentState === 'recording') openSpectrumStream();
    setInterval(loadStatus, 1500);
  } catch (e) {
    showError(e.message);
  }
})();
