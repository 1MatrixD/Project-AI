"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, streamSse } from "@/lib/api";
import type { Chat, ChatMessage } from "@/lib/types";

const MODELS = [
  { key: "opus", label: "Opus 5" },
  { key: "sonnet", label: "Sonnet" },
  { key: "haiku", label: "Haiku" },
];
const REASONING = [
  { key: "none", label: "Без размышлений" },
  { key: "low", label: "Лёгкий" },
  { key: "medium", label: "Средний" },
  { key: "high", label: "Глубокий" },
];

type LiveState = {
  streaming: boolean;
  text: string;
  tools: string[];
  error: string | null;
};

export default function ChatTab({ projectId }: { projectId: string }) {
  const [chats, setChats] = useState<Chat[]>([]);
  const [chat, setChat] = useState<Chat | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [live, setLive] = useState<LiveState>({ streaming: false, text: "", tools: [], error: null });
  const bottomRef = useRef<HTMLDivElement | null>(null);

  const loadChats = useCallback(async () => {
    const cs = await api<Chat[]>(`/projects/${projectId}/chats`);
    setChats(cs);
    return cs;
  }, [projectId]);

  useEffect(() => {
    loadChats().then((cs) => {
      if (cs.length) selectChat(cs[0]);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, live.text]);

  async function selectChat(c: Chat) {
    setChat(c);
    setMessages(await api<ChatMessage[]>(`/projects/${projectId}/chats/${c.id}/messages`));
  }

  async function newChat() {
    const c = await api<Chat>(`/projects/${projectId}/chats`, { method: "POST", body: JSON.stringify({}) });
    await loadChats();
    setChat(c);
    setMessages([]);
  }

  async function updateChatSettings(patch: Partial<Chat>) {
    if (!chat) return;
    const updated = await api<Chat>(`/projects/${projectId}/chats/${chat.id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    });
    setChat(updated);
    loadChats();
  }

  async function send(e: React.FormEvent) {
    e.preventDefault();
    if (!input.trim() || live.streaming) return;
    let current = chat;
    if (!current) {
      current = await api<Chat>(`/projects/${projectId}/chats`, { method: "POST", body: JSON.stringify({}) });
      setChat(current);
      loadChats();
    }
    const content = input.trim();
    setInput("");
    setMessages((m) => [
      ...m,
      { id: `tmp-${Date.now()}`, role: "user", content, meta: {}, created_at: new Date().toISOString() },
    ]);
    setLive({ streaming: true, text: "", tools: [], error: null });

    try {
      await streamSse(
        `/projects/${projectId}/chats/${current.id}/messages`,
        { content },
        (ev) => {
          if (ev.type === "delta" && ev.text) {
            setLive((s) => ({ ...s, text: s.text + ev.text }));
          } else if (ev.type === "tool" && ev.name) {
            setLive((s) => ({ ...s, tools: [...s.tools, ev.name!] }));
          } else if (ev.type === "error") {
            setLive((s) => ({ ...s, error: ev.detail ?? "Ошибка" }));
          }
        }
      );
    } catch (err) {
      setLive((s) => ({ ...s, error: err instanceof Error ? err.message : "Ошибка" }));
    } finally {
      const msgs = await api<ChatMessage[]>(`/projects/${projectId}/chats/${current.id}/messages`).catch(() => null);
      if (msgs) setMessages(msgs);
      setLive((s) => ({ streaming: false, text: "", tools: [], error: s.error }));
      loadChats();
    }
  }

  return (
    <div className="flex gap-3 h-[calc(100vh-160px)] min-h-96">
      <div className="w-56 card p-3 space-y-2 overflow-y-auto shrink-0 hidden md:block">
        <button className="btn w-full justify-center text-sm" onClick={newChat}>+ Новый чат</button>
        {chats.map((c) => (
          <button
            key={c.id}
            onClick={() => selectChat(c)}
            className={`w-full text-left px-3 py-2 rounded-lg text-sm truncate ${
              chat?.id === c.id ? "bg-[var(--surface-2)] border border-[var(--border)]" : "text-[var(--muted)] hover:text-white"
            }`}
          >
            {c.title}
          </button>
        ))}
      </div>

      <div className="flex-1 card flex flex-col min-w-0">
        <div className="flex items-center gap-2 p-3 border-b border-[var(--border)] flex-wrap">
          <div className="text-sm font-medium truncate flex-1">{chat?.title ?? "Чат с ИИ по проекту"}</div>
          <select
            className="input !w-auto text-xs"
            value={chat?.model ?? "opus"}
            onChange={(e) => updateChatSettings({ model: e.target.value })}
            disabled={!chat}
            title="Модель"
          >
            {MODELS.map((m) => (
              <option key={m.key} value={m.key}>{m.label}</option>
            ))}
          </select>
          <select
            className="input !w-auto text-xs"
            value={chat?.reasoning ?? "high"}
            onChange={(e) => updateChatSettings({ reasoning: e.target.value })}
            disabled={!chat}
            title="Глубина размышлений"
          >
            {REASONING.map((r) => (
              <option key={r.key} value={r.key}>{r.label}</option>
            ))}
          </select>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {messages.length === 0 && !live.streaming && (
            <div className="text-sm text-[var(--muted)] text-center pt-10 space-y-2">
              <div>Спроси о проекте, дай задачу с созвона или попроси составить план.</div>
              <div className="text-xs">
                ИИ видит карту знаний, файлы, материалы и канбан. Может создавать задачи и
                помечать сделанное — карта знаний обновится автоматически.
              </div>
            </div>
          )}
          {messages.map((m) => (
            <MessageBubble key={m.id} msg={m} />
          ))}
          {live.streaming && (
            <div className="space-y-2">
              {live.tools.length > 0 && (
                <div className="flex gap-1.5 flex-wrap">
                  {live.tools.map((t, i) => (
                    <span key={i} className="chip text-[var(--accent)]">⚙ {t.replace("mcp__projectai__", "")}</span>
                  ))}
                </div>
              )}
              <div className="text-sm whitespace-pre-wrap leading-relaxed">
                {live.text || <span className="pulse text-[var(--muted)]">ИИ думает…</span>}
              </div>
            </div>
          )}
          {live.error && <div className="text-sm text-red-400">⚠️ {live.error}</div>}
          <div ref={bottomRef} />
        </div>

        <form onSubmit={send} className="p-3 border-t border-[var(--border)] flex gap-2">
          <textarea
            className="input min-h-11 max-h-40 resize-y"
            placeholder="Сообщение… (Enter — отправить, Shift+Enter — новая строка)"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send(e);
              }
            }}
          />
          <button className="btn self-end" disabled={live.streaming || !input.trim()}>
            {live.streaming ? "…" : "➤"}
          </button>
        </form>
      </div>
    </div>
  );
}

function MessageBubble({ msg }: { msg: ChatMessage }) {
  const isUser = msg.role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[85%] rounded-xl px-4 py-2.5 text-sm leading-relaxed ${
          isUser ? "bg-[var(--accent)]/20 border border-[var(--accent)]/40" : "bg-[var(--surface-2)] border border-[var(--border)]"
        }`}
      >
        <RichText text={msg.content} />
        {!isUser && (msg.meta.cost_usd != null || msg.meta.duration_ms != null) && (
          <div className="text-[10px] text-[var(--muted)] mt-1.5">
            {msg.meta.model ?? ""}
            {msg.meta.duration_ms != null ? ` · ${(msg.meta.duration_ms / 1000).toFixed(1)}с` : ""}
            {msg.meta.cost_usd != null ? ` · $${Number(msg.meta.cost_usd).toFixed(4)}` : ""}
          </div>
        )}
      </div>
    </div>
  );
}

/** Безопасный рендер: код-фенсы моноширинно, остальное pre-wrap. */
function RichText({ text }: { text: string }) {
  const parts = text.split(/```(?:\w*\n)?/);
  return (
    <div className="space-y-2">
      {parts.map((part, i) =>
        i % 2 === 1 ? (
          <pre key={i} className="bg-black/40 rounded-lg p-3 overflow-x-auto text-xs font-mono">
            {part}
          </pre>
        ) : part.trim() ? (
          <div key={i} className="whitespace-pre-wrap">{part}</div>
        ) : null
      )}
    </div>
  );
}
