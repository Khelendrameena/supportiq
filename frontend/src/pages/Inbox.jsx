import { useEffect, useRef, useState } from 'react';
import { api, postSSE } from '../api.js';

/* Support inbox: streamed chat with citations. */

function Citations({ citations }) {
  if (!citations?.length) return null;
  return (
    <div className="mt-2 text-xs text-slate-500 border-t pt-2">
      <div className="font-semibold mb-1">Sources</div>
      {citations.map((c) => (
        <div key={c.index} className="mb-0.5">
          [{c.index}] {c.document_title} · chunk {c.chunk_ord} · score {c.score}
        </div>
      ))}
    </div>
  );
}

export default function Inbox() {
  const [kbs, setKbs] = useState([]);
  const [kbId, setKbId] = useState('');
  const [convos, setConvos] = useState([]);
  const [active, setActive] = useState(null); // conversation object
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [cacheNote, setCacheNote] = useState('');
  const bottomRef = useRef(null);

  useEffect(() => {
    api('/api/kb/knowledge-bases/').then((d) => {
      const list = d.results || d;
      setKbs(list);
      if (list.length) setKbId(String(list[0].id));
    });
    api('/api/chat/conversations/').then((d) => setConvos(d.results || d));
  }, []);

  useEffect(() => bottomRef.current?.scrollIntoView({ behavior: 'smooth' }), [messages]);

  function openConvo(c) {
    setActive(c);
    setMessages(c.messages || []);
    setCacheNote('');
  }

  function newChat() {
    setActive(null);
    setMessages([]);
    setCacheNote('');
  }

  async function send(e) {
    e.preventDefault();
    const question = input.trim();
    if (!question || !kbId || streaming) return;
    setInput('');
    setStreaming(true);
    setCacheNote('');
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
            setCacheNote(
              ev.cache === 'HIT' ? `⚡ served from semantic cache in ${ev.latency_ms}ms` : '',
            );
            if (!active) {
              // Refresh the conversation list so the new chat appears.
              api('/api/chat/conversations/').then((d) => setConvos(d.results || d));
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

  return (
    <div className="grid grid-cols-4 gap-6 h-[calc(100vh-140px)]">
      <div className="col-span-1 bg-white rounded-lg border p-4 overflow-y-auto">
        <button onClick={newChat} className="w-full bg-sky-600 text-white text-sm rounded py-2 mb-3">
          + New chat
        </button>
        <div className="text-xs font-semibold text-slate-500 mb-2">PREVIOUS CHATS</div>
        {convos.map((c) => (
          <button
            key={c.id}
            onClick={() => openConvo(c)}
            className={`w-full text-left text-sm p-2 rounded mb-1 ${
              active?.id === c.id ? 'bg-sky-50 border border-sky-300' : 'hover:bg-slate-50 border border-transparent'
            }`}
          >
            <div className="truncate font-medium">{c.title || `Chat #${c.id}`}</div>
            <div className="text-xs text-slate-500">{c.kb_name}</div>
          </button>
        ))}
      </div>

      <div className="col-span-3 bg-white rounded-lg border flex flex-col">
        <div className="p-4 border-b flex items-center gap-3">
          <label className="text-sm text-slate-500">Knowledge base:</label>
          <select
            value={kbId}
            onChange={(e) => setKbId(e.target.value)}
            className="border rounded px-2 py-1 text-sm"
          >
            {kbs.map((kb) => (
              <option key={kb.id} value={kb.id}>{kb.name}</option>
            ))}
          </select>
          {cacheNote && <span className="text-xs text-green-700 ml-auto">{cacheNote}</span>}
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {messages.length === 0 && (
            <p className="text-slate-400 text-sm text-center mt-10">
              Ask anything about the selected knowledge base.<br />
              Answers stream in with cited sources.
            </p>
          )}
          {messages.map((m, i) => (
            <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div
                className={`max-w-[80%] rounded-lg px-4 py-2 text-sm ${
                  m.role === 'user' ? 'bg-sky-600 text-white' : 'bg-slate-100'
                }`}
              >
                <div className="whitespace-pre-wrap">
                  {m.text}
                  {m.streaming && <span className="animate-pulse">▍</span>}
                </div>
                {m.abstained && (
                  <div className="text-xs text-amber-700 mt-1">⚠ abstained — no supporting evidence</div>
                )}
                <Citations citations={m.citations} />
              </div>
            </div>
          ))}
          <div ref={bottomRef} />
        </div>

        <form onSubmit={send} className="p-4 border-t flex gap-2">
          <input
            className="flex-1 border rounded-lg px-4 py-2 text-sm"
            placeholder="Ask a support question…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={streaming}
          />
          <button
            className="bg-sky-600 hover:bg-sky-700 text-white text-sm px-6 rounded-lg disabled:opacity-50"
            disabled={streaming || !kbId}
          >
            Send
          </button>
        </form>
      </div>
    </div>
  );
}
