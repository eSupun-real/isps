import { api, setToken, clearToken, getToken } from './api.js';
import { toast, statusPill, escHtml, vesselTableHTML, initLeafletMap, destroyMap, renderComplianceResults } from './ui.js';
import { readFileAsBase64, pollDocumentStatus, validateFileSize } from './upload.js';
import './style.css';

let currentUser = null;
let currentCallId = null;
let pendingDocs = {};
let bulkFileMap = [];

export { doLogout };

// ── Auth ──────────────────────────────────────────────────────────────────────
async function doLogin() {
  const u = document.getElementById('loginUser').value.trim();
  const p = document.getElementById('loginPass').value;
  const err = document.getElementById('authErr');
  err.style.display = 'none';
  try {
    const data = await api('POST', '/api/auth/login', { username: u, password: p });
    setToken(data.token);
    currentUser = data.user;
    initApp();
  } catch (e) {
    err.textContent = e.message || 'Login failed.';
    err.style.display = 'block';
  }
}
window.doLogin = doLogin;

function quickLogin(username, password) {
  document.getElementById('loginUser').value = username;
  document.getElementById('loginPass').value = password;
  doLogin();
}
window.quickLogin = quickLogin;

window.doLogout = doLogout;

function doLogout() {
  clearToken();
  currentUser = null;
  document.getElementById('authScreen').style.display = 'flex';
  document.getElementById('appShell').style.display = 'none';
}

async function tryAutoLogin() {
  const token = getToken();
  if (!token) return false;
  try {
    currentUser = await api('GET', '/api/auth/me');
    return true;
  } catch {
    clearToken();
    return false;
  }
}

function initApp() {
  document.getElementById('authScreen').style.display = 'none';
  document.getElementById('appShell').style.display = 'flex';
  document.getElementById('topbarName').textContent = currentUser.full_name || currentUser.username;
  document.getElementById('topbarRole').textContent = currentUser.role.replace('_', ' ');

  document.getElementById('navAgent').style.display = 'none';
  document.getElementById('navISPS').style.display = 'none';
  document.getElementById('navOfficer').style.display = 'none';

  const role = currentUser.role;
  if (role === 'agent') document.getElementById('navAgent').style.display = 'block';
  if (role === 'isps_office') document.getElementById('navISPS').style.display = 'block';
  if (role === 'isps_officer') {
    document.getElementById('navISPS').style.display = 'block';
    document.getElementById('navOfficer').style.display = 'block';
  }

  loadDashboard();
  loadVessels();
  if (role === 'isps_office' || role === 'isps_officer') loadReviewList();
  if (role === 'isps_officer') { loadNobjList(); loadRules(); loadConfig(); loadConfigModels(); loadLLMLogs(); }
  if (role === 'agent') loadAgentSettings();
}

// ── Agent Settings ──────────────────────────────────────────────────────────
window.loadAgentSettings = loadAgentSettings;

function loadAgentSettings() {
  document.getElementById('settings_name').value = currentUser.full_name || '';
  document.getElementById('settings_email').value = currentUser.email || '';
  document.getElementById('settings_phone').value = currentUser.phone || '';
  document.getElementById('settings_company').value = currentUser.company || '';
}

window.saveAgentSettings = saveAgentSettings;

async function saveAgentSettings() {
  const name = document.getElementById('settings_name').value.trim();
  const email = document.getElementById('settings_email').value.trim();
  if (!name || !email) { toast('Name and email are required', 'err'); return; }
  try {
    await api('PATCH', '/api/auth/settings', {
      full_name: name, email,
      phone: document.getElementById('settings_phone').value.trim(),
      company: document.getElementById('settings_company').value.trim()
    });
    currentUser.full_name = name;
    currentUser.email = email;
    document.getElementById('topbarName').textContent = name;
    document.getElementById('settingsStatus').innerHTML = '✓ Settings saved';
    document.getElementById('settingsStatus').style.color = 'var(--pass)';
    document.getElementById('settingsStatus').style.display = 'block';
    toast('Settings saved', 'ok');
  } catch (e) {
    document.getElementById('settingsStatus').innerHTML = '❌ ' + e.message;
    document.getElementById('settingsStatus').style.color = 'var(--fail)';
    document.getElementById('settingsStatus').style.display = 'block';
    toast(e.message, 'err');
  }
}

// ── Navigation ────────────────────────────────────────────────────────────────
window.showPage = showPage;

function showPage(id) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.getElementById('page-' + id).classList.add('active');
  document.querySelectorAll(`.nav-item[data-page="${id}"]`).forEach(n => n.classList.add('active'));
  if (id === 'submit' && currentUser.role === 'agent') autoFillAgentSettings();
}

function autoFillAgentSettings() {
  if (!document.getElementById('s_agent').value && currentUser.full_name)
    document.getElementById('s_agent').value = currentUser.full_name;
  if (!document.getElementById('s_agentEmail').value && currentUser.email)
    document.getElementById('s_agentEmail').value = currentUser.email;
  if (!document.getElementById('s_company').value && currentUser.company)
    document.getElementById('s_company').value = currentUser.company;
}

// ── Dashboard ─────────────────────────────────────────────────────────────────
async function loadDashboard() {
  try {
    const vessels = await api('GET', '/api/vessels');
    const total = vessels.length;
    const pending = vessels.filter(v => ['pending', 'documents_submitted', 'under_review'].includes(v.status)).length;
    const cleared = vessels.filter(v => v.status === 'no_objection_issued').length;
    const issues = vessels.filter(v => v.status === 'discrepancies_raised').length;
    document.getElementById('dashStats').innerHTML = `
      <div class="stat-box"><div class="num">${total}</div><div class="lbl">Total Calls</div></div>
      <div class="stat-box"><div class="num">${pending}</div><div class="lbl">Pending Review</div></div>
      <div class="stat-box"><div class="num" style="color:var(--fail)">${issues}</div><div class="lbl">Discrepancies</div></div>
      <div class="stat-box"><div class="num" style="color:var(--pass)">${cleared}</div><div class="lbl">Cleared</div></div>`;
    document.getElementById('dashVessels').innerHTML = vesselTableHTML(vessels.slice(0, 8), true);
    document.getElementById('vesselCount').textContent = total;
  } catch (e) { console.error(e); }
}

// ── Vessels ───────────────────────────────────────────────────────────────────
async function loadVessels() {
  try {
    const vessels = await api('GET', '/api/vessels');
    document.getElementById('vesselTable').innerHTML = vesselTableHTML(vessels, false);
  } catch (e) {}
}

async function openVessel(id) {
  try {
    const d = await api('GET', `/api/vessels/${id}`);
    currentCallId = id;
    const role = currentUser.role;
    if (role === 'agent') { showPage('submit'); populateSubmitForEdit(d); }
    else if (role === 'isps_office') { showPage('review'); openReviewDetail(d); }
    else { showPage('nobjection'); openNobjDetail(d); }
  } catch (e) { toast(e.message, 'err'); }
}
window.openVessel = openVessel;

