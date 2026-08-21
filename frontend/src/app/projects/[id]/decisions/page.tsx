"use client";

import DecisionsTab from "@/components/project/DecisionsTab";
import { useProject } from "@/components/project/ProjectContext";

export default function DecisionsPage() {
  const { project } = useProject();
  return <DecisionsTab projectId={project.id} />;
}
