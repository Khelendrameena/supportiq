import { useEffect, useState } from 'react';
import { api } from '../api.js';

/* Tenant admin view: manage knowledge bases and ingest documents. */

const STATUS_COLOR = {
  pending: 'bg-yellow-100 text-yellow-800',
  processing: 'bg-blue-100 text-blue-800',
  ready: 'bg-green-100 text-green-800',
  failed: 'bg-red-100 text-red-800',
};

export default function Admin() {
  const [kbs, setKbs] = useState([]);
  const [selected, setSelected] = useState(null);
  const [docs, setDocs] = useState([]);
  const [newKb, setNewKb] = useState({ name: '', description: '' });
  const [budget, setBudget] = useState(null);
  const [uploading, setUploading] = useState(false);

  const loadKbs = () => api('/api/kb/knowledge-bases/').then((d) => setKbs(d.results || d));
  const loadDocs = (kbId) =>
    api(`/api/kb/documents/?kb=${kbId}`).then((d) => setDocs(d.results || d));

  useEffect(() => {
    loadKbs();
    api('/api/chat/budget/').then(setBudget).catch(() => {});
  }, []);

  useEffect(() => {
    if (selected) {
      loadDocs(selected.id);
      // Poll ingestion status until everything settles (simple + honest).
      const t = setInterval(() => loadDocs(selected.id), 3000);
      return () => clearInterval(t);
    }
  }, [selected]);

  async function createKb(e) {
    e.preventDefault();
    const kb = await api('/api/kb/knowledge-bases/', { method: 'POST', body: newKb });
    setNewKb({ name: '', description: '' });
    loadKbs();
    setSelected(kb);
  }

  async function upload(e) {
    const file = e.target.files[0];
    if (!file || !selected) return;
    setUploading(true);
    const form = new FormData();
    form.append('kb', selected.id);
    form.append('file', file);
    try {
      await api('/api/kb/documents/upload/', { method: 'POST', body: form, form: true });
      loadDocs(selected.id);
    } finally {
      setUploading(false);
      e.target.value = '';
    }
  }

  return (
    <div className="grid grid-cols-3 gap-6">
      <div className="col-span-1">
        <h2 className="font-semibold mb-3">Knowledge bases</h2>
        <div className="space-y-2 mb-4">
          {kbs.map((kb) => (
            <button
              key={kb.id}
              onClick={() => setSelected(kb)}
              className={`w-full text-left p-3 rounded-lg border ${
                selected?.id === kb.id ? 'border-sky-500 bg-sky-50' : 'bg-white hover:border-slate-400'
              }`}
            >
              <div className="font-medium">{kb.name}</div>
              <div className="text-xs text-slate-500">{kb.document_count} documents</div>
            </button>
          ))}
        </div>
        <form onSubmit={createKb} className="bg-white p-4 rounded-lg border">
          <h3 className="text-sm font-semibold mb-2">New knowledge base</h3>
          <input
            className="w-full border rounded px-2 py-1 mb-2 text-sm"
            placeholder="Name"
            value={newKb.name}
            onChange={(e) => setNewKb({ ...newKb, name: e.target.value })}
            required
          />
          <input
            className="w-full border rounded px-2 py-1 mb-2 text-sm"
            placeholder="Description"
            value={newKb.description}
            onChange={(e) => setNewKb({ ...newKb, description: e.target.value })}
          />
          <button className="w-full bg-sky-600 text-white text-sm rounded py-1.5">Create</button>
        </form>
        {budget && (
          <div className="mt-4 bg-white p-4 rounded-lg border text-sm">
            <div className="font-semibold mb-1">Token budget (this month)</div>
            <div className="text-slate-600">
              {budget.used.toLocaleString()} / {budget.limit.toLocaleString()} tokens
            </div>
          </div>
        )}
      </div>

      <div className="col-span-2">
        {selected ? (
          <>
            <div className="flex items-center justify-between mb-3">
              <h2 className="font-semibold">{selected.name} — documents</h2>
              <label className="bg-sky-600 hover:bg-sky-700 text-white text-sm px-4 py-2 rounded cursor-pointer">
                {uploading ? 'Uploading…' : 'Upload PDF / MD / TXT'}
                <input type="file" className="hidden" accept=".pdf,.md,.txt" onChange={upload} disabled={uploading} />
              </label>
            </div>
            <div className="space-y-2">
              {docs.map((doc) => (
                <div key={doc.id} className="bg-white p-4 rounded-lg border flex items-center justify-between">
                  <div>
                    <div className="font-medium">{doc.title}</div>
                    <div className="text-xs text-slate-500">
                      {doc.chunk_count} chunks
                      {doc.status === 'failed' && doc.error && (
                        <span className="text-red-600"> — {doc.error}</span>
                      )}
                    </div>
                  </div>
                  <span className={`text-xs px-2 py-1 rounded-full ${STATUS_COLOR[doc.status]}`}>
                    {doc.status}
                  </span>
                </div>
              ))}
              {docs.length === 0 && (
                <p className="text-slate-500 text-sm">No documents yet. Upload one to get started.</p>
              )}
            </div>
          </>
        ) : (
          <p className="text-slate-500">Select a knowledge base, or create one.</p>
        )}
      </div>
    </div>
  );
}