// ── Submit Documents ──────────────────────────────────────────────────────────
function triggerUpload(id) { document.getElementById(id).click(); }
window.triggerUpload = triggerUpload;

function slotFileSelected(input, slotId, docType, label) {
  const file = input.files[0];
  if (!file) return;
  try {
    validateFileSize(file);
  } catch (e) {
    toast(e.message, 'err');
    input.value = '';
    return;
  }
  const slot = document.getElementById(slotId);
  slot.classList.add('uploaded');
  slot.querySelector('.ico').textContent = '⏳';
  slot.querySelector('.lbl').textContent = label + ' (reading…)';
  slot.querySelector('.sub').textContent = file.name.length > 22 ? file.name.substring(0, 22) + '…' : file.name;
  const reader = new FileReader();
  reader.onload = e => {
    const b64 = e.target.result.split(',')[1];
    pendingDocs[docType] = { file, b64, filename: file.name };
    slot.querySelector('.ico').textContent = '✅';
    slot.querySelector('.lbl').textContent = label + ' ✓';
  };
  reader.readAsDataURL(file);
}
window.slotFileSelected = slotFileSelected;

async function submitVesselAndDocs() {
  const name = document.getElementById('s_name').value.trim();
  const arrival = document.getElementById('s_arrival').value;
  if (!name || !arrival) { toast('Vessel name and expected arrival are required', 'err'); return; }

  const btn = document.getElementById('btnSubmitDocs');
  const status = document.getElementById('submitStatus');
  btn.disabled = true;
  status.style.display = 'block';
  status.innerHTML = '<span class="spinner"></span> Creating vessel call…';

  try {
    const callData = await api('POST', '/api/vessels', {
      vessel_name: name, imo_number: document.getElementById('s_imo').value,
      flag_state: document.getElementById('s_flag').value, vessel_type: document.getElementById('s_type').value,
      gross_tonnage: document.getElementById('s_gt').value, master_name: document.getElementById('s_master').value,
      company_name: document.getElementById('s_company').value, expected_arrival: arrival,
      departure: document.getElementById('s_departure').value, purpose: document.getElementById('s_purpose').value,
      agent_name: document.getElementById('s_agent').value, agent_email: document.getElementById('s_agentEmail').value,
      latitude: document.getElementById('s_lat').value, longitude: document.getElementById('s_lon').value
    });

    const callId = callData.call_id;
    const allDocs = [];

    for (const [dt, f] of Object.entries(pendingDocs)) {
      allDocs.push({ doc_type: dt, filename: f.filename, b64: f.b64 });
    }

    for (const entry of bulkFileMap) {
      if (entry.docType !== 'other') {
        const b64 = await readFileAsBase64(entry.file);
        allDocs.push({ doc_type: entry.docType, filename: entry.file.name, b64 });
      }
    }

    if (allDocs.length > 0) {
      status.innerHTML = `<span class="spinner"></span> Uploading ${allDocs.length} documents (background OCR)…`;
      await api('POST', `/api/vessels/${callId}/documents`, { docs: allDocs });

      status.innerHTML = `<span class="spinner"></span> Processing OCR in background…`;
      const result = await pollDocumentStatus(callId, (s) => {
        const docs = s.documents || {};
        const done = Object.values(docs).filter(d => d.ocr_status === 'done').length;
        const total = Object.values(docs).filter(d => d.ocr_status && d.ocr_status !== 'not_uploaded').length;
        if (total > 0) status.innerHTML = `<span class="spinner"></span> OCR ${done}/${total} documents complete…`;
      });
      if (!result.done) toast('OCR still running in background', 'warn');
    }

    status.innerHTML = '✅ Submitted successfully! Voyage ref: <strong>' + callData.voyage_ref + '</strong>';
    toast('Documents submitted — OCR processing started', 'ok');
    clearSubmitForm();
    loadDashboard();
    loadVessels();
  } catch (e) {
    status.innerHTML = '❌ ' + e.message;
    toast(e.message, 'err');
  }
  btn.disabled = false;
}
window.submitVesselAndDocs = submitVesselAndDocs;

window.clearSubmitForm = clearSubmitForm;

function clearSubmitForm() {
  ['s_name','s_imo','s_flag','s_type','s_gt','s_master','s_company','s_arrival','s_departure','s_purpose','s_agent','s_agentEmail']
    .forEach(id => { document.getElementById(id).value = ''; });
  const slots = ['pans','issc','csr','dos','crew_list','fal6','fal7','armed_guards','isps_checklist','pi_certificate','hull_machinery','ship_particulars'];
  const icons = { pans:'📋',issc:'📜',csr:'📑',dos:'✍️',crew_list:'👥',fal6:'👤',fal7:'☢️',armed_guards:'🛡️',isps_checklist:'☑️',pi_certificate:'📄',hull_machinery:'⚙️',ship_particulars:'🗂️'};
  const labels = { pans:'PANS',issc:'ISSC',csr:'CSR',dos:'Declaration of Security',crew_list:'IMO Crew List',fal6:'Passenger List',fal7:'Dangerous Goods',armed_guards:'Armed Guards',isps_checklist:'ISPS Checklist',pi_certificate:'P&I Certificate',hull_machinery:'Hull & Machinery',ship_particulars:'Ship Particulars'};
  slots.forEach(dt => {
    const slot = document.getElementById(`uslot-${dt}`);
    if (!slot) return;
    slot.classList.remove('uploaded');
    slot.querySelector('.ico').textContent = icons[dt] || '📄';
    slot.querySelector('.lbl').textContent = labels[dt] || dt;
  });
  pendingDocs = {};
  bulkFileMap = [];
  document.getElementById('submitStatus').style.display = 'none';
  document.getElementById('submitMapContainer').style.display = 'none';
  document.getElementById('s_lat').value = '';
  document.getElementById('s_lon').value = '';
  document.getElementById('bulkPreviewSection').classList.remove('show');
  document.getElementById('bulkFileInput').value = '';
  destroyMap('s_map');
}

function populateSubmitForEdit(d) {
  const v = d.vessel;
  document.getElementById('s_name').value = v.vessel_name || '';
  document.getElementById('s_imo').value = v.imo_number || '';
  document.getElementById('s_flag').value = v.flag_state || '';
  document.getElementById('s_type').value = v.vessel_type || '';
  document.getElementById('s_gt').value = v.gross_tonnage || '';
  document.getElementById('s_master').value = v.master_name || '';
  document.getElementById('s_company').value = v.company_name || '';
  document.getElementById('s_arrival').value = v.expected_arrival || '';
  document.getElementById('s_departure').value = v.departure || '';
  document.getElementById('s_purpose').value = v.purpose || '';
  document.getElementById('s_agent').value = v.agent_name || '';
  document.getElementById('s_agentEmail').value = v.agent_email || '';
  document.getElementById('s_lat').value = v.latitude || '';
  document.getElementById('s_lon').value = v.longitude || '';
  if (v.latitude && v.longitude) {
    document.getElementById('submitMapContainer').style.display = 'block';
    initLeafletMap('s_map', parseFloat(v.latitude), parseFloat(v.longitude), v.vessel_name, v.imo_number);
  }
}

