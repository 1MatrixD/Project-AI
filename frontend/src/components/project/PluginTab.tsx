"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { PluginInfo } from "@/lib/types";

export default function PluginTab({ projectId }: { projectId: string }) {
  const [info, setInfo] = useState<PluginInfo | null>(null);
  const [notice, setNotice] = useState("");

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
    </div>
  );
}
