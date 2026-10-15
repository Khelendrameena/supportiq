import { useEffect, useState } from 'react';
import { api, isLoggedIn, logout, saveTokens } from './api.js';
import Admin from './pages/Admin.jsx';
import Inbox from './pages/Inbox.jsx';

function useHashRoute() {
  const [route, setRoute] = useState(window.location.hash || '#/');
  useEffect(() => {
    const onChange = () => setRoute(window.location.hash || '#/');
    window.addEventListener('hashchange', onChange);
    return () => window.removeEventListener('hashchange', onChange);
  }, []);
  return route;
}

function Nav({ me, route }) {
  const isAdmin = route.startsWith('#/admin');
  const tab = (active) =>
    active ? 'text-white font-semibold' : 'text-slate-400 hover:text-sky-300';
  return (
    <nav className="bg-slate-900 text-white px-4 sm:px-6 py-3 flex items-center justify-between sticky top-0 z-10">
      <a href="#/" className="font-bold text-lg shrink-0">
        Support<span className="text-sky-400">IQ</span>
      </a>
      <div className="flex items-center gap-3 sm:gap-5 text-sm">
        <a href="#/" className={tab(!isAdmin)}>Inbox</a>
        <a href="#/admin" className={tab(isAdmin)}>Knowledge Base</a>
        <span className="text-slate-400 hidden sm:inline truncate max-w-[160px]" title={me?.tenant?.name}>
          {me?.tenant?.name}
        </span>
        <button
          onClick={() => { logout(); window.location.hash = '#/login'; }}
          className="bg-slate-700 hover:bg-slate-600 px-3 py-1 rounded"
        >
          Log out
        </button>
      </div>
    </nav>
  );
}

function AuthPage() {
  const [mode, setMode] = useState('login'); // 'login' | 'register'
  const [form, setForm] = useState({ tenant_name: '', tenant_slug: '', email: '', password: '' });
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  async function submit(e) {
    e.preventDefault();
    if (busy) return; // no double-submit
    setError('');
    setBusy(true);
    try {
      if (mode === 'register') {
        const data = await api('/api/auth/register/', { method: 'POST', body: form });
        saveTokens(data);
      } else {
        const data = await api('/api/auth/token/', {
          method: 'POST',
          body: { username: form.email, password: form.password },
        });
        saveTokens(data);
      }
      window.location.hash = '#/';
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const input = 'w-full border border-slate-300 rounded px-3 py-2 mb-3';

  return (
    <div className="min-h-screen flex items-center justify-center px-4 bg-gradient-to-b from-slate-100 to-slate-200">
      <form onSubmit={submit} className="bg-white p-8 rounded-2xl shadow-lg w-full max-w-sm">
        <h1 className="text-2xl font-bold mb-1">
          Support<span className="text-sky-500">IQ</span>
        </h1>
        <p className="text-slate-500 text-sm mb-6">
          {mode === 'register' ? 'Create your support workspace' : 'Log in to your workspace'}
        </p>
        {mode === 'register' && (
          <>
            <input className={input} placeholder="Company name" value={form.tenant_name} onChange={set('tenant_name')} required />
            <input className={input} placeholder="Workspace slug (e.g. acme)" value={form.tenant_slug} onChange={set('tenant_slug')} required pattern="[a-z0-9-]+" title="Lowercase letters, numbers and hyphens only" />
          </>
        )}
        <input className={input} placeholder="Email" type="email" value={form.email} onChange={set('email')} required />
        <input className={input} placeholder="Password" type="password" value={form.password} onChange={set('password')} required />
        {error && <p className="text-red-600 text-sm mb-3 bg-red-50 border border-red-200 rounded-lg px-3 py-2">{error}</p>}
        <button
          disabled={busy}
          className="w-full bg-sky-600 hover:bg-sky-700 disabled:opacity-60 text-white rounded-lg py-2 font-medium transition"
        >
          {busy ? (mode === 'register' ? 'Creating workspace…' : 'Logging in…') : (mode === 'register' ? 'Create workspace' : 'Log in')}
        </button>
        <button
          type="button"
          onClick={() => setMode(mode === 'register' ? 'login' : 'register')}
          className="w-full text-center text-sm text-sky-600 mt-3 hover:underline"
        >
          {mode === 'register' ? 'Already have a workspace? Log in' : 'New here? Create a workspace'}
        </button>
      </form>
    </div>
  );
}

export default function App() {
  const route = useHashRoute();
  const [me, setMe] = useState(null);

  useEffect(() => {
    if (isLoggedIn()) api('/api/auth/me/').then(setMe).catch(() => {});
  }, [route]);

  if (!isLoggedIn()) return <AuthPage />;

  return (
    <div className="min-h-screen">
      <Nav me={me} route={route} />
      <main className="max-w-6xl mx-auto p-4 sm:p-6">
        {route.startsWith('#/admin') ? <Admin /> : <Inbox />}
      </main>
    </div>
  );
}
