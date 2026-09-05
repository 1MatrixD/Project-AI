"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import type { GraphData } from "@/lib/types";

const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), { ssr: false });

const LABEL_COLORS: Record<string, string> = {
  Project: "#f5c518",
  Component: "#8b6cff",
  File: "#6c8cff",
  Entity: "#38bdf8",
  Document: "#34d399",
  Task: "#fb923c",
  WorkLog: "#f472b6",
};

type Node = { id: string; name: string; label: string; summary: string; kind: string; val: number };

export default function GraphTab({ projectId }: { projectId: string }) {
  const t = useTranslations("graph");
  const [data, setData] = useState<GraphData | null>(null);
  const [selected, setSelected] = useState<Node | null>(null);
  const [size, setSize] = useState({ w: 800, h: 600 });

  useEffect(() => {
    api<GraphData>(`/projects/${projectId}/graph?limit=600`).then(setData).catch(() => setData({ nodes: [], links: [] }));
  }, [projectId]);

  useEffect(() => {
    const measure = () => {
      const el = document.getElementById("graph-wrap");
      if (el) setSize({ w: el.clientWidth, h: Math.max(480, window.innerHeight - 260) });
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, []);

  const graphData = useMemo(() => {
    if (!data) return { nodes: [], links: [] };
    return {
      nodes: data.nodes.map((n) => {
        const label = n.labels.find((l) => LABEL_COLORS[l]) ?? n.labels[0] ?? "";
        return {
          id: n.uid,
          name: n.name,
          label,
          summary: n.summary,
          kind: n.kind,
          val: label === "Project" ? 10 : label === "Component" ? 6 : 2,
        } satisfies Node;
      }),
      links: data.links.map((l) => ({ source: l.source, target: l.target, type: l.type })),
    };
  }, [data]);

  const labelName = (label: string) => (t.has(`labels.${label}`) ? t(`labels.${label}`) : label);

  if (!data) return <div className="text-[var(--muted)]">{t("loading")}</div>;

  return (
    <div className="space-y-2">
      <div className="flex gap-2 flex-wrap items-center">
        {Object.entries(LABEL_COLORS).map(([label, color]) => (
          <span key={label} className="chip">
            <span className="w-2 h-2 rounded-full inline-block mr-1.5" style={{ background: color }} />
            {labelName(label)}
          </span>
        ))}
        <span className="text-xs text-[var(--muted)]">
          {t("counts", { nodes: graphData.nodes.length, links: graphData.links.length })}
        </span>
      </div>
      <div className="flex gap-3">
        <div id="graph-wrap" className="card flex-1 overflow-hidden">
          {graphData.nodes.length === 0 ? (
            <div className="p-10 text-center text-sm text-[var(--muted)]">{t("empty")}</div>
          ) : (
            <ForceGraph2D
              width={size.w}
              height={size.h}
              graphData={graphData}
              backgroundColor="#0b0e14"
              nodeLabel={(n) => `${(n as Node).name}`}
              nodeColor={(n) => LABEL_COLORS[(n as Node).label] ?? "#8b93a7"}
              nodeVal={(n) => (n as Node).val}
              linkColor={() => "#2c3550"}
              linkWidth={0.5}
              onNodeClick={(n) => setSelected(n as Node)}
              cooldownTicks={120}
            />
          )}
        </div>
        {selected && (
          <div className="card p-4 w-80 shrink-0 space-y-2 self-start">
            <div className="flex justify-between items-start gap-2">
              <div className="font-medium text-sm break-all">{selected.name}</div>
              <button className="text-[var(--muted)] hover:text-white" onClick={() => setSelected(null)}>✕</button>
            </div>
            <div className="flex gap-1.5 flex-wrap">
              <span className="chip" style={{ color: LABEL_COLORS[selected.label] }}>
                {labelName(selected.label)}
              </span>
              {selected.kind && <span className="chip">{selected.kind}</span>}
            </div>
            {selected.summary && (
              <div className="text-xs text-[var(--muted)] leading-relaxed whitespace-pre-wrap">
                {selected.summary}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