// ── Review ────────────────────────────────────────────────────────────────────
async function loadReviewList() {
  try {
    const vessels = await api('GET', '/api/vessels');
    const relevant = vessels.filter(v => !['no_objection_issued','rejected'].includes(v.status));
    const list = document.getElementById('reviewVesselList');
    if (!relevant.length) { list.innerHTML = '<div class="empty-state"><div class="emo">✅</div><p>No vessels pending review.</p></div>'; return; }

    const submitted = relevant.filter(v => ['documents_submitted','documents_corrected','under_review'].includes(v.status));
    const discrepancies = relevant.filter(v => v.status === 'discrepancies_raised');
    const cleared = relevant.filter(v => v.status === 'cleared');
    const pending = relevant.filter(v => v.status === 'pending');

    function renderGroup(title, arr) {
      if (!arr.length) return '';
      return `
        <div style="margin-top:16px;margin-bottom:4px;font-weight:600;font-size:13px;color:var(--text2);text-transform:uppercase;letter-spacing:0.05em">${title} (${arr.length})</div>
        <div style="background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);margin-bottom:16px">
        ${arr.map((v, idx) => `
          <div style="display:flex;align-items:center;gap:12px;padding:12px 14px;${idx < arr.length - 1 ? 'border-bottom:1px solid var(--border);' : ''}cursor:pointer" onclick="openReviewById(${v.id})" onmouseover="this.style.background='var(--surface2)'" onmouseout="this.style.background='transparent'">
            <div style="flex:1"><strong style="font-size:14px">${v.imo_number ? 'IMO ' + v.imo_number + ' — ' : ''}${v.vessel_name}</strong><br>
            <span style="font-size:12px;color:var(--text2)">ETA: ${v.expected_arrival || '—'} · ${v.voyage_ref}</span></div>
            ${statusPill(v.status)}
          </div>`).join('')}</div>`;
    }

    list.innerHTML = renderGroup('Submitted for Review', submitted) + renderGroup('Discrepancies Raised', discrepancies) + renderGroup('Cleared', cleared) + renderGroup('Pending Documents', pending);
  } catch (e) {}
}
window.loadReviewList = loadReviewList;

async function openReviewById(id) {
  try {
    const d = await api('GET', `/api/vessels/${id}`);
    currentCallId = id;
    openReviewDetail(d);
  } catch (e) { toast(e.message, 'err'); }
}
window.openReviewById = openReviewById;

function openReviewDetail(d) {
  document.getElementById('reviewVesselPicker').style.display = 'none';
  document.getElementById('reviewDetail').style.display = 'block';
  api('GET', '/api/config/active-provider').then(cfg => {
    const badge = document.getElementById('reviewProviderBadge');
    const labels = { anthropic:'Claude', openai:'GPT', openrouter:'OpenRouter' };
    badge.textContent = 'AI: ' + (labels[cfg.provider] || cfg.provider) + ' · ' + (cfg.model || '');
  }).catch(() => {
    document.getElementById('reviewProviderBadge').textContent = 'AI provider not configured';
  });
  const v = d.vessel;
  document.getElementById('reviewVesselInfo').innerHTML = `
    <div class="card">
      <div class="vessel-name">${v.imo_number ? 'IMO ' + v.imo_number + ' — ' : ''}${v.vessel_name}</div>
      <div class="vessel-sub">${v.flag_state || ''} flag · ${v.vessel_type || ''} · Ref: ${v.voyage_ref}</div>
      <table class="bulk-map-table" style="margin-top:12px;border:1px solid var(--border);border-radius:var(--radius);overflow:hidden">
        <tbody>
          <tr><th style="width:25%;background:var(--surface2)">Master</th><td style="width:25%">${v.master_name || '—'}</td><th style="width:25%;background:var(--surface2)">Agent</th><td style="width:25%">${v.agent_name || '—'}</td></tr>
          <tr><th style="background:var(--surface2)">ETA</th><td>${v.expected_arrival || '—'}</td><th style="background:var(--surface2)">Departure</th><td>${v.departure || '—'}</td></tr>
          <tr><th style="background:var(--surface2)">Purpose</th><td>${v.purpose || '—'}</td><th style="background:var(--surface2)">Status</th><td>${statusPill(v.status)}</td></tr>
        </tbody>
      </table>
      ${v.latitude && v.longitude ? `
      <div style="margin-top:16px;border-top:1px solid var(--border);padding-top:16px">
        <div style="display:flex;align-items:center;margin-bottom:6px">
          <label style="font-size:10px;font-family:var(--mono);text-transform:uppercase;letter-spacing:0.06em;color:var(--text3)">🛰 Vessel Live GPS Position (aisstream.io)</label>
          ${v.imo_number ? `<button class="gps-refresh-btn" id="gpsRefreshBtnR" onclick="refreshGpsMap('r_map','${v.imo_number}','${v.vessel_name}','gpsRefreshBtnR','gpsCoordR')"><span>↻</span> Refresh Live</button>` : ''}
        </div>
        <div style="font-size:11px;color:var(--text3);font-family:var(--mono);margin-bottom:6px" id="gpsCoordR">📍 Stored: ${parseFloat(v.latitude).toFixed(4)}°N, ${parseFloat(v.longitude).toFixed(4)}°E</div>
        <div id="r_map" style="height:240px;border:1px solid var(--border2);border-radius:var(--radius)"></div>
      </div>` : `
      <div style="margin-top:16px;border-top:1px solid var(--border);padding-top:16px">
        <div style="font-size:12px;color:var(--text3);display:flex;align-items:center;gap:8px">
          📡 No GPS position stored.
          ${v.imo_number ? `<button class="gps-refresh-btn" id="gpsRefreshBtnR2" onclick="fetchAndShowGpsMap('r_map2','${v.imo_number}','${v.vessel_name}','gpsRefreshBtnR2','gpsCoordR2','reviewGpsWrapR')">↻ Fetch Live Position</button>` : ''}
        </div>
        <div style="font-size:11px;color:var(--text3);font-family:var(--mono);margin:4px 0 6px" id="gpsCoordR2"></div>
        <div id="reviewGpsWrapR" style="display:none"><div id="r_map2" style="height:240px;border:1px solid var(--border2);border-radius:var(--radius)"></div></div>
      </div>`}
    </div>`;
  if (v.latitude && v.longitude) {
    setTimeout(() => initLeafletMap('r_map', parseFloat(v.latitude), parseFloat(v.longitude), v.vessel_name, v.imo_number), 100);
  }

  const docs = d.documents || {};
  const docTypes = ['pans','issc','csr','dos','crew_list','armed_guards','isps_checklist','pi_certificate','hull_machinery','fal6','fal7','ship_particulars'];
  const docLabels = { pans:'PANS',issc:'ISSC',csr:'CSR',dos:'Declaration of Security',crew_list:'Crew List (FAL5)',armed_guards:'Armed Guards',isps_checklist:'ISPS Checklist',pi_certificate:'P&I Certificate',hull_machinery:'Hull & Machinery',fal6:'Passenger List (FAL6)',fal7:'Dangerous Goods (FAL7)',ship_particulars:'Ship Particulars'};

  const docRows = docTypes.map(dt => {
    const received = docs[`doc_${dt}_received`];
    const disc = docs[`doc_${dt}_discrepancy`];
    const detail = docs[`doc_${dt}_disc_detail`] || '';
    const corrective = docs[`doc_${dt}_corrective`] || '';
    if (!received) return `<div class="doc-review-row"><div class="doc-review-hdr"><div class="doc-type-label">${docLabels[dt] || dt}</div><span class="disc-status" style="background:#eee;color:#999">Not received</span></div></div>`;
    return `<div class="doc-review-row">
      <div class="doc-review-hdr" style="margin-bottom:${detail||corrective?'8px':'0'}">
        <div class="doc-type-label">${docLabels[dt]||dt}</div>
        <span class="disc-status ${disc?'ds-issue':'ds-ok'}">${disc?'⚠ Issue':'✓ OK'}</span>
      </div>
      ${detail?`<div style="font-size:12px;color:var(--fail);margin-bottom:6px">📌 ${detail}</div>`:''}
      ${corrective?`<div style="font-size:12px;color:var(--pass)">✔ Corrective: ${corrective}</div>`:''}
    </div>`;
  }).join('');
  document.getElementById('reviewDocStatus').innerHTML = `<div class="card"><div class="card-title">Document Status</div>${docRows}</div>`;

  if (docs.compliance_json) {
    try { renderComplianceResults(JSON.parse(docs.compliance_json), 'reviewCompliance'); } catch {}
  } else {
    document.getElementById('reviewCompliance').innerHTML = `<div class="card" style="text-align:center;padding:24px;color:var(--text2)">
      <div style="font-size:28px;margin-bottom:8px">🔍</div><p style="font-size:13px">Click "Run AI Analysis" to check ISPS compliance</p></div>`;
  }

  const discFormRows = docTypes.filter(dt => docs[`doc_${dt}_received`]).map(dt => `
    <div style="margin-bottom:14px;padding-bottom:14px;border-bottom:1px solid var(--border)">
      <div style="font-size:13px;font-weight:600;margin-bottom:8px">${docLabels[dt]||dt}</div>
      <div class="form-row">
        <div class="form-group"><label>Discrepancy Detail</label><textarea id="disc_${dt}" rows="2">${docs[`doc_${dt}_disc_detail`]||''}</textarea></div>
        <div class="form-group"><label>Corrective Action</label><textarea id="corr_${dt}" rows="2">${docs[`doc_${dt}_corrective`]||''}</textarea></div>
      </div>
      <label style="font-size:12px;color:var(--text2);cursor:pointer"><input type="checkbox" id="chk_${dt}" ${docs[`doc_${dt}_discrepancy`]?'checked':''}> Has discrepancy</label>
    </div>`).join('');

  document.getElementById('reviewDiscForm').innerHTML = docTypes.some(dt => docs[`doc_${dt}_received`])
    ? `<div class="card"><div class="card-title">Raise / Edit Discrepancies</div>${discFormRows}<button class="btn btn-warn" onclick="saveDiscrepancies()">Save Discrepancies</button><button class="btn btn-success" style="margin-left:8px" onclick="forwardForClearance()">Forward for Clearance →</button></div>`
    : '';
}
window.openReviewDetail = openReviewDetail;

