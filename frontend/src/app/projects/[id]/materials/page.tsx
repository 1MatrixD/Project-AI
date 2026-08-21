"use client";

import MaterialsTab from "@/components/project/MaterialsTab";
import { useProject } from "@/components/project/ProjectContext";

export default function MaterialsPage() {
  const { project, refreshTick } = useProject();
  return <MaterialsTab projectId={project.id} refreshTick={refreshTick} />;
}
