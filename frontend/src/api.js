/* Minimal API client for the SupportIQ backend. */

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000';

function authHeaders() {
  const token = localStorage.getItem('access');
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function api(path, { method = 'GET', body, form = false } = {}) {
  const headers = { ...authHeaders() };
  const opts = { method, headers };
  if (body !== undefined) {
    if (form) {
      opts.body = body; // FormData: browser sets the multipart boundary
    } else {
      headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
  }
  const res = await fetch(`${API}${path}`, opts);
  if (res.status === 401) {
    localStorage.removeItem('access');
    localStorage.removeItem('refresh');
    window.location.hash = '#/login';
    throw new Error('Session expired — please log in again.');
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || JSON.stringify(data));
  return data;
}

export const saveTokens = ({ access, refresh }) => {
  localStorage.setItem('access', access);
  localStorage.setItem('refresh', refresh);
};

export const isLoggedIn = () => !!localStorage.getItem('access');
export const logout = () => {
  localStorage.removeItem('access');
  localStorage.removeItem('refresh');
};

/* POST an SSE endpoint and invoke callbacks as events arrive. */
export async function postSSE(path, body, { onToken, onDone, onError }) {
  const res = await fetch(`${API}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const parts = buf.split('\n\n');
    buf = parts.pop();
    for (const part of parts) {
      for (const line of part.split('\n')) {
        if (!line.startsWith('data: ')) continue;
        const event = JSON.parse(line.slice(6));
        if (event.type === 'token') onToken(event.text);
        else if (event.type === 'done') onDone(event);
        else if (event.type === 'error') onError(event);
      }
    }
  }
}