async function runAnalysis() {
  const btn = document.getElementById('btnAnalyse');
  const spinner = document.getElementById('analyseSpinner');
  btn.disabled = true;
  spinner.style.display = 'inline-block';
  try {
    const cfg = await api('GET', '/api/config/active-provider');
    const provider = cfg.provider || 'anthropic';
    const data = await api('POST', `/api/vessels/${currentCallId}/analyse`, { provider });
    renderComplianceResults(data.result, 'reviewCompliance');
    toast('Analysis complete — overall: ' + data.overall, data.overall === 'pass' ? 'ok' : 'warn');
    const d = await api('GET', `/api/vessels/${currentCallId}`);
    openReviewDetail(d);
  } catch (e) { toast('Analysis failed: ' + e.message, 'err'); }
  btn.disabled = false;
  spinner.style.display = 'none';
}
window.runAnalysis = runAnalysis;

async function saveDiscrepancies() {
  const docTypes = ['pans','issc','csr','dos','crew_list','armed_guards','isps_checklist','pi_certificate','hull_machinery','fal6','fal7','ship_particulars'];
  for (const dt of docTypes) {
    const el = document.getElementById(`disc_${dt}`);
    if (!el) continue;
    const detail = el.value.trim();
    const corrective = (document.getElementById(`corr_${dt}`)||{}).value || '';
    const hasDisc = (document.getElementById(`chk_${dt}`)||{}).checked || false;
    if (detail || hasDisc) {
      await api('PATCH', `/api/vessels/${currentCallId}/discrepancy`, { doc_type: dt, disc_detail: detail, corrective_action: corrective, has_discrepancy: hasDisc }).catch(() => {});
    }
  }
  toast('Discrepancies saved', 'ok');
  const d = await api('GET', `/api/vessels/${currentCallId}`);
  openReviewDetail(d);
}
window.saveDiscrepancies = saveDiscrepancies;

async function forwardForClearance() {
  await saveDiscrepancies();
  await api('PATCH', `/api/vessels/${currentCallId}/status`, { status: 'cleared' });
  toast('Forwarded for ISPS Officer clearance', 'ok');
  loadReviewList();
}
window.forwardForClearance = forwardForClearance;

// ── No Objection ──────────────────────────────────────────────────────────────
async function loadNobjList() {
  try {
    const vessels = await api('GET', '/api/vessels');
    const relevant = vessels.filter(v => ['cleared','no_objection_issued','discrepancies_raised'].includes(v.status));
    const list = document.getElementById('nobjVesselList');
    if (!relevant.length) { list.innerHTML = '<div class="empty-state"><div class="emo">📭</div><p>No vessels ready for no-objection.</p></div>'; return; }
    const cleared = relevant.filter(v => v.status === 'cleared');
    const nobj = relevant.filter(v => v.status === 'no_objection_issued');
    const discrepancies = relevant.filter(v => v.status === 'discrepancies_raised');
    function renderGroup(title, arr) {
      if (!arr.length) return '';
      return `
        <div style="margin-top:16px;margin-bottom:4px;font-weight:600;font-size:13px;color:var(--text2);text-transform:uppercase;letter-spacing:0.05em">${title} (${arr.length})</div>
        <div style="background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);margin-bottom:16px">
        ${arr.map((v, idx) => `
          <div style="display:flex;align-items:center;gap:12px;padding:12px 14px;${idx < arr.length - 1 ? 'border-bottom:1px solid var(--border);' : ''}cursor:pointer" onclick="openNobjById(${v.id})" onmouseover="this.style.background='var(--surface2)'" onmouseout="this.style.background='transparent'">
            <div style="flex:1"><strong style="font-size:14px">${v.imo_number ? 'IMO ' + v.imo_number + ' — ' : ''}${v.vessel_name}</strong><br>
            <span style="font-size:12px;color:var(--text2)">ETA: ${v.expected_arrival || '—'} · ${v.voyage_ref}</span></div>
            ${statusPill(v.status)}
          </div>`).join('')}</div>`;
    }
    list.innerHTML = renderGroup('Cleared for No Objection', cleared) + renderGroup('No Objection Issued', nobj) + renderGroup('Discrepancies Raised', discrepancies);
  } catch (e) {}
}
window.loadNobjList = loadNobjList;

