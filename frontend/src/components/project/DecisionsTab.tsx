"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import { useFmt } from "@/lib/format";
import { toast } from "@/components/Toast";
import type { Decision } from "@/lib/types";

/** Соглашения проекта — отдельная страница: их может стать много, и они —
 *  такой же каталог знаний, как файлы и материалы. Пишут сюда и человек
 *  (руками), и ИИ (record_decision через MCP, извлечение из созвонов);
 *  учитываются в проработке задач, декомпозиции, ИИ-проверке, git-импорте
 *  и системном промпте чата. */
export default function DecisionsTab({ projectId }: { projectId: string }) {
  const t = useTranslations("decisions");
  const tCommon = useTranslations("common");
  const fmt = useFmt();
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
    toast(t("added"));
    load();
  }

  async function save(id: string, topic: string, text: string) {
    await api(`/projects/${projectId}/decisions/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ topic, text }),
    });
    setEditId(null);
    toast(t("updated"));
    load();
  }

  async function remove(id: string) {
    if (!confirm(t("confirmDelete"))) return;
    await api(`/projects/${projectId}/decisions/${id}`, { method: "DELETE" });
    toast(t("deleted"));
    load();
  }

  const sourceLabel = (s: string) => (t.has(`source.${s}`) ? t(`source.${s}`) : s);

  return (
    <div className="max-w-3xl mx-auto space-y-4">
      <div className="card p-5 space-y-3">
        <div className="flex items-center justify-between">
          <div className="font-medium">{t("title")}</div>
          <button className="btn btn-ghost text-sm" onClick={() => setShowAdd(!showAdd)}>
            {showAdd ? "✕" : t("add")}
          </button>
        </div>
        <div className="text-xs text-[var(--muted)] leading-relaxed">
          {t.rich("intro", { b: (chunks) => <b>{chunks}</b> })}
        </div>
        {showAdd && (
          <DecisionForm
            onSubmit={add}
            onCancel={() => setShowAdd(false)}
            submitLabel={tCommon("save")}
          />
        )}
      </div>

      {decisions === null ? (
        <div className="text-sm text-[var(--muted)] text-center py-6">{tCommon("loading")}</div>
      ) : decisions.length === 0 ? (
        <div className="card p-5 text-sm text-[var(--muted)]">{t("empty")}</div>
      ) : (
        decisions.map((d) =>
          editId === d.id ? (
            <div key={d.id} className="card p-4">
              <DecisionForm
                initialTopic={d.topic}
                initialText={d.text}
                onSubmit={(topic, text) => save(d.id, topic, text)}
                onCancel={() => setEditId(null)}
                submitLabel={tCommon("save")}
              />
            </div>
          ) : (
            <div key={d.id} className="card p-4 space-y-1.5 group">
              <div className="flex justify-between gap-2 items-start">
                <div className="text-sm font-medium">{d.topic}</div>
                <div className="flex gap-1 opacity-0 group-hover:opacity-100 shrink-0">
                  <button
                    className="text-xs text-[var(--muted)] hover:text-[var(--accent)] px-1.5"
                    title={t("edit")}
                    onClick={() => setEditId(d.id)}
                  >
                    ✎
                  </button>
                  <button
                    className="text-xs text-[var(--muted)] hover:text-red-300 px-1.5"
                    title={tCommon("delete")}
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
                <span className="chip">{sourceLabel(d.source)}</span>
                {fmt.date(d.updated_at)}
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
  const t = useTranslations("decisions.form");
  const tCommon = useTranslations("common");
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
      toast(err instanceof Error ? err.message : tCommon("error"), "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-2">
      <input
        className="input"
        placeholder={t("topic")}
        value={topic}
        onChange={(e) => setTopic(e.target.value)}
      />
      <textarea
        className="input min-h-20 text-sm"
        placeholder={t("text")}
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      <div className="flex gap-2 justify-end">
        <button type="button" className="btn btn-ghost text-sm" onClick={onCancel} disabled={busy}>
          {tCommon("cancel")}
        </button>
        <button className="btn text-sm" disabled={busy || !topic.trim() || !text.trim()}>
          {submitLabel}
        </button>
      </div>
    </form>
  );
}
