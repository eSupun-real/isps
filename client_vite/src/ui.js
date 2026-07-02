export function toast(msg, type) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast ' + (type || '');
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 2800);
}

export function statusPill(s) {
  const map = {
    pending: 's-pending', documents_submitted: 's-submitted', under_review: 's-review',
    discrepancies_raised: 's-disc', documents_corrected: 's-review',
    cleared: 's-cleared', no_objection_issued: 's-noi', rejected: 's-rejected'
  };
  const label = (s || '').replace(/_/g, ' ');
  return `<span class="status-pill ${map[s] || 's-pending'}">${label}</span>`;
}

export function escHtml(s) {
  if (!s) return '';
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

export function vesselTableHTML(vessels, compact) {
  if (!vessels.length) return '<div class="empty-state" style="padding:32px"><div class="emo">🚢</div><p>No vessel calls found.</p></div>';
  const rows = vessels.map(v => `
    <tr onclick="window.openVessel(${v.id})">
      <td><strong>${v.imo_number ? 'IMO ' + v.imo_number + ' — ' : ''}${v.vessel_name}</strong></td>
      <td><span style="font-size:11px;font-family:var(--mono)">${v.imo_number || '—'}</span></td>
      ${compact ? '' : `<td>${v.flag_state || '—'}</td><td>${v.vessel_type || '—'}</td>`}
      <td>${v.expected_arrival ? v.expected_arrival.substring(0, 10) : '—'}</td>
      <td>${statusPill(v.status)}</td>
      <td style="font-size:11px;color:var(--text2)">${v.voyage_ref || '—'}</td>
    </tr>`).join('');
  return `<table><thead><tr>
    <th>Vessel</th><th>IMO Number</th>
    ${compact ? '' : '<th>Flag</th><th>Type</th>'}
    <th>ETA</th><th>Status</th><th>Voyage Ref</th>
  </tr></thead><tbody>${rows}</tbody></table>`;
}

let maps = {};

export function initLeafletMap(id, lat, lon, name, imo) {
  try {
    if (maps[id]) { try { maps[id].remove(); } catch (e) {} }
    const map = L.map(id).setView([lat, lon], 12);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; OpenStreetMap contributors'
    }).addTo(map);
    L.marker([lat, lon]).addTo(map)
      .bindPopup(`<strong>${imo ? 'IMO ' + imo + ' — ' : ''}${name || ''}</strong>`)
      .openPopup();
    maps[id] = map;
  } catch (e) { console.error('Leaflet init error', e); }
}

export function destroyMap(id) {
  if (maps[id]) {
    try { maps[id].remove(); delete maps[id]; } catch (e) {}
  }
}

export function getMaps() { return maps; }

export function renderComplianceResults(parsed, targetId) {
  const checks = parsed.checks || [];
  const flags = parsed.flags || [];
  const overall = parsed.overall || 'pass';
  const obClass = overall === 'pass' ? 'ob-pass' : overall === 'warn' ? 'ob-warn' : 'ob-fail';
  const obIcon = overall === 'pass' ? '✅' : overall === 'warn' ? '⚠️' : '🚫';
  const obText = overall === 'pass' ? 'All checks passed — No Objection may be issued'
    : overall === 'warn' ? 'Passed with warnings — Conditional clearance'
    : 'Issues found — No Objection withheld';
  const pass = checks.filter(c => c.status === 'pass').length;
  const fail = checks.filter(c => c.status === 'fail').length;
  const warn = checks.filter(c => c.status === 'warn').length;

  function chkIco(s) {
    if (s === 'pass') return `<svg class="check-ico" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2"><circle cx="10" cy="10" r="8"/><path d="M6.5 10l2.5 2.5 4.5-5"/></svg>`;
    if (s === 'fail') return `<svg class="check-ico" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2"><circle cx="10" cy="10" r="8"/><path d="M7 7l6 6M13 7l-6 6"/></svg>`;
    return `<svg class="check-ico" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2"><path d="M10 3l8 14H2z"/><path d="M10 9v4M10 15h.01"/></svg>`;
  }

  const flagsHTML = flags.length ? `
    <div style="margin-bottom:14px">
      <div style="font-size:12px;font-weight:600;color:var(--fail);margin-bottom:8px">🚩 ${flags.length} Discrepanc${flags.length > 1 ? 'ies' : 'y'} Flagged</div>
      ${flags.map(f => `<div class="flag-item ${f.severity === 'warn' ? 'warn' : ''}"><div class="flag-lbl">${f.severity === 'fail' ? '🚫' : '⚠️'} ${f.label}</div><div class="flag-detail">${f.detail}</div></div>`).join('')}
    </div>` : '';

  document.getElementById(targetId).innerHTML = `
    <div class="card">
      <div class="card-title">AI Compliance Analysis</div>
      <div class="overall-banner ${obClass}">
        <span style="font-size:20px">${obIcon}</span> ${obText}
        <span style="margin-left:auto;font-size:12px;font-weight:400">${pass} pass · ${warn} warn · ${fail} fail</span>
      </div>
      ${flagsHTML}
      <div class="checks-grid">
        ${checks.map(c => `<div class="check-item ${c.status}">${chkIco(c.status)}<div class="check-label"><strong>${c.label}</strong><span>${c.note || ''}</span></div></div>`).join('')}
      </div>
      ${(parsed.custom_checks || []).length ? `
        <div class="section-label" style="margin-top:14px">Custom Rule Results</div>
        <div class="checks-grid">
          ${(parsed.custom_checks || []).map(c => `<div class="check-item ${c.status}">${chkIco(c.status)}<div class="check-label"><strong>${c.label}</strong><span>${c.note || ''}</span></div></div>`).join('')}
        </div>` : ''}
    </div>`;
}