async function openNobjById(id) {
  try {
    const d = await api('GET', `/api/vessels/${id}`);
    currentCallId = id;
    openNobjDetail(d);
  } catch (e) { toast(e.message, 'err'); }
}
window.openNobjById = openNobjById;

function openNobjDetail(d) {
  document.getElementById('nobjVesselPicker').style.display = 'none';
  document.getElementById('nobjDetail').style.display = 'block';
  const v = d.vessel;
  document.getElementById('nobjVesselInfo').innerHTML = `
    <div class="card" style="margin-bottom:16px">
      <div class="vessel-name">${v.imo_number ? 'IMO ' + v.imo_number + ' — ' : ''}${v.vessel_name}</div>
      <div class="vessel-sub">${v.flag_state||''} · ${v.voyage_ref}</div>
      <div class="info-grid">
        <div class="info-field"><label>ETA</label><span>${v.expected_arrival||'—'}</span></div>
        <div class="info-field"><label>Purpose</label><span>${v.purpose||'—'}</span></div>
        <div class="info-field"><label>Agent</label><span>${v.agent_name||'—'} ${v.agent_email?'&lt;'+v.agent_email+'&gt;':''}</span></div>
        <div class="info-field"><label>Status</label><span>${statusPill(v.status)}</span></div>
      </div>
      ${v.latitude && v.longitude ? `
      <div style="margin-top:16px;border-top:1px solid var(--border);padding-top:16px">
        <div style="display:flex;align-items:center;margin-bottom:6px">
          <label style="font-size:10px;font-family:var(--mono);text-transform:uppercase;letter-spacing:0.06em;color:var(--text3)">🛰 Vessel Live GPS Position (aisstream.io)</label>
          ${v.imo_number ? `<button class="gps-refresh-btn" id="gpsRefreshBtnN" onclick="refreshGpsMap('n_map','${v.imo_number}','${v.vessel_name}','gpsRefreshBtnN','gpsCoordN')"><span>↻</span> Refresh Live</button>` : ''}
        </div>
        <div style="font-size:11px;color:var(--text3);font-family:var(--mono);margin-bottom:6px" id="gpsCoordN">📍 Stored: ${parseFloat(v.latitude).toFixed(4)}°N, ${parseFloat(v.longitude).toFixed(4)}°E</div>
        <div id="n_map" style="height:240px;border:1px solid var(--border2);border-radius:var(--radius)"></div>
      </div>` : `
      <div style="margin-top:16px;border-top:1px solid var(--border);padding-top:16px">
        <div style="font-size:12px;color:var(--text3);display:flex;align-items:center;gap:8px">
          📡 No GPS position stored.
          ${v.imo_number ? `<button class="gps-refresh-btn" id="gpsRefreshBtnN2" onclick="fetchAndShowGpsMap('n_map2','${v.imo_number}','${v.vessel_name}','gpsRefreshBtnN2','gpsCoordN2','nobjGpsWrapN')">↻ Fetch Live Position</button>` : ''}
        </div>
        <div style="font-size:11px;color:var(--text3);font-family:var(--mono);margin:4px 0 6px" id="gpsCoordN2"></div>
        <div id="nobjGpsWrapN" style="display:none"><div id="n_map2" style="height:240px;border:1px solid var(--border2);border-radius:var(--radius)"></div></div>
      </div>`}
    </div>`;
  if (v.latitude && v.longitude) {
    setTimeout(() => initLeafletMap('n_map', parseFloat(v.latitude), parseFloat(v.longitude), v.vessel_name, v.imo_number), 100);
  }
  const nobj = d.no_objection || {};
  document.getElementById('nobjPortSubj').value = nobj.email_port_subject || '';
  document.getElementById('nobjPortBody').value = nobj.email_port_body || '';
  document.getElementById('nobjAgentTo').textContent = v.agent_email ? `${v.agent_name||'Agent'} <${v.agent_email}>` : (v.agent_name||'Shipping Agent');
  document.getElementById('nobjAgentSubj').value = nobj.email_agent_subject || '';
  document.getElementById('nobjAgentBody').value = nobj.email_agent_body || '';
}
window.openNobjDetail = openNobjDetail;

function switchTab(which, el) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  el.classList.add('active');
  document.getElementById('emailTabPort').style.display = which === 'port' ? 'block' : 'none';
  document.getElementById('emailTabAgent').style.display = which === 'agent' ? 'block' : 'none';
}
window.switchTab = switchTab;

function copyEmailText(which) {
  const subj = document.getElementById(`nobj${which==='port'?'Port':'Agent'}Subj`).value;
  const body = document.getElementById(`nobj${which==='port'?'Port':'Agent'}Body`).value;
  navigator.clipboard.writeText('Subject: '+subj+'\n\n'+body).then(() => toast('Copied to clipboard','ok'));
}
window.copyEmailText = copyEmailText;

function openMailto(which) {
  const subj = document.getElementById(`nobj${which === 'port' ? 'Port' : 'Agent'}Subj`).value;
  const body = document.getElementById(`nobj${which === 'port' ? 'Port' : 'Agent'}Body`).value;
  const to = which === 'port' ? 'harbourmaster@hbport.lk' : (document.getElementById('nobjAgentTo').textContent || '');
  window.open(`mailto:${to}?subject=${encodeURIComponent(subj)}&body=${encodeURIComponent(body)}`);
}
window.openMailto = openMailto;

async function saveEmailDraft() {
  try {
    await api('PUT', `/api/vessels/${currentCallId}/no-objection`, {
      email_port_subject: document.getElementById('nobjPortSubj').value,
      email_port_body: document.getElementById('nobjPortBody').value,
      email_agent_subject: document.getElementById('nobjAgentSubj').value,
      email_agent_body: document.getElementById('nobjAgentBody').value
    });
    toast('Draft saved', 'ok');
  } catch (e) { toast(e.message, 'err'); }
}
window.saveEmailDraft = saveEmailDraft;

async function sendNobjEmail(which) {
  await saveEmailDraft();
  const subj = document.getElementById(`nobj${which==='port'?'Port':'Agent'}Subj`).value;
  const body = document.getElementById(`nobj${which==='port'?'Port':'Agent'}Body`).value;
  const to = which==='port'?'harbourmaster@hbport.lk':(document.getElementById('nobjAgentTo').textContent||'');
  window.open(`mailto:${to}?subject=${encodeURIComponent(subj)}&body=${encodeURIComponent(body)}`);
  try {
    await api('POST', `/api/vessels/${currentCallId}/no-objection/send`, { target: which });
    toast(`No-objection sent to ${which==='port'?'Port Authority':'Agent'}`, 'ok');
    loadNobjList();
  } catch (e) { toast(e.message, 'err'); }
}
window.sendNobjEmail = sendNobjEmail;

