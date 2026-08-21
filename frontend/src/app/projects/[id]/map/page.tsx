"use client";

import GraphTab from "@/components/project/GraphTab";
import { useProject } from "@/components/project/ProjectContext";

export default function MapPage() {
  const { project } = useProject();
  return <GraphTab projectId={project.id} />;
}
