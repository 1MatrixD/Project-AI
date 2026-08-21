"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { API_URL, api, fmtBytes, fmtDate, getToken } from "@/lib/api";
import { toast } from "@/components/Toast";
import type { Material } from "@/lib/types";
import StatusBadge from "@/components/StatusBadge";

export default function MaterialsTab({
  projectId,
  refreshTick,
}: {
  projectId: string;
  refreshTick: number;
}) {
  const [materials, setMaterials] = useState<Material[]>([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [viewText, setViewText] = useState<{ title: string; text: string } | null>(null);
  //: к какому материалу относится следующая загрузка (уточнение)
  const [clarifies, setClarifies] = useState<Material | null>(null);
  const [noteFor, setNoteFor] = useState<Material | null | undefined>(undefined);
  const fileRef = useRef<HTMLInputElement | null>(null);

  const load = useCallback(async () => {
    try {
      setMaterials(await api<Material[]>(`/projects/${projectId}/materials`));
    } catch {}
  }, [projectId]);

  useEffect(() => {
    load();
  }, [load, refreshTick]);

  async function upload(files: FileList | null) {
    if (!files?.length) return;
    setError("");
    setUploading(true);
    try {
      const q = clarifies ? `?clarifies=${clarifies.id}` : "";
      for (const file of Array.from(files)) {
        const fd = new FormData();
        fd.append("file", file);
        const res = await fetch(`${API_URL}/api/projects/${projectId}/materials${q}`, {
          method: "POST",
          headers: { Authorization: `Bearer ${getToken()}` },
          body: fd,
        });
        if (!res.ok) {
          const d = await res.json().catch(() => null);
          throw new Error(d?.detail ?? res.statusText);
        }
      }
      toast(
        clarifies
          ? `Загружено как уточнение к «${clarifies.filename}»: ИИ дополнит задачи из того материала и отправит их на переработку.`
          : "Материал загружен: ИИ извлечёт выжимку и задачи."
      );
      setClarifies(null);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка загрузки");
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function showText(m: Material) {
    const res = await api<{ text: string }>(`/projects/${projectId}/materials/${m.id}/text?limit_chars=50000`);
    setViewText({ title: m.filename, text: res.text });
  }

  // Уточнения показываем под своим материалом: созвон и пришедшее позже ТЗ —
  // одна история, и плоский список это скрывал.
  const children = new Map<string, Material[]>();
  for (const m of materials) {
    const parent = m.meta?.clarifies;
    if (parent) children.set(parent, [...(children.get(parent) ?? []), m]);
  }
  const roots = materials.filter((m) => !m.meta?.clarifies || !materials.some((x) => x.id === m.meta!.clarifies));

  return (
    <div className="space-y-4">
      <div
        className="card border-dashed p-8 text-center space-y-2 cursor-pointer hover:border-[var(--accent)]"
        onClick={() => fileRef.current?.click()}
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          upload(e.dataTransfer.files);
        }}
      >
        <div className="text-2xl">📎</div>
        <div className="text-sm">
          {uploading
            ? "Загружаю…"
            : clarifies
              ? `Файл станет уточнением к «${clarifies.filename}»`
              : "Перетащи файлы или нажми: записи созвонов (mp4/m4a/mp3), ТЗ (pdf/docx), таблицы, документы"}
        </div>
        <div className="text-xs text-[var(--muted)]">
          {clarifies
            ? "ИИ дополнит задачи, рождённые тем материалом, и отправит их на переработку — новые заведёт отдельно."
            : "Аудио и видео транскрибируются локальным Whisper; из текста ИИ извлечёт выжимку и задачи в канбан."}
        </div>
        <input ref={fileRef} type="file" multiple hidden onChange={(e) => upload(e.target.files)} />
      </div>
      <div className="flex gap-2 items-center flex-wrap">
        <button className="btn btn-ghost text-sm" onClick={() => setNoteFor(clarifies)}>
          ✍️ Заметка своими словами
        </button>
        {clarifies && (
          <button className="btn btn-ghost text-sm" onClick={() => setClarifies(null)}>
            ✕ Не уточнять «{clarifies.filename}»
          </button>
        )}
      </div>
      {error && <div className="text-sm text-red-400">{error}</div>}

      <div className="space-y-2">
        {roots.map((m) => (
          <div key={m.id} className="space-y-2">
            <MaterialRow
              m={m}
              projectId={projectId}
              onText={showText}
              onReload={load}
              onClarify={() => setClarifies(m)}
              onNote={() => setNoteFor(m)}
            />
            {(children.get(m.id) ?? []).map((c) => (
              <div key={c.id} className="ml-6 pl-3 border-l-2 border-[var(--border)]">
                <MaterialRow
                  m={c}
                  projectId={projectId}
                  onText={showText}
                  onReload={load}
                  clarifying
                />
              </div>
            ))}
          </div>
        ))}
        {materials.length === 0 && (
          <div className="text-sm text-[var(--muted)] text-center py-6">Материалов пока нет</div>
        )}
      </div>

      {noteFor !== undefined && (
        <NoteModal
          projectId={projectId}
          clarifies={noteFor}
          onClose={() => setNoteFor(undefined)}
          onSaved={() => {
            setNoteFor(undefined);
            setClarifies(null);
            load();
          }}
        />
      )}

      {viewText !== null && (
        <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4" onClick={() => setViewText(null)}>
          <div className="card w-full max-w-3xl p-5 space-y-3 max-h-[85vh] flex flex-col" onClick={(e) => e.stopPropagation()}>
            <div className="flex justify-between items-center">
              <div className="font-medium truncate">{viewText.title}</div>
              <button className="text-[var(--muted)] hover:text-white" onClick={() => setViewText(null)}>✕</button>
            </div>
            <pre className="flex-1 overflow-auto text-xs whitespace-pre-wrap font-mono bg-black/30 rounded-lg p-4">
              {viewText.text}
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}

function MaterialRow({
  m,
  projectId,
  onText,
  onReload,
  onClarify,
  onNote,
  clarifying = false,
}: {
  m: Material;
  projectId: string;
  onText: (m: Material) => void;
  onReload: () => void;
  onClarify?: () => void;
  onNote?: () => void;
  clarifying?: boolean;
}) {
  const icon = /\.(mp4|mov|avi|mkv|webm)$/i.test(m.filename)
    ? "🎬"
    : /\.(m4a|mp3|wav|ogg|flac)$/i.test(m.filename)
      ? "🎙"
      : m.media_type === "text/plain"
        ? "✍️"
        : "📄";
  return (
    <div className="card p-4 flex items-start gap-3 flex-wrap">
      <div className="text-xl">{icon}</div>
      <div className="flex-1 min-w-64 space-y-1">
        <div className="text-sm font-medium">
          {m.filename}
          {clarifying && <span className="chip ml-2">уточнение</span>}
        </div>
        <div className="text-xs text-[var(--muted)]">
          {fmtBytes(m.size)} · {fmtDate(m.created_at)}
        </div>
        {m.summary && <div className="text-sm text-[var(--muted)] whitespace-pre-wrap">{m.summary}</div>}
        {m.error && <div className="text-xs text-red-400">{m.error}</div>}
      </div>
      <div className="flex items-center gap-2 flex-wrap justify-end">
        <StatusBadge status={m.status} />
        {onClarify && m.status === "ready" && (
          <button
            className="btn btn-ghost text-xs"
            title="Загрузить документ или написать заметку, которая уточняет задачи из этого материала"
            onClick={onClarify}
          >
            + Уточнение
          </button>
        )}
        {onNote && m.status === "ready" && (
          <button className="btn btn-ghost text-xs" title="Дописать своими словами" onClick={onNote}>
            ✍️
          </button>
        )}
        {m.status === "ready" && (
          <button className="btn btn-ghost text-xs" onClick={() => onText(m)}>Текст</button>
        )}
        {(m.status === "error" || m.status === "ready") && (
          <button
            className="btn btn-ghost text-xs"
            title="Обработать заново"
            onClick={() =>
              api(`/projects/${projectId}/materials/${m.id}/reprocess`, { method: "POST" }).then(onReload)
            }
          >
            ⟳
          </button>
        )}
      </div>
    </div>
  );
}

/** Заметка своими словами. Это обычный материал, просто набранный руками:
 *  так же извлекает задачи и так же умеет уточнять уже заведённые. */
function NoteModal({
  projectId,
  clarifies,
  onClose,
  onSaved,
}: {
  projectId: string;
  clarifies: Material | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (!text.trim() || busy) return;
    setBusy(true);
    try {
      await api(`/projects/${projectId}/materials/note`, {
        method: "POST",
        body: JSON.stringify({
          title: title.trim(),
          text: text.trim(),
          clarifies: clarifies?.id ?? null,
        }),
      });
      toast(
        clarifies
          ? `Заметка добавлена как уточнение к «${clarifies.filename}» — задачи оттуда будут дополнены.`
          : "Заметка добавлена: ИИ разберёт её как материал."
      );
      onSaved();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Ошибка", "error");
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4" onClick={onClose}>
      <div className="card w-full max-w-2xl p-5 space-y-3" onClick={(e) => e.stopPropagation()}>
        <div className="font-medium text-lg">
          {clarifies ? `Уточнение к «${clarifies.filename}»` : "Заметка своими словами"}
        </div>
        <div className="text-xs text-[var(--muted)] leading-relaxed">
          {clarifies
            ? "Пойдёт тем же путём, что документ: ИИ дополнит задачи, рождённые тем материалом, и отправит их на переработку."
            : "Обычный текст без разметки. ИИ разберёт его как материал: заведёт новые задачи и дополнит подходящие существующие."}
        </div>
        <input
          className="input"
          placeholder="Заголовок (необязательно)"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
        <textarea
          className="input min-h-48 text-sm leading-relaxed"
          placeholder="Например: в матче девять игроков, замены только в перерыве, вратарь не считается полевым…"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
              e.preventDefault();
              submit();
            }
          }}
        />
        <div className="flex justify-end gap-2">
          <button className="btn btn-ghost" onClick={onClose} disabled={busy}>Отмена</button>
          <button className="btn" onClick={submit} disabled={busy || !text.trim()} title="Ctrl+Enter">
            {busy ? "Сохраняю…" : "Добавить"}
          </button>
        </div>
      </div>
    </div>
  );
}