// ── Custom Rules ──────────────────────────────────────────────────────────────
async function loadRules() {
  try {
    const rules = await api('GET', '/api/rules');
    document.getElementById('ruleCount').textContent = rules.length;
    const list = document.getElementById('rulesList');
    if (!rules.length) { list.innerHTML = '<div style="font-size:13px;color:var(--text3);padding:8px 0">No custom rules yet.</div>'; return; }
    list.innerHTML = rules.map(r => `
      <div class="rule-item">
        <span class="rule-badge ${r.severity==='mandatory'?'rb-mandatory':'rb-advisory'}">${r.severity}</span>
        <div class="rule-body"><strong>${r.title}</strong><span>${r.description}</span>
          <div style="font-size:10px;color:var(--text3);margin-top:3px;font-family:var(--mono)">${r.category}</div></div>
        <button class="btn btn-sm" style="background:none;border:none;cursor:pointer;color:var(--text3)" onclick="deleteRule(${r.id})" title="Delete">✕</button>
      </div>`).join('');
  } catch (e) {}
}
window.loadRules = loadRules;

async function addRule() {
  const title = document.getElementById('rTitle').value.trim();
  const desc = document.getElementById('rDesc').value.trim();
  if (!title || !desc) { toast('Title and description required', 'err'); return; }
  try {
    await api('POST', '/api/rules', { title, description: desc, severity: document.getElementById('rSev').value, category: document.getElementById('rCat').value });
    document.getElementById('rTitle').value = '';
    document.getElementById('rDesc').value = '';
    loadRules();
    toast('Rule saved', 'ok');
  } catch (e) { toast(e.message, 'err'); }
}
window.addRule = addRule;

async function deleteRule(id) {
  try { await api('DELETE', `/api/rules/${id}`); loadRules(); toast('Rule deleted', ''); } catch (e) { toast(e.message, 'err'); }
}
window.deleteRule = deleteRule;

// ── Config ────────────────────────────────────────────────────────────────────
async function loadConfig() {
  try {
    const cfg = await api('GET', '/api/config');
    if (cfg.ANTHROPIC_API_KEY) document.getElementById('cfgAnthropicKey').placeholder = cfg.ANTHROPIC_API_KEY;
    if (cfg.OPENAI_API_KEY) document.getElementById('cfgOpenaiKey').placeholder = cfg.OPENAI_API_KEY;
    if (cfg.OPENROUTER_API_KEY) document.getElementById('cfgOpenrouterKey').placeholder = cfg.OPENROUTER_API_KEY;
    if (cfg.ACTIVE_PROVIDER) document.getElementById('cfgActiveProvider').value = cfg.ACTIVE_PROVIDER;
  } catch {}
}
window.loadConfig = loadConfig;

async function saveConfig() {
  const body = {};
  const a = document.getElementById('cfgAnthropicKey').value;
  const o = document.getElementById('cfgOpenaiKey').value;
  const r = document.getElementById('cfgOpenrouterKey').value;
  const ma = document.getElementById('cfgAnthropicModel').value;
  const mo = document.getElementById('cfgOpenaiModel').value;
  const mr = document.getElementById('cfgOpenrouterModel').value;
  const ast = document.getElementById('cfgAisstreamKey').value;
  if (a) body.ANTHROPIC_API_KEY = a;
  if (o) body.OPENAI_API_KEY = o;
  if (r) body.OPENROUTER_API_KEY = r;
  body.ANTHROPIC_MODEL = ma || '';
  body.OPENAI_MODEL = mo || '';
  body.OPENROUTER_MODEL = mr || '';
  body.ACTIVE_PROVIDER = document.getElementById('cfgActiveProvider').value;
  if (ast) body.AISTREAM_API_KEY = ast;
  try { await api('POST', '/api/config', body); toast('Configuration saved', 'ok'); } catch (e) { toast(e.message, 'err'); }
}
window.saveConfig = saveConfig;

async function loadConfigModels() {
  try {
    const res = await api('GET', '/api/config/models');
    const aSel = document.getElementById('cfgAnthropicModel');
    const oSel = document.getElementById('cfgOpenaiModel');
    const rSel = document.getElementById('cfgOpenrouterModel');
    function populate(sel, list) { sel.innerHTML = list.map(m => `<option value="${m}">${m}</option>`).join(''); }
    populate(aSel, res.anthropic || []);
    populate(oSel, res.openai || []);
    populate(rSel, res.openrouter || []);
    const cfg = await api('GET', '/api/config');
    if (cfg.ANTHROPIC_MODEL) aSel.value = cfg.ANTHROPIC_MODEL;
    if (cfg.OPENAI_MODEL) oSel.value = cfg.OPENAI_MODEL;
    if (cfg.OPENROUTER_MODEL) rSel.value = cfg.OPENROUTER_MODEL;
    if (cfg.ANTHROPIC_API_KEY) document.getElementById('cfgAnthropicKey').placeholder = cfg.ANTHROPIC_API_KEY;
    if (cfg.OPENAI_API_KEY) document.getElementById('cfgOpenaiKey').placeholder = cfg.OPENAI_API_KEY;
    if (cfg.OPENROUTER_API_KEY) document.getElementById('cfgOpenrouterKey').placeholder = cfg.OPENROUTER_API_KEY;
    if (cfg.AISTREAM_API_KEY) document.getElementById('cfgAisstreamKey').placeholder = cfg.AISTREAM_API_KEY;
    if (cfg.ACTIVE_PROVIDER) document.getElementById('cfgActiveProvider').value = cfg.ACTIVE_PROVIDER;
  } catch (e) { console.error('loadConfigModels error', e); }
}
window.loadConfigModels = loadConfigModels;

