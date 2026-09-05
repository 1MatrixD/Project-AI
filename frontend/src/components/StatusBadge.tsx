"use client";

import { useTranslations } from "next-intl";

const STYLE: Record<string, { cls: string; pulse?: boolean }> = {
  created: { cls: "text-sky-300 border-sky-800" },
  indexing: { cls: "text-amber-300 border-amber-800", pulse: true },
  ready: { cls: "text-emerald-300 border-emerald-800" },
  error: { cls: "text-red-300 border-red-800" },
  queued: { cls: "text-sky-300 border-sky-800" },
  running: { cls: "text-amber-300 border-amber-800", pulse: true },
  done: { cls: "text-emerald-300 border-emerald-800" },
  cancelled: { cls: "text-zinc-400 border-zinc-700" },
  uploaded: { cls: "text-sky-300 border-sky-800" },
  processing: { cls: "text-amber-300 border-amber-800", pulse: true },
};

export default function StatusBadge({ status }: { status: string }) {
  const t = useTranslations("status");
  const m = STYLE[status] ?? { cls: "text-zinc-300 border-zinc-700" };
  const label = t.has(status) ? t(status) : status;
  return <span className={`chip ${m.cls} ${m.pulse ? "pulse" : ""}`}>{label}</span>;
}
