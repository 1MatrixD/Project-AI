"use client";

import PluginTab from "@/components/project/PluginTab";
import { useProject } from "@/components/project/ProjectContext";

export default function PluginPage() {
  const { project } = useProject();
  return <PluginTab projectId={project.id} />;
}
