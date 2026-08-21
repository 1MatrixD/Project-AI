"use client";

import { createContext, useContext } from "react";
import type { Job, Project } from "@/lib/types";

/** Общий контекст страниц проекта: layout грузит проект и джобы (SSE + резервный
 *  поллинг), страницы-вкладки берут их отсюда — раньше это были пропсы табов. */
export type ProjectCtx = {
  project: Project;
  jobs: Job[];
  refreshTick: number;
  reload: () => void;
};

const Ctx = createContext<ProjectCtx | null>(null);

export const ProjectProvider = Ctx.Provider;

export function useProject(): ProjectCtx {
  const v = useContext(Ctx);
  if (!v) throw new Error("useProject используется вне layout проекта");
  return v;
}
