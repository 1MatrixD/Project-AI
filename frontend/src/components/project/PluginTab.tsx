"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import { toast } from "@/components/Toast";
import type { PluginInfo } from "@/lib/types";

type PluginFile = { path: string; size: number };

export default function PluginTab({ projectId }: { projectId: string }) {
  const t = useTranslations("plugin");
  const tCommon = useTranslations("common");
  const [info, setInfo] = useState<PluginInfo | null>(null);
  const [busy, setBusy] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [browserOpen, setBrowserOpen] = useState<string | null>(null); // стартовый файл

  const load = useCallback(async () => {
    setInfo(await api<PluginInfo>(`/projects/${projectId}/plugin`));
  }, [projectId]);

  useEffect(() => {
    load();
  }, [load]);

  async function regenerate() {
    try {
      await api(`/projects/${projectId}/plugin/regenerate`, { method: "POST" });
      toast(t("regenerated"));
      setTimeout(load, 3000);
    } catch (e) {
      toast(e instanceof Error ? e.message : tCommon("error"), "error");
    }
  }

  async function installLocal() {
    setBusy(true);
    try {
      const r = await api<{ path: string }>(`/projects/${projectId}/plugin/local`, {
        method: "POST",
      });
      toast(t("installed", { path: r.path }));
      await load();
    } catch (e) {
      toast(e instanceof Error ? e.message : tCommon("error"), "error");
    } finally {
      setBusy(false);
    }
  }

  async function uninstallLocal() {
    setBusy(true);
    try {
      await api(`/projects/${projectId}/plugin/local`, { method: "DELETE" });
      toast(t("uninstalled"));
      await load();
    } catch (e) {
      toast(e instanceof Error ? e.message : tCommon("error"), "error");
    } finally {
      setBusy(false);
    }
  }

  if (!info) return <div className="text-[var(--muted)]">{tCommon("loading")}</div>;

  return (
    <div className="max-w-3xl space-y-4">
      <div className="card p-5 space-y-3">
        <div className="flex items-center justify-between">
          <div className="font-medium">{t("title")}</div>
          <div className="relative">
            <button
              className="btn btn-ghost text-sm px-2.5"
              title={tCommon("more")}
              onClick={() => setMenuOpen((v) => !v)}
            >
              ⋯
            </button>
            {menuOpen && (
              <>
                <div className="fixed inset-0 z-30" onClick={() => setMenuOpen(false)} />
                <div className="absolute right-0 top-full mt-1 z-40 card p-1 w-64 shadow-xl">
                  <button
                    className="w-full text-left text-sm px-3 py-2 rounded-lg hover:bg-[var(--surface-2)]"
                    onClick={() => {
                      setMenuOpen(false);
                      regenerate();
                    }}
                  >
                    {t("regenerate")}
                    <span className="block text-[11px] text-[var(--muted)]">{t("regenerateHint")}</span>
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
        <p className="text-sm text-[var(--muted)] leading-relaxed">{t("intro")}</p>
        <div className="text-xs text-[var(--muted)]">
          {t("status", { status: info.exists ? t("generated") : t("notGenerated") })}
        </div>
        <div className="text-xs font-mono break-all text-[var(--muted)]">{info.path}</div>
      </div>

      <div className="card p-5 space-y-3">
        <div className="font-medium">{t("skills")}</div>
        <p className="text-xs text-[var(--muted)]">{t("skillsHint")}</p>
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
              {t("allFiles")}
            </button>
          </div>
        ) : (
          <div className="text-sm text-[var(--muted)]">{t("skillsEmpty")}</div>
        )}
      </div>

      <div className="card p-5 space-y-3">
        <div className="font-medium">{t("tools")}</div>
        <p className="text-xs text-[var(--muted)]">{t("toolsHint")}</p>
        <div className="grid gap-1.5 sm:grid-cols-2">
          {info.mcp_tools?.map((tool) => (
            <div key={tool.name} className="border border-[var(--border)] rounded-lg p-2.5 space-y-0.5">
              <div className="text-xs font-mono text-[var(--accent)]">{tool.name}</div>
              <div className="text-xs text-[var(--muted)]">{tool.description}</div>
            </div>
          ))}
        </div>
      </div>

      <ToolAccessCard projectId={projectId} />

      <div className="card p-5 space-y-3">
        <div className="flex items-center justify-between gap-2">
          <div className="font-medium">{t("install")}</div>
          {info.installed_locally && (
            <span className="chip text-emerald-300">{t("enabledChip")}</span>
          )}
        </div>
        <p className="text-sm text-[var(--muted)] leading-relaxed">
          {t.rich("installHint", {
            path: info.local_settings_path,
            b: (chunks) => <b>{chunks}</b>,
            code: (chunks) => <code className="font-mono text-xs">{chunks}</code>,
          })}
        </p>
        <div className="flex gap-2 flex-wrap">
          <button className="btn" onClick={installLocal} disabled={busy}>
            {info.installed_locally ? t("reinstall") : t("enable")}
          </button>
          {info.installed_locally && (
            <button className="btn btn-ghost" onClick={uninstallLocal} disabled={busy}>
              {t("uninstall")}
            </button>
          )}
        </div>
        <details className="text-sm">
          <summary className="cursor-pointer text-[var(--muted)] hover:text-[var(--foreground)]">
            {t("global")}
          </summary>
          <ol className="space-y-3 list-decimal list-inside mt-2">
            <li>
              {t("global1")}
              <pre className="bg-black/40 rounded-lg p-3 mt-1 text-xs font-mono overflow-x-auto">
                claude plugin marketplace add {info.marketplace_path}
              </pre>
            </li>
            <li>
              {t("global2")}
              <pre className="bg-black/40 rounded-lg p-3 mt-1 text-xs font-mono overflow-x-auto">
                claude plugin install {info.slug}@projectai
              </pre>
            </li>
            <li>
              {t.rich("global3", {
                code: (chunks) => <code className="font-mono text-xs">{chunks}</code>,
              })}
            </li>
          </ol>
        </details>
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

type ToolAccess = {
  access: Record<string, Record<string, boolean>>;
  labels: Record<string, string>;
  groups: Record<string, string[]>;
};

/** Разграничение инструментов: чат приложения vs внешний плагин Claude Code. */
function ToolAccessCard({ projectId }: { projectId: string }) {
  const t = useTranslations("plugin.access");
  const [data, setData] = useState<ToolAccess | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api<ToolAccess>(`/projects/${projectId}/tool-access`).then(setData).catch(() => {});
  }, [projectId]);

  async function toggle(surface: string, group: string) {
    if (!data) return;
    const access = {
      ...data.access,
      [surface]: { ...data.access[surface], [group]: !data.access[surface][group] },
    };
    setData({ ...data, access });
    await api(`/projects/${projectId}/tool-access`, {
      method: "PUT",
      body: JSON.stringify(access),
    });
    setSaved(true);
    setTimeout(() => setSaved(false), 1500);
  }

  if (!data) return null;
  const groups = Object.keys(data.labels);

  return (
    <div className="card p-5 space-y-3">
      <div className="flex items-center justify-between">
        <div className="font-medium">{t("title")}</div>
        {saved && <span className="text-xs text-emerald-300">{t("saved")}</span>}
      </div>
      <p className="text-xs text-[var(--muted)] leading-relaxed">{t("hint")}</p>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-xs text-[var(--muted)] text-left">
            <th className="py-1.5 font-normal">{t("group")}</th>
            <th className="py-1.5 font-normal text-center w-28">{t("chat")}</th>
            <th className="py-1.5 font-normal text-center w-28">{t("plugin")}</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-[var(--border)]">
          {groups.map((g) => (
            <tr key={g}>
              <td className="py-2 pr-2">{data.labels[g]}</td>
              {(["chat", "plugin"] as const).map((surface) => (
                <td key={surface} className="py-2 text-center">
                  <input
                    type="checkbox"
                    className="accent-[var(--accent)] w-4 h-4 cursor-pointer"
                    checked={data.access[surface]?.[g] ?? true}
                    onChange={() => toggle(surface, g)}
                  />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
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
  const t = useTranslations("plugin.browser");
  const tCommon = useTranslations("common");
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
      .catch((e) => setContent(t("openFailed", { error: e instanceof Error ? e.message : String(e) })))
      .finally(() => setLoading(false));
  }, [projectId, selected, t]);

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
          <div className="font-medium text-sm">{t("title")}</div>
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
            {loading ? tCommon("loading") : content || t("pick")}
          </pre>
        </div>
      </div>
    </div>
  );
}
