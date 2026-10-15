import { useEffect, useRef, useState } from 'react';
import { api } from '../api.js';

/* Tenant admin view: manage knowledge bases and ingest documents. */

const STATUS_STYLE = {
  pending: 'bg-yellow-100 text-yellow-800 border-yellow-200',
  processing: 'bg-blue-100 text-blue-800 border-blue-200',
  ready: 'bg-green-100 text-green-800 border-green-200',
  failed: 'bg-red-100 text-red-800 border-red-200',
};

const SETTLED = new Set(['ready', 'failed']);

function BudgetBar({ budget }) {
  if (!budget) return null;
  const pct = Math.min(100, (budget.used / Math.max(1, budget.limit)) * 100);
  const over = budget.used >= budget.limit;
  return (
    <div className="mt-4 bg-white p-4 rounded-xl border text-sm shadow-sm">
      <div className="font-semibold mb-1">Token budget <span className="font-normal text-slate-500">(this month)</span></div>
      <div className="text-slate-600 mb-2">
        {budget.used.toLocaleString()} / {budget.limit.toLocaleString()} tokens
      </div>
      <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${over ? 'bg-red-500' : pct > 80 ? 'bg-amber-500' : 'bg-sky-500'}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      {over && <p className="text-red-600 text-xs mt-1.5">Budget exhausted — answers are blocked until next month.</p>}
    </div>
  );
}

