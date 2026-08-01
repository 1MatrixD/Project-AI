"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { PluginInfo } from "@/lib/types";

type PluginFile = { path: string; size: number };

export default function PluginTab({ projectId }: { projectId: string }) {
  const [info, setInfo] = useState<PluginInfo | null>(null);
  const [notice, setNotice] = useState("");
  const [browserOpen, setBrowserOpen] = useState<string | null>(null); // стартовый файл

  const load = useCallback(async () => {
    setInfo(await api<PluginInfo>(`/projects/${projectId}/plugin`));
  }, [projectId]);

  useEffect(() => {
    load();
  }, [load]);

  async function regenerate() {
    await api(`/projects/${projectId}/plugin/regenerate`, { method: "POST" });
    setNotice("Плагин перегенерируется в фоне со свежими знаниями из карты.");
    setTimeout(load, 3000);
  }

  if (!info) return <div className="text-[var(--muted)]">Загрузка…</div>;

  return (
    <div className="max-w-3xl space-y-4">
      <div className="card p-5 space-y-3">
        <div className="font-medium">Плагин Claude Code для этого проекта</div>
        <p className="text-sm text-[var(--muted)] leading-relaxed">
          Плагин подключает к твоему Claude Code MCP-сервер проекта (карта знаний, канбан,
          RLM-запросы, worklog) и скиллы, сгенерированные из анализа: архитектура,
          бизнес-логика, рабочий процесс задач. После установки Claude в терминале будет
          «знать» проект и сможет вести задачи — сделанное автоматически попадёт в карту знаний.
        </p>
        <div className="text-xs text-[var(--muted)]">
          Статус: {info.exists ? "✅ сгенерирован" : "⏳ ещё не сгенерирован (дождись индексации)"}
        </div>
        <div className="text-xs font-mono break-all text-[var(--muted)]">{info.path}</div>
        <button className="btn btn-ghost" onClick={regenerate}>⟳ Перегенерировать</button>
        {notice && <div className="text-sm text-[var(--accent)]">{notice}</div>}
      </div>

      <div className="card p-5 space-y-3">
        <div className="font-medium">Скиллы плагина</div>
        <p className="text-xs text-[var(--muted)]">
          Генерируются из карты знаний при каждой индексации — Claude Code подхватит их автоматически.
        </p>
        {info.skills?.length ? (
          <div className="space-y-2">
            {info.skills.map((s) => (
              <button
                key={s.name}
                className="w-full text-left border border-[var(--border)] rounded-lg p-3 space-y-0.5 hover:border-[var(--accent)] cursor-pointer"
                onClick={() => setBrowserOpen(`skills/${s.name}/SKILL.md`)}
              >
                <div className="text-sm font-mono text-[var(--accent)]">/{s.name}</div>
                <div className="text-xs text-[var(--muted)]">{s.description}</div>
              </button>
            ))}
            <button className="btn btn-ghost text-sm" onClick={() => setBrowserOpen("")}>
              📂 Все файлы плагина
            </button>
          </div>
        ) : (
          <div className="text-sm text-[var(--muted)]">Появятся после индексации проекта</div>
        )}
      </div>

      <div className="card p-5 space-y-3">
        <div className="font-medium">MCP-инструменты сервера projectai</div>
        <p className="text-xs text-[var(--muted)]">
          Доступны и чату внутри системы, и Claude Code после установки плагина.
        </p>
        <div className="grid gap-1.5 sm:grid-cols-2">
          {info.mcp_tools?.map((t) => (
            <div key={t.name} className="border border-[var(--border)] rounded-lg p-2.5 space-y-0.5">
              <div className="text-xs font-mono text-[var(--accent)]">{t.name}</div>
              <div className="text-xs text-[var(--muted)]">{t.description}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="card p-5 space-y-3">
        <div className="font-medium">Установка</div>
        <ol className="text-sm space-y-3 list-decimal list-inside">
          <li>
            Добавь маркетплейс «Проекты ИИ» (один раз):
            <pre className="bg-black/40 rounded-lg p-3 mt-1 text-xs font-mono overflow-x-auto">
              claude plugin marketplace add {info.marketplace_path}
            </pre>
          </li>
          <li>
            Установи плагин проекта:
            <pre className="bg-black/40 rounded-lg p-3 mt-1 text-xs font-mono overflow-x-auto">
              claude plugin install {info.slug}@projectai
            </pre>
          </li>
          <li>
            Открой Claude Code в каталоге проекта — инструменты <code className="font-mono text-xs">projectai</code> и
            скиллы подхватятся автоматически.
          </li>
        </ol>
      </div>

      {browserOpen !== null && (
        <PluginBrowser
          projectId={projectId}
          initialPath={browserOpen}
          onClose={() => setBrowserOpen(null)}
        />
      )}
    </div>
  );
}

/** Модалка просмотра плагина: слева файлы как в директории, по центру текст. */
function PluginBrowser({
  projectId,
  initialPath,
  onClose,
}: {
  projectId: string;
  initialPath: string;
  onClose: () => void;
}) {
  const [files, setFiles] = useState<PluginFile[]>([]);
  const [selected, setSelected] = useState<string>(initialPath);
  const [content, setContent] = useState<string>("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    api<PluginFile[]>(`/projects/${projectId}/plugin/files`).then((fs) => {
      setFiles(fs);
      if (!initialPath && fs.length) setSelected(fs[0].path);
    });
  }, [projectId, initialPath]);

  useEffect(() => {
    if (!selected) return;
    setLoading(true);
    api<{ content: string }>(`/projects/${projectId}/plugin/file?path=${encodeURIComponent(selected)}`)
      .then((r) => setContent(r.content))
      .catch((e) => setContent(`(не удалось открыть: ${e instanceof Error ? e.message : e})`))
      .finally(() => setLoading(false));
  }, [projectId, selected]);

  // группировка по каталогам для навигации
  const grouped: { dir: string; items: PluginFile[] }[] = [];
  for (const f of files) {
    const dir = f.path.includes("/") ? f.path.slice(0, f.path.lastIndexOf("/")) : "";
    let g = grouped.find((x) => x.dir === dir);
    if (!g) {
      g = { dir, items: [] };
      grouped.push(g);
    }
    g.items.push(f);
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4" onClick={onClose}>
      <div
        className="card w-full max-w-5xl h-[85vh] flex flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--border)]">
          <div className="font-medium text-sm">Файлы плагина</div>
          <div className="text-xs font-mono text-[var(--muted)] truncate max-w-md">{selected}</div>
          <button className="text-[var(--muted)] hover:text-white" onClick={onClose}>✕</button>
        </div>
        <div className="flex flex-1 min-h-0">
          <div className="w-72 border-r border-[var(--border)] overflow-y-auto p-2 space-y-1 shrink-0">
            {grouped.map((g) => (
              <div key={g.dir || "."}>
                <div className="text-[11px] text-[var(--muted)] px-2 pt-2 pb-0.5 font-mono">
                  📁 {g.dir || "."}
                </div>
                {g.items.map((f) => {
                  const name = f.path.split("/").pop();
                  return (
                    <button
                      key={f.path}
                      onClick={() => setSelected(f.path)}
                      className={`w-full text-left px-3 py-1.5 rounded-md text-xs font-mono truncate ${
                        selected === f.path
                          ? "bg-[var(--accent)]/20 text-[var(--accent)]"
                          : "text-[var(--foreground)] hover:bg-[var(--surface-2)]"
                      }`}
                    >
                      {name}
                    </button>
                  );
                })}
              </div>
            ))}
          </div>
          <pre className="flex-1 overflow-auto p-5 text-[13px] leading-relaxed whitespace-pre-wrap font-mono">
            {loading ? "Загрузка…" : content || "Выбери файл слева"}
          </pre>
        </div>
      </div>
    </div>
  );
}