// ── LLM Call Logs ─────────────────────────────────────────────────────────────
async function loadLLMLogs() {
  try {
    const logs = await api('GET', '/api/llm-logs');
    const list = document.getElementById('llmLogsList');
    if (!logs.length) { list.innerHTML = '<div class="empty-state"><div class="emo">📡</div><p>No LLM calls recorded yet.</p></div>'; return; }
    const labels = { anthropic:'Claude', openai:'GPT', openrouter:'OpenRouter' };
    const statusHtml = s => {
      if (s === 'success') return '<span style="color:var(--pass)">● Success</span>';
      if (s === 'parse_error') return '<span style="color:var(--warn)">● Parse Error</span>';
      return '<span style="color:var(--fail)">● Error</span>';
    };
    list.innerHTML = logs.map(l => `
      <div class="llm-log-row" onclick="toggleLLMLog(this)">
        <div class="llm-log-hdr">
          <span style="font-size:11px;color:var(--text3);font-family:var(--mono);min-width:140px">${l.created_at||''}</span>
          <strong style="flex:1;font-size:13px">${l.vessel_name||'—'}</strong>
          <span style="font-size:11px;color:var(--text2);min-width:70px">${labels[l.provider]||l.provider}</span>
          <span style="font-size:10px;color:var(--text3);font-family:var(--mono);min-width:80px">${l.model||''}</span>
          <span style="min-width:80px">${statusHtml(l.status)}</span>
          <span style="font-size:11px;color:var(--text3);font-family:var(--mono);min-width:60px">${l.duration_ms?(l.duration_ms+'ms'):'—'}</span>
          <span style="font-size:10px;color:var(--text3)">${l.user_name||''}</span>
          <span style="font-size:16px;color:var(--text3);margin-left:auto">▸</span>
        </div>
        <div class="llm-log-body" style="display:none">
          ${l.error?`<div class="llm-log-section error"><strong>Error:</strong> ${l.error}</div>`:''}
          <div class="llm-log-section"><strong>Prompt:</strong><pre>${escHtml(l.prompt||'(truncated)')}</pre></div>
          <div class="llm-log-section"><strong>Response:</strong><pre>${escHtml(l.response||'(empty)')}</pre></div>
          ${l.status === 'parse_error' ? '<div class="llm-log-section warn"><strong>⚠ The LLM returned invalid JSON.</strong> Check the raw response above for formatting issues.</div>' : ''}
        </div>
      </div>`).join('');
  } catch (e) {
    document.getElementById('llmLogsList').innerHTML = '<div class="empty-state"><div class="emo">❌</div><p>Failed to load logs: '+e.message+'</p></div>';
  }
}
window.loadLLMLogs = loadLLMLogs;

function toggleLLMLog(el) {
  const body = el.querySelector('.llm-log-body');
  const arrow = el.querySelector('.llm-log-hdr span:last-child');
  if (body.style.display === 'none') { body.style.display = 'block'; if (arrow) arrow.textContent = '▾'; }
  else { body.style.display = 'none'; if (arrow) arrow.textContent = '▸'; }
}
window.toggleLLMLog = toggleLLMLog;

// ── IMO Lookup ────────────────────────────────────────────────────────────────
async function lookupImoData() {
  const imo = document.getElementById('s_imo').value.trim();
  if (!imo || !/^\d{7}$/.test(imo)) { toast('Enter a valid 7-digit IMO number', 'err'); return; }
  try {
    const d = await api('GET', '/api/vessels/lookup-imo/' + imo);
    if (d.error) throw new Error(d.error);
    document.getElementById('s_name').value = d.vessel_name || '';
    document.getElementById('s_gt').value = d.gross_tonnage || '';
    document.getElementById('s_type').value = d.vessel_type || '';
    document.getElementById('s_flag').value = d.flag_state || '';
    document.getElementById('s_lat').value = d.latitude || '';
    document.getElementById('s_lon').value = d.longitude || '';
    if (d.latitude && d.longitude) {
      document.getElementById('submitMapContainer').style.display = 'block';
      initLeafletMap('s_map', parseFloat(d.latitude), parseFloat(d.longitude), d.vessel_name, imo);
    }
    toast('Vessel data loaded', 'ok');
  } catch (e) { toast('Lookup failed: ' + (e.message || e), 'err'); }
}
window.lookupImoData = lookupImoData;

function checkImoAutoLookup() {
  const v = document.getElementById('s_imo').value.trim();
  if (/^\d{7}$/.test(v)) lookupImoData();
}
window.checkImoAutoLookup = checkImoAutoLookup;

// ── Bulk Upload ────────────────────────────────────────────────────────────────
const DOC_TYPE_PATTERNS = [
  { type:'pans', label:'PANS', patterns:['pans','pre-arrival','pre_arrival','prearr'] },
  { type:'issc', label:'ISSC', patterns:['issc','ship security cert','ship_security'] },
  { type:'csr', label:'CSR', patterns:['csr','continuous synopsis','synopsis'] },
  { type:'dos', label:'Declaration of Security', patterns:['dos','declaration of security','decl_sec','decl-sec'] },
  { type:'crew_list', label:'IMO Crew List (FAL5)', patterns:['crew','fal5','fal 5','fal_5','crew_list','crewlist'] },
  { type:'fal6', label:'Passenger List (FAL6)', patterns:['passenger','fal6','fal 6','fal_6','pax'] },
  { type:'fal7', label:'Dangerous Goods (FAL7)', patterns:['dangerous','fal7','fal 7','fal_7','dg','hazmat'] },
  { type:'armed_guards', label:'Armed Guards', patterns:['armed','guard','weapon','pcasp'] },
  { type:'isps_checklist', label:'ISPS Checklist', patterns:['checklist','isps_check','check_list','navy check'] },
  { type:'pi_certificate', label:'P&I Certificate', patterns:['p&i','p_i','pi_cert','protection indem','club cert','coe'] },
  { type:'hull_machinery', label:'Hull & Machinery', patterns:['hull','h&m','h_m','machinery','hm cert'] },
  { type:'ship_particulars', label:'Ship Particulars', patterns:['particular','vessel detail','ship_part','particulars'] }
];

function identifyDocType(filename) {
  const lower = filename.toLowerCase().replace(/[_\-\.]/g, ' ');
  for (const dt of DOC_TYPE_PATTERNS) {
    if (dt.patterns.some(p => lower.includes(p))) return dt;
  }
  return { type:'other', label:'Unknown — please select' };
}

function handleBulkDrop(e) {
  e.preventDefault();
  document.getElementById('bulkDropZone').classList.remove('drag-over');
  handleBulkFiles(e.dataTransfer.files);
}
window.handleBulkDrop = handleBulkDrop;