export default function Admin() {
  const [kbs, setKbs] = useState([]);
  const [selected, setSelected] = useState(null);
  const [docs, setDocs] = useState([]);
  const [newKb, setNewKb] = useState({ name: '', description: '' });
  const [budget, setBudget] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const pollRef = useRef(null);

  async function loadKbs() {
    const d = await api('/api/kb/knowledge-bases/');
    setKbs(d.results || d);
  }

  async function loadDocs(kbId) {
    const d = await api(`/api/kb/documents/?kb=${kbId}`);
    const list = d.results || d;
    setDocs(list);
    return list;
  }

  useEffect(() => {
    (async () => {
      try {
        await loadKbs();
        const b = await api('/api/chat/budget/').catch(() => null);
        setBudget(b);
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  // Poll ingestion status, but stop once every doc has settled.
  useEffect(() => {
    clearInterval(pollRef.current);
    if (!selected) return;
    loadDocs(selected.id).catch(() => {});
    pollRef.current = setInterval(async () => {
      try {
        const list = await loadDocs(selected.id);
        if (list.every((d) => SETTLED.has(d.status))) clearInterval(pollRef.current);
      } catch {
        clearInterval(pollRef.current);
      }
    }, 3000);
    return () => clearInterval(pollRef.current);
  }, [selected]);

  async function createKb(e) {
    e.preventDefault();
    setNotice('');
    try {
      const kb = await api('/api/kb/knowledge-bases/', { method: 'POST', body: newKb });
      setNewKb({ name: '', description: '' });
      await loadKbs();
      setSelected(kb);
    } catch (err) {
      setNotice(`Couldn't create knowledge base: ${err.message}`);
    }
  }

  async function upload(e) {
    const file = e.target.files[0];
    if (!file || !selected) return;
    setUploading(true);
    setNotice('');
    const form = new FormData();
    form.append('kb', selected.id);
    form.append('file', file);
    try {
      await api('/api/kb/documents/upload/', { method: 'POST', body: form, form: true });
      await loadDocs(selected.id);
    } catch (err) {
      setNotice(`Upload failed: ${err.message}`);
    } finally {
      setUploading(false);
      e.target.value = '';
    }
  }

  async function retryDoc(doc) {
    setNotice('');
    try {
      await api(`/api/kb/documents/${doc.id}/reingest/`, { method: 'POST' });
      await loadDocs(selected.id);
    } catch (err) {
      setNotice(`Couldn't re-queue ingestion: ${err.message}`);
    }
  }

  if (loading) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="space-y-2">
          {[0, 1].map((i) => <div key={i} className="animate-pulse bg-slate-200 rounded-xl h-16" />)}
        </div>
        <div className="md:col-span-2 space-y-2">
          {[0, 1, 2].map((i) => <div key={i} className="animate-pulse bg-slate-200 rounded-xl h-20" />)}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-white rounded-xl border border-red-200 p-8 text-center max-w-md mx-auto mt-10">
        <p className="text-red-700 font-medium mb-1">Couldn't load knowledge bases</p>
        <p className="text-slate-500 text-sm mb-4">{error}</p>
        <button onClick={() => window.location.reload()} className="bg-sky-600 hover:bg-sky-700 text-white text-sm px-5 py-2 rounded-lg">
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
      <div>
        <h2 className="font-semibold mb-3">Knowledge bases</h2>
        {kbs.length === 0 && (
          <p className="text-sm text-slate-400 mb-4">None yet — create your first one below.</p>
        )}
        <div className="space-y-2 mb-4">
          {kbs.map((kb) => (
            <button
              key={kb.id}
              onClick={() => setSelected(kb)}
              className={`w-full text-left p-3 rounded-xl border transition shadow-sm ${
                selected?.id === kb.id ? 'border-sky-500 bg-sky-50' : 'bg-white hover:border-slate-400'
              }`}
            >
              <div className="font-medium">{kb.name}</div>
              <div className="text-xs text-slate-500">{kb.document_count} document{kb.document_count === 1 ? '' : 's'}</div>
            </button>
          ))}
        </div>
        <form onSubmit={createKb} className="bg-white p-4 rounded-xl border shadow-sm">
          <h3 className="text-sm font-semibold mb-2">New knowledge base</h3>
          <input
            className="w-full border rounded-lg px-2.5 py-1.5 mb-2 text-sm focus:outline-none focus:ring-2 focus:ring-sky-500"
            placeholder="Name"
            value={newKb.name}
            onChange={(e) => setNewKb({ ...newKb, name: e.target.value })}
            required
          />
          <input
            className="w-full border rounded-lg px-2.5 py-1.5 mb-2 text-sm focus:outline-none focus:ring-2 focus:ring-sky-500"
            placeholder="Description (optional)"
            value={newKb.description}
            onChange={(e) => setNewKb({ ...newKb, description: e.target.value })}
          />
          <button className="w-full bg-sky-600 hover:bg-sky-700 transition text-white text-sm font-medium rounded-lg py-1.5">
            Create
          </button>
        </form>
        <BudgetBar budget={budget} />
      </div>

      <div className="md:col-span-2">
        {notice && (
          <div className="mb-3 text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded-xl px-4 py-2.5">
            {notice}
          </div>
        )}
        {selected ? (
          <>
            <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
              <h2 className="font-semibold">{selected.name} <span className="font-normal text-slate-500">— documents</span></h2>
              <label className={`text-white text-sm font-medium px-4 py-2 rounded-lg cursor-pointer transition ${uploading ? 'bg-slate-400' : 'bg-sky-600 hover:bg-sky-700'}`}>
                {uploading ? 'Uploading…' : 'Upload PDF / MD / TXT'}
                <input type="file" className="hidden" accept=".pdf,.md,.txt" onChange={upload} disabled={uploading} />
              </label>
            </div>
            <div className="space-y-2">
              {docs.map((doc) => (
                <div key={doc.id} className="bg-white p-4 rounded-xl border shadow-sm flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <div className="font-medium truncate">{doc.title}</div>
                    <div className="text-xs text-slate-500">
                      {doc.chunk_count} chunk{doc.chunk_count === 1 ? '' : 's'}
                      {doc.status === 'failed' && doc.error && (
                        <span className="text-red-600"> — {doc.error}</span>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    {doc.status === 'failed' && (
                      <button
                        onClick={() => retryDoc(doc)}
                        className="text-xs font-medium text-sky-700 hover:text-sky-900 border border-sky-200 hover:border-sky-400 rounded-full px-3 py-1 transition"
                      >
                        Retry
                      </button>
                    )}
                    <span className={`text-xs font-medium px-2.5 py-1 rounded-full border ${STATUS_STYLE[doc.status] || 'bg-slate-100 text-slate-700 border-slate-200'}`}>
                      {doc.status}
                    </span>
                  </div>
                </div>
              ))}
              {docs.length === 0 && (
                <div className="text-center py-10 border border-dashed border-slate-300 rounded-xl">
                  <p className="text-slate-500 text-sm">No documents yet.<br />Upload a PDF, Markdown or text file to get started.</p>
                </div>
              )}
            </div>
          </>
        ) : (
          <div className="text-center py-16 border border-dashed border-slate-300 rounded-xl">
            <p className="text-slate-500 text-sm">Select a knowledge base, or create one to begin.</p>
          </div>
        )}
      </div>
    </div>
  );
}
