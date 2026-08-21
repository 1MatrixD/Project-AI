"use client";

import KanbanTab from "@/components/project/KanbanTab";
import { useProject } from "@/components/project/ProjectContext";

export default function TasksPage() {
  const { project, jobs, refreshTick } = useProject();
  return (
    <KanbanTab
      projectId={project.id}
      projectName={project.name}
      refreshTick={refreshTick}
      jobs={jobs}
    />
  );
}
