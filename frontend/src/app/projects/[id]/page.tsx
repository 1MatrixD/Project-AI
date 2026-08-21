"use client";

import OverviewTab from "@/components/project/OverviewTab";
import { useProject } from "@/components/project/ProjectContext";

export default function OverviewPage() {
  const { project, jobs, reload } = useProject();
  return <OverviewTab project={project} jobs={jobs} onAction={reload} />;
}
