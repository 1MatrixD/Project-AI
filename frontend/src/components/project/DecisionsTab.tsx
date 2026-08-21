"use client";

import { useCallback, useEffect, useState } from "react";
import { api, fmtDate } from "@/lib/api";
import { toast } from "@/components/Toast";
import type { Decision } from "@/lib/types";

const SOURCE_LABEL: Record<string, string> = {
  manual: "человек",
  meeting: "ИИ · с созвона",
  doc: "ИИ · из документа",
  chat: "ИИ · из чата",
};

/** Соглашения проекта — отдельная страница: их может стать много, и они —
 *  такой же каталог знаний, как файлы и материалы. Пишут сюда и человек
 *  (руками), и ИИ (record_decision через MCP, извлечение из созвонов);
 *  учитываются в проработке задач, декомпозиции, ИИ-проверке, git-импорте
 *  и системном промпте чата. */
export default function DecisionsTab({ projectId }: { projectId: string }) {
  const [decisions, setDecisions] = useState<Decision[] | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setDecisions(await api<Decision[]>(`/projects/${projectId}/decisions`));
    } catch {}
  }, [projectId]);

  useEffect(() => {
    load();
  }, [load]);

  async function add(topic: string, text: string) {
    await api(`/projects/${projectId}/decisions`, {
      method: "POST",
      body: JSON.stringify({ topic, text }),
    });
    setShowAdd(false);
    toast("Соглашение записано — все будущие проработки и проверки будут его учитывать.");
    load();
  }

  async function save(id: string, topic: string, text: string) {
    await api(`/projects/${projectId}/decisions/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ topic, text }),
    });
    setEditId(null);
    toast("Соглашение обновлено.");
    load();
  }

  async function remove(id: string) {
    if (!confirm("Удалить соглашение?")) return;
    await api(`/projects/${projectId}/decisions/${id}`, { method: "DELETE" });
    toast("Соглашение удалено.");
    load();
  }

  return (
    <div className="max-w-3xl mx-auto space-y-4">
      <div className="card p-5 space-y-3">
        <div className="flex items-center justify-between">
          <div className="font-medium">Соглашения проекта</div>
          <button className="btn btn-ghost text-sm" onClick={() => setShowAdd(!showAdd)}>
            {showAdd ? "✕" : "+ Добавить"}
          </button>
        </div>
        <div className="text-xs text-[var(--muted)] leading-relaxed">
          То, чего <b>в коде не прочитать</b>: что считается правильным сейчас и от чего
          отказались. Код обычно отстаёт от решений: без заметки «роль ORGANIZER упразднена,
          теперь MANAGER + права» ИИ найдёт остатки старого подхода и заведёт их как баг;
          с ней — поймёт, что это осознанный переход, и будет доделывать миграцию, а не
          откатывать её. Пишет сюда и человек, и ИИ: скажи в Claude Code «мы сменили
          подход» — он зафиксирует через record_decision. Автоматически извлекаются из
          созвонов и документов.
        </div>
        {showAdd && (
          <DecisionForm
            onSubmit={add}
            onCancel={() => setShowAdd(false)}
            submitLabel="Сохранить"
          />
        )}
      </div>

      {decisions === null ? (
        <div className="text-sm text-[var(--muted)] text-center py-6">Загрузка…</div>
      ) : decisions.length === 0 ? (
        <div className="card p-5 text-sm text-[var(--muted)]">
          Пока нет — добавь вручную, попроси ИИ в Claude Code зафиксировать
          (record_decision) или загрузи созвон: решения извлекаются автоматически.
        </div>
      ) : (
        decisions.map((d) =>
          editId === d.id ? (
            <div key={d.id} className="card p-4">
              <DecisionForm
                initialTopic={d.topic}
                initialText={d.text}
                onSubmit={(topic, text) => save(d.id, topic, text)}
                onCancel={() => setEditId(null)}
                submitLabel="Сохранить"
              />
            </div>
          ) : (
            <div key={d.id} className="card p-4 space-y-1.5 group">
              <div className="flex justify-between gap-2 items-start">
                <div className="text-sm font-medium">{d.topic}</div>
                <div className="flex gap-1 opacity-0 group-hover:opacity-100 shrink-0">
                  <button
                    className="text-xs text-[var(--muted)] hover:text-[var(--accent)] px-1.5"
                    title="Править"
                    onClick={() => setEditId(d.id)}
                  >
                    ✎
                  </button>
                  <button
                    className="text-xs text-[var(--muted)] hover:text-red-300 px-1.5"
                    title="Удалить"
                    onClick={() => remove(d.id)}
                  >
                    ✕
                  </button>
                </div>
              </div>
              <div className="text-sm text-[var(--muted)] whitespace-pre-wrap leading-relaxed">
                {d.text}
              </div>
              <div className="text-[10px] text-[var(--muted)] flex items-center gap-1.5">
                <span className="chip">{SOURCE_LABEL[d.source] ?? d.source}</span>
                {fmtDate(d.updated_at)}
              </div>
            </div>
          )
        )
      )}
    </div>
  );
}

function DecisionForm({
  initialTopic = "",
  initialText = "",
  onSubmit,
  onCancel,
  submitLabel,
}: {
  initialTopic?: string;
  initialText?: string;
  onSubmit: (topic: string, text: string) => Promise<void>;
  onCancel: () => void;
  submitLabel: string;
}) {
  const [topic, setTopic] = useState(initialTopic);
  const [text, setText] = useState(initialText);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!topic.trim() || !text.trim() || busy) return;
    setBusy(true);
    try {
      await onSubmit(topic.trim(), text.trim());
    } catch (err) {
      toast(err instanceof Error ? err.message : "Ошибка", "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-2">
      <input
        className="input"
        placeholder="Тема (например: Роли в админке)"
        value={topic}
        onChange={(e) => setTopic(e.target.value)}
      />
      <textarea
        className="input min-h-20 text-sm"
        placeholder="Актуальное решение: что теперь правильно и от чего отказались…"
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      <div className="flex gap-2 justify-end">
        <button type="button" className="btn btn-ghost text-sm" onClick={onCancel} disabled={busy}>
          Отмена
        </button>
        <button className="btn text-sm" disabled={busy || !topic.trim() || !text.trim()}>
          {submitLabel}
        </button>
      </div>
    </form>
  );
}
