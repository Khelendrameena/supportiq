import { useEffect, useRef, useState } from 'react';
import { api, postSSE } from '../api.js';

/* Support inbox: streamed chat with citations. */

function Citations({ citations }) {
  if (!citations?.length) return null;
  return (
    <div className="mt-2 text-xs text-slate-500 border-t border-slate-200 pt-2">
      <div className="font-semibold mb-1">Sources</div>
      {citations.map((c) => (
        <div key={c.index} className="mb-0.5">
          [{c.index}] {c.document_title} · chunk {c.chunk_ord} · score {c.score}
        </div>
      ))}
    </div>
  );
}

function Skeleton({ className = '' }) {
  return <div className={`animate-pulse bg-slate-200 rounded ${className}`} />;
}

export default function Inbox() {
  const [kbs, setKbs] = useState([]);
  const [kbId, setKbId] = useState('');
  const [convos, setConvos] = useState([]);
  const [active, setActive] = useState(null); // conversation object
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [statusNote, setStatusNote] = useState(''); // cache hit / latency line
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const bottomRef = useRef(null);

  async function loadAll() {
    setLoading(true);
    setLoadError('');
    try {
      const [kbData, convoData] = await Promise.all([
        api('/api/kb/knowledge-bases/'),
        api('/api/chat/conversations/'),
      ]);
      const list = kbData.results || kbData;
      setKbs(list);
      if (list.length && !kbId) setKbId(String(list[0].id));
      setConvos(convoData.results || convoData);
    } catch (err) {
      setLoadError(err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { loadAll(); }, []);

  useEffect(() => bottomRef.current?.scrollIntoView({ behavior: 'smooth' }), [messages]);

  function openConvo(c) {
    setActive(c);
    setMessages(c.messages || []);
    setStatusNote('');
  }

  function newChat() {
    setActive(null);
    setMessages([]);
    setStatusNote('');
  }

  async function send(e) {
    e.preventDefault();
    const question = input.trim();
    if (!question || !kbId || streaming) return;
    setInput('');
    setStreaming(true);
    setStatusNote('');
    const userMsg = { role: 'user', text: question };
    setMessages((m) => [...m, userMsg, { role: 'assistant', text: '', streaming: true }]);

    let answer = '';
    const onToken = (t) => {
      answer += t;
      setMessages((m) => {
        const copy = [...m];
        copy[copy.length - 1] = { role: 'assistant', text: answer, streaming: true };
        return copy;
      });
    };
    const finish = (finalText, extra = {}) => {
      setMessages((m) => {
        const copy = [...m];
        copy[copy.length - 1] = { role: 'assistant', text: finalText, streaming: false, ...extra };
        return copy;
      });
      setStreaming(false);
    };

    try {
      await postSSE(
        '/api/chat/ask/',
        { kb_id: Number(kbId), question, conversation_id: active?.id },
        {
          onToken,
          onDone: (ev) => {
            finish(ev.answer, { citations: ev.citations, abstained: ev.abstained });
            const bits = [];
            if (ev.cache === 'HIT') bits.push('⚡ served from semantic cache');
            if (ev.latency_ms != null) bits.push(`${Math.round(ev.latency_ms)}ms`);
            setStatusNote(bits.join(' · '));
            if (!active) {
              // Refresh the conversation list so the new chat appears.
              api('/api/chat/conversations/').then((d) => setConvos(d.results || d)).catch(() => {});
              setActive({ id: ev.conversation_id });
            }
          },
          onError: (ev) => {
            const msg =
              ev.code === 'rate_limited'
                ? `Rate limited — retry in ${ev.retry_after}s.`
                : `Request blocked: ${ev.detail || ev.code}`;
            finish(msg);
          },
        },
      );
    } catch (err) {
      finish(`Error: ${err.message}`);
    }
  }

  if (loading) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-4 gap-6 h-[calc(100vh-140px)]">
        <div className="bg-white rounded-xl border p-4 space-y-2">
          <Skeleton className="h-9 w-full" />
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-12 w-full" />
        </div>
        <div className="md:col-span-3 bg-white rounded-xl border p-6 space-y-4">
          <Skeleton className="h-10 w-2/3" />
          <Skeleton className="h-10 w-1/2 ml-auto" />
          <Skeleton className="h-16 w-3/4" />
        </div>
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="bg-white rounded-xl border border-red-200 p-8 text-center max-w-md mx-auto mt-10">
        <p className="text-red-700 font-medium mb-1">Couldn't load the inbox</p>
        <p className="text-slate-500 text-sm mb-4">{loadError}</p>
        <button onClick={loadAll} className="bg-sky-600 hover:bg-sky-700 text-white text-sm px-5 py-2 rounded-lg">
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-4 gap-6 md:h-[calc(100vh-140px)]">
      <div className="bg-white rounded-xl border p-4 overflow-y-auto max-h-64 md:max-h-none">
        <button onClick={newChat} className="w-full bg-sky-600 hover:bg-sky-700 transition text-white text-sm font-medium rounded-lg py-2 mb-3">
          + New chat
        </button>
        <div className="text-xs font-semibold text-slate-500 mb-2 tracking-wide">PREVIOUS CHATS</div>
        {convos.length === 0 && (
          <p className="text-xs text-slate-400">No chats yet — ask your first question →</p>
        )}
        {convos.map((c) => (
          <button
            key={c.id}
            onClick={() => openConvo(c)}
            className={`w-full text-left text-sm p-2 rounded-lg mb-1 transition ${
              active?.id === c.id ? 'bg-sky-50 border border-sky-300' : 'hover:bg-slate-50 border border-transparent'
            }`}
          >
            <div className="truncate font-medium">{c.title || `Chat #${c.id}`}</div>
            <div className="text-xs text-slate-500 truncate">{c.kb_name}</div>
          </button>
        ))}
      </div>

      <div className="md:col-span-3 bg-white rounded-xl border flex flex-col min-h-[60vh] md:min-h-0 shadow-sm">
        <div className="p-4 border-b flex items-center gap-3 flex-wrap">
          <label className="text-sm text-slate-500">Knowledge base:</label>
          {kbs.length > 0 ? (
            <select
              value={kbId}
              onChange={(e) => setKbId(e.target.value)}
              className="border rounded-lg px-2 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-sky-500"
            >
              {kbs.map((kb) => (
                <option key={kb.id} value={kb.id}>{kb.name}</option>
              ))}
            </select>
          ) : (
            <a href="#/admin" className="text-sm text-sky-600 hover:underline">
              Create a knowledge base first →
            </a>
          )}
          {statusNote && <span className="text-xs text-slate-500 ml-auto">{statusNote}</span>}
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {messages.length === 0 && (
            <div className="text-center mt-10 max-w-sm mx-auto">
              <div className="text-4xl mb-3">💬</div>
              <p className="text-slate-500 text-sm">
                {kbs.length
                  ? 'Ask anything about the selected knowledge base. Answers stream in with cited sources — and the system abstains when the evidence isn\'t there.'
                  : 'Upload documents to a knowledge base first, then come back and ask away.'}
              </p>
            </div>
          )}
          {messages.map((m, i) => (
            <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div
                className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm shadow-sm ${
                  m.role === 'user' ? 'bg-sky-600 text-white rounded-br-md' : 'bg-slate-100 text-slate-900 rounded-bl-md'
                }`}
              >
                <div className="whitespace-pre-wrap leading-relaxed">
                  {m.text}
                  {m.streaming && <span className="animate-pulse">▍</span>}
                </div>
                {m.abstained && (
                  <div className="text-xs text-amber-700 mt-1.5 bg-amber-50 border border-amber-200 rounded px-2 py-1">
                    ⚠ abstained — no supporting evidence in the knowledge base
                  </div>
                )}
                <Citations citations={m.citations} />
              </div>
            </div>
          ))}
          <div ref={bottomRef} />
        </div>

        <form onSubmit={send} className="p-4 border-t flex gap-2">
          <input
            className="flex-1 border rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-sky-500 focus:border-sky-500 disabled:bg-slate-50"
            placeholder={kbs.length ? 'Ask a support question…' : 'Create a knowledge base first'}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={streaming || !kbs.length}
          />
          <button
            className="bg-sky-600 hover:bg-sky-700 transition text-white text-sm font-medium px-6 rounded-xl disabled:opacity-50"
            disabled={streaming || !kbId}
          >
            {streaming ? '…' : 'Send'}
          </button>
        </form>
      </div>
    </div>
  );
}
