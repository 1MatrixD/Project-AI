"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";

type DirList = { path: string; parent: string | null; dirs: { name: string; path: string }[] };

export default function DirPicker({
  onSelect,
  onClose,
}: {
  onSelect: (path: string) => void;
  onClose: () => void;
}) {
  const t = useTranslations("dirPicker");
  const tCommon = useTranslations("common");
  const [drives, setDrives] = useState<string[]>([]);
  const [list, setList] = useState<DirList | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async (path: string) => {
    setError("");
    try {
      setList(await api<DirList>(`/fs/list?path=${encodeURIComponent(path)}`));
    } catch (e) {
      setError(e instanceof Error ? e.message : tCommon("error"));
    }
  }, [tCommon]);

  useEffect(() => {
    api<string[]>("/fs/drives").then((d) => {
      setDrives(d);
      if (d.length) load(d[0]);
    });
  }, [load]);

  return (
    <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4" onClick={onClose}>
      <div className="card w-full max-w-lg p-5 space-y-3" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <div className="font-medium">{t("title")}</div>
          <button className="text-[var(--muted)] hover:text-white" onClick={onClose}>✕</button>
        </div>
        <div className="flex gap-2 flex-wrap">
          {drives.map((d) => (
            <button key={d} className="chip hover:border-[var(--accent)]" onClick={() => load(d)}>
              {d}
            </button>
          ))}
        </div>
        {list && (
          <>
            <div className="text-xs text-[var(--muted)] font-mono break-all">{list.path}</div>
            <div className="h-64 overflow-y-auto border border-[var(--border)] rounded-lg divide-y divide-[var(--border)]">
              {list.parent && (
                <button
                  className="w-full text-left px-3 py-2 text-sm hover:bg-[var(--surface-2)]"
                  onClick={() => load(list.parent!)}
                >
                  {t("up")}
                </button>
              )}
              {list.dirs.map((d) => (
                <button
                  key={d.path}
                  className="w-full text-left px-3 py-2 text-sm hover:bg-[var(--surface-2)] flex items-center gap-2"
                  onClick={() => load(d.path)}
                >
                  <span>📁</span> {d.name}
                </button>
              ))}
              {list.dirs.length === 0 && (
                <div className="px-3 py-2 text-sm text-[var(--muted)]">{t("empty")}</div>
              )}
            </div>
          </>
        )}
        {error && <div className="text-sm text-red-400">{error}</div>}
        <div className="flex justify-end gap-2">
          <button className="btn btn-ghost" onClick={onClose}>{tCommon("cancel")}</button>
          <button className="btn" disabled={!list} onClick={() => list && onSelect(list.path)}>
            {t("select")}
          </button>
        </div>
      </div>
    </div>
  );
}