function handleBulkFiles(files) {
  if (!files || !files.length) return;
  bulkFileMap = [];
  const tbody = document.getElementById('bulkMapBody');
  tbody.innerHTML = '';

  const processFile = async (file, indexOffset) => {
    if (file.name.toLowerCase().endsWith('.zip')) {
      try { validateFileSize(file); } catch (e) { toast(e.message, 'err'); return []; }
      const reader = new FileReader();
      const arrayBuffer = await new Promise(resolve => { reader.onload = e => resolve(e.target.result); reader.readAsArrayBuffer(file); });
      const filesList = await extractZipFiles(arrayBuffer, file.name);
      return filesList.map((f, i) => ({ file: f.file, originalZip: file.name, zipIndex: i + indexOffset }));
    }
    try { validateFileSize(file); } catch (e) { toast(e.message, 'err'); return []; }
    return [{ file, originalZip: null, zipIndex: indexOffset }];
  };

  (async () => {
    const allFiles = [];
    let idx = 0;
    for (const file of Array.from(files)) {
      const extracted = await processFile(file, idx);
      allFiles.push(...extracted);
      idx += extracted.length;
    }
    allFiles.forEach((entry, i) => {
      const file = entry.file;
      const fromZip = entry.originalZip;
      const identified = identifyDocType(file.name);
      bulkFileMap.push({ file, docType: identified.type, label: identified.label, fromZip });
      const optionsHtml = DOC_TYPE_PATTERNS.map(dt =>
        `<option value="${dt.type}" ${dt.type === identified.type ? 'selected' : ''}>${dt.label}</option>`
      ).join('') + `<option value="other" ${identified.type === 'other' ? 'selected' : ''}>Other / Skip</option>`;
      const confidence = identified.type !== 'other' ? '✅ Auto-matched' : '❓ Unrecognized';
      const confColor = identified.type !== 'other' ? 'var(--pass)' : 'var(--warn)';
      tbody.innerHTML += `
        <tr id="brow-${i}">
          <td><div class="bulk-fname">${file.name}</div><div style="font-size:10px;color:var(--text3)">${(file.size/1024).toFixed(0)} KB${fromZip?'<br><span style="color:var(--navy);font-size:10px">From: '+fromZip+'</span>':''}</div></td>
          <td><span style="font-size:11px;color:${confColor};font-weight:600">${confidence}</span></td>
          <td><select style="font-size:12px;padding:4px 6px;border:1px solid var(--border2);border-radius:4px;background:var(--bg);font-family:var(--font)" onchange="bulkFileMap[${i}].docType=this.value;bulkFileMap[${i}].label=this.options[this.selectedIndex].text">${optionsHtml}</select></td>
          <td><button class="btn btn-sm" style="padding:3px 8px;background:none;border:1px solid var(--border2);font-size:11px" onclick="bulkFileMap.splice(${i},1);this.closest('tr').remove()">✕</button></td>
        </tr>`;
    });
    document.getElementById('bulkPreviewSection').classList.add('show');
  })();
}
window.handleBulkFiles = handleBulkFiles;

async function extractZipFiles(arrayBuffer, zipName) {
  const files = [];
  try {
    if (typeof JSZip === 'undefined') {
      await new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.src = 'https://cdn.jsdelivr.net/npm/jszip@3.10.1/dist/jszip.min.js';
        script.onload = resolve;
        script.onerror = reject;
        document.head.appendChild(script);
      });
    }
    const zip = await window.JSZip.loadAsync(arrayBuffer);
    for (const name of Object.keys(zip.files)) {
      const entry = zip.files[name];
      if (!entry.dir) {
        const blob = await entry.async('blob');
        files.push({ file: new File([blob], name), name });
      }
    }
  } catch (e) {
    console.error('ZIP extraction error:', e);
    toast('ZIP extraction failed: ' + e.message, 'err');
  }
  return files;
}

async function applyBulkMapping() {
  const docLabels = { pans:'PANS',issc:'ISSC',csr:'CSR',dos:'Declaration of Security',crew_list:'IMO Crew List',fal6:'Passenger List',fal7:'Dangerous Goods',armed_guards:'Armed Guards',isps_checklist:'ISPS Checklist',pi_certificate:'P&I Certificate',hull_machinery:'Hull & Machinery',ship_particulars:'Ship Particulars',other:'Other'};
  const docIcons = { pans:'📋',issc:'📜',csr:'📑',dos:'✍️',crew_list:'👥',fal6:'👤',fal7:'☢️',armed_guards:'🛡️',isps_checklist:'☑️',pi_certificate:'📄',hull_machinery:'⚙️',ship_particulars:'🗂️',other:'📁'};
  const toMap = bulkFileMap.filter(f => f.docType !== 'other');
  let applied = 0;
  for (const entry of toMap) {
    const { file, docType } = entry;
    const slotId = `uslot-${docType}`;
    const slot = document.getElementById(slotId);
    if (!slot) continue;
    await new Promise(resolve => {
      const reader = new FileReader();
      reader.onload = e => {
        const b64 = e.target.result.split(',')[1];
        pendingDocs[docType] = { file, b64, filename: file.name };
        slot.classList.add('uploaded');
        slot.querySelector('.ico').textContent = docIcons[docType]||'✅';
        slot.querySelector('.lbl').textContent = (docLabels[docType]||docType) + ' ✓';
        slot.querySelector('.sub').textContent = file.name.length > 22 ? file.name.substring(0,22)+'…' : file.name;
        applied++;
        resolve();
      };
      reader.readAsDataURL(file);
    });
  }
  document.getElementById('bulkPreviewSection').classList.remove('show');
  document.getElementById('bulkFileInput').value = '';
  bulkFileMap = [];
  toast(`Applied ${applied} file${applied!==1?'s':''} to document slots`, 'ok');
}
window.applyBulkMapping = applyBulkMapping;

// ── GPS Map Live Refresh ────────────────────────────────────────────────────────
async function refreshGpsMap(mapId, imo, vesselName, btnId, coordId) {
  const btn = document.getElementById(btnId);
  if (!btn) return;
  const origHtml = btn.innerHTML;
  btn.innerHTML = '<span class="spin">↻</span> Fetching…';
  btn.disabled = true;
  try {
    const d = await api('GET', '/api/vessels/lookup-imo/' + imo);
    if (d.latitude && d.longitude) {
      const lat = parseFloat(d.latitude);
      const lon = parseFloat(d.longitude);
      const coordEl = document.getElementById(coordId);
      if (coordEl) coordEl.textContent = `📍 Live: ${lat.toFixed(4)}°N, ${lon.toFixed(4)}°E (refreshed just now)`;
      initLeafletMap(mapId, lat, lon, vesselName, imo);
      toast('GPS position refreshed', 'ok');
    } else { toast('No live position returned', 'warn'); }
  } catch (e) { toast('GPS refresh failed: ' + e.message, 'err'); }
  btn.innerHTML = origHtml;
  btn.disabled = false;
}
window.refreshGpsMap = refreshGpsMap;

async function fetchAndShowGpsMap(mapId, imo, vesselName, btnId, coordId, wrapperId) {
  const btn = document.getElementById(btnId);
  if (!btn) return;
  const origHtml = btn.innerHTML;
  btn.innerHTML = '<span class="spin">↻</span> Fetching…';
  btn.disabled = true;
  try {
    const d = await api('GET', '/api/vessels/lookup-imo/' + imo);
    if (d.latitude && d.longitude) {
      const lat = parseFloat(d.latitude);
      const lon = parseFloat(d.longitude);
      const coordEl = document.getElementById(coordId);
      if (coordEl) coordEl.textContent = `📍 Live: ${lat.toFixed(4)}°N, ${lon.toFixed(4)}°E`;
      const wrapper = document.getElementById(wrapperId);
      if (wrapper) wrapper.style.display = 'block';
      setTimeout(() => initLeafletMap(mapId, lat, lon, vesselName, imo), 80);
      toast('Live GPS position fetched', 'ok');
    } else { toast('No live position returned from aisstream.io', 'warn'); }
  } catch (e) { toast('GPS fetch failed: ' + e.message, 'err'); }
  btn.innerHTML = origHtml;
  btn.disabled = false;
}
window.fetchAndShowGpsMap = fetchAndShowGpsMap;

// ── Init ──────────────────────────────────────────────────────────────────────
(async function () {
  if (getToken()) {
    const ok = await tryAutoLogin();
    if (ok) { initApp(); return; }
  }
  document.getElementById('authScreen').style.display = 'flex';
})();
