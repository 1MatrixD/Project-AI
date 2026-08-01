"use client";

import { useCallback, useEffect, useState } from "react";
import { api, fmtBytes } from "@/lib/api";
import type { ProjectFile } from "@/lib/types";

const KINDS = ["", "code", "config", "doc", "test", "data", "asset", "other"];
const KIND_LABEL: Record<string, string> = {
  "": "Все типы",
  code: "Код",
  config: "Конфиги",
  doc: "Документы",
  test: "Тесты",
  data: "Данные",
  asset: "Ассеты",
  other: "Прочее",
};

const STATUS_ICON: Record<string, string> = {
  analyzed: "🟢",
  pending: "⚪",
  error: "🔴",
  skipped: "⚫",
};

export default function FilesTab({ projectId }: { projectId: string }) {
  const [items, setItems] = useState<ProjectFile[]>([]);
  const [total, setTotal] = useState(0);
  const [q, setQ] = useState("");
  const [kind, setKind] = useState("");
  const [offset, setOffset] = useState(0);
  const limit = 100;

  const load = useCallback(async () => {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (q) params.set("q", q);
    if (kind) params.set("kind", kind);
    const res = await api<{ total: number; items: ProjectFile[] }>(
      `/projects/${projectId}/files?${params}`
    );
    setItems(res.items);
    setTotal(res.total);
  }, [projectId, q, kind, offset]);

  useEffect(() => {
    const t = setTimeout(load, 250);
    return () => clearTimeout(t);
  }, [load]);

  return (
    <div className="card p-4 space-y-3">
      <div className="flex gap-2 flex-wrap">
        <input
          className="input !w-64"
          placeholder="Поиск по пути и описанию…"
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setOffset(0);
          }}
        />
        <select className="input !w-auto" value={kind} onChange={(e) => { setKind(e.target.value); setOffset(0); }}>
          {KINDS.map((k) => (
            <option key={k} value={k}>{KIND_LABEL[k]}</option>
          ))}
        </select>
        <div className="chip self-center">{total} файлов</div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-[var(--muted)] text-xs">
            <tr>
              <th className="py-2 pr-3">Файл</th>
              <th className="py-2 pr-3">Тип</th>
              <th className="py-2 pr-3">Размер</th>
              <th className="py-2">Роль (из ИИ-анализа)</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--border)]">
            {items.map((f) => (
              <tr key={f.id}>
                <td className="py-2 pr-3 font-mono text-xs whitespace-nowrap">
                  <span title={f.analysis_status}>{STATUS_ICON[f.analysis_status] ?? "⚪"}</span>{" "}
                  {f.rel_path}
                </td>
                <td className="py-2 pr-3"><span className="chip">{f.kind}</span></td>
                <td className="py-2 pr-3 text-[var(--muted)] whitespace-nowrap">{fmtBytes(f.size)}</td>
                <td className="py-2 text-[var(--muted)] text-xs max-w-xl">{f.summary ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex gap-2 justify-end text-sm">
        <button className="btn btn-ghost" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))}>
          ← Назад
        </button>
        <button className="btn btn-ghost" disabled={offset + limit >= total} onClick={() => setOffset(offset + limit)}>
          Вперёд →
        </button>
      </div>
    </div>
  );
}
