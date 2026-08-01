"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { API_URL, api, fmtBytes, fmtDate, getToken } from "@/lib/api";
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
      for (const file of Array.from(files)) {
        const fd = new FormData();
        fd.append("file", file);
        const res = await fetch(`${API_URL}/api/projects/${projectId}/materials`, {
          method: "POST",
          headers: { Authorization: `Bearer ${getToken()}` },
          body: fd,
        });
        if (!res.ok) {
          const d = await res.json().catch(() => null);
          throw new Error(d?.detail ?? res.statusText);
        }
      }
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
          {uploading ? "Загружаю…" : "Перетащи файлы или нажми: записи созвонов (mp4/m4a/mp3), ТЗ (pdf/docx), таблицы, документы"}
        </div>
        <div className="text-xs text-[var(--muted)]">
          Аудио и видео транскрибируются локальным Whisper; из текста ИИ извлечёт выжимку и задачи в канбан.
        </div>
        <input ref={fileRef} type="file" multiple hidden onChange={(e) => upload(e.target.files)} />
      </div>
      {error && <div className="text-sm text-red-400">{error}</div>}

      <div className="space-y-2">
        {materials.map((m) => (
          <div key={m.id} className="card p-4 flex items-start gap-3 flex-wrap">
            <div className="text-xl">
              {/\.(mp4|mov|avi|mkv|webm)$/i.test(m.filename) ? "🎬" : /\.(m4a|mp3|wav|ogg|flac)$/i.test(m.filename) ? "🎙" : "📄"}
            </div>
            <div className="flex-1 min-w-64 space-y-1">
              <div className="text-sm font-medium">{m.filename}</div>
              <div className="text-xs text-[var(--muted)]">
                {fmtBytes(m.size)} · {fmtDate(m.created_at)}
              </div>
              {m.summary && <div className="text-sm text-[var(--muted)] whitespace-pre-wrap">{m.summary}</div>}
              {m.error && <div className="text-xs text-red-400">{m.error}</div>}
            </div>
            <div className="flex items-center gap-2">
              <StatusBadge status={m.status} />
              {m.status === "ready" && (
                <button className="btn btn-ghost text-xs" onClick={() => showText(m)}>Текст</button>
              )}
              {(m.status === "error" || m.status === "ready") && (
                <button
                  className="btn btn-ghost text-xs"
                  onClick={() =>
                    api(`/projects/${projectId}/materials/${m.id}/reprocess`, { method: "POST" }).then(load)
                  }
                >
                  ⟳
                </button>
              )}
            </div>
          </div>
        ))}
        {materials.length === 0 && (
          <div className="text-sm text-[var(--muted)] text-center py-6">Материалов пока нет</div>
        )}
      </div>

      {viewText && (
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
