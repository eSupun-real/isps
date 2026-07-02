const API = '';
let authToken = localStorage.getItem('isps_token') || '';

export function setToken(token) {
  authToken = token;
  localStorage.setItem('isps_token', token);
}

export function clearToken() {
  authToken = '';
  localStorage.removeItem('isps_token');
}

export function getToken() {
  return authToken || localStorage.getItem('isps_token');
}

export async function api(method, path, body) {
  const token = getToken();
  const opts = {
    method,
    headers: { 'Content-Type': 'application/json' }
  };
  if (token) {
    opts.headers['Authorization'] = 'Bearer ' + token;
    if (!authToken) authToken = token;
  } else {
    console.warn(`[API] Missing JWT token for request to ${path}`);
  }
  if (body !== undefined) opts.body = JSON.stringify(body);
  const r = await fetch(API + path, opts);
  if (r.status === 401 && path !== '/api/auth/login' && path !== '/api/auth/me') {
    const { toast } = await import('./ui.js');
    toast('Session expired or invalid. Please log in again.', 'err');
    const { doLogout } = await import('./main.js');
    doLogout();
    throw new Error('Unauthorized');
  }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || r.statusText);
  return data;
}
