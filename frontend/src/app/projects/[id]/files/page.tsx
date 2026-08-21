"use client";

import FilesTab from "@/components/project/FilesTab";
import { useProject } from "@/components/project/ProjectContext";

export default function FilesPage() {
  const { project } = useProject();
  return <FilesTab projectId={project.id} />;
}
