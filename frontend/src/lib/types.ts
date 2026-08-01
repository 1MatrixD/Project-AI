export type User = { id: string; email: string; name: string };

export type Project = {
  id: string;
  name: string;
  description: string;
  root_path: string;
  status: "created" | "indexing" | "ready" | "error";
  meta: {
    detect?: { project_kinds?: string[]; stack?: string[] };
    overview?: {
      summary?: string;
      components?: { name: string; kind: string; summary: string; paths: string[] }[];
      business_logic?: { name: string; summary: string }[];
      conventions?: string;
      how_to?: Record<string, string>;
    };
    stats?: { files_total: number; by_kind: Record<string, number>; analyzed: number };
    watch?: boolean;
    extra_roots?: { alias: string; path: string }[];
  };
  created_at: string;
  updated_at: string;
  stats?: { nodes?: Record<string, number>; relations?: number };
};

export type Job = {
  id: string;
  type: string;
  status: "queued" | "running" | "done" | "error" | "cancelled";
  progress: number;
  detail: string;
  stats: Record<string, unknown>;
  error: string | null;
  created_at: string;
};

export type ChangeReport = {
  id: string;
  mode: string;
  added: string[];
  modified: string[];
  deleted: string[];
  stats: { added: number; modified: number; deleted: number; unchanged: number; total: number };
  created_at: string;
};

export type ProjectFile = {
  id: string;
  rel_path: string;
  size: number;
  kind: string;
  analysis_status: string;
  summary: string | null;
};

export type Chat = {
  id: string;
  title: string;
  model: string;
  reasoning: string;
  created_at: string;
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  meta: { cost_usd?: number; duration_ms?: number; error?: string; model?: string };
  created_at: string;
};

export type TaskStatus = "planned" | "in_progress" | "review" | "done" | "cancelled";

export type PlanStep = { text: string; done: boolean };

export type TaskExtra = {
  enriched?: boolean;
  original_description?: string;
  files?: string[];
  related?: { title: string; relation: string; note: string }[];
  duplicate_of?: string | null;
  // планировщик: у родителя — planned/plan_summary/subtasks, у подзадач — parent/depends_on
  planned?: boolean;
  plan_summary?: string;
  subtasks?: string[];
  parent_task?: string;
  parent_title?: string;
  depends_on?: string[];
};

export type Task = {
  id: string;
  title: string;
  description: string;
  status: TaskStatus;
  source: string;
  plan: PlanStep[];
  extra: TaskExtra;
  report: string | null;
  created_at: string;
  updated_at: string;
  done_at: string | null;
};

export type Material = {
  id: string;
  filename: string;
  media_type: string;
  size: number;
  status: "uploaded" | "processing" | "ready" | "error";
  summary: string | null;
  error: string | null;
  created_at: string;
};

export type Decision = {
  id: string;
  topic: string;
  text: string;
  source: string;
  updated_at: string;
};

export type GraphData = {
  nodes: { uid: string; labels: string[]; name: string; summary: string; kind: string }[];
  links: { source: string; target: string; type: string }[];
};

export type PluginInfo = {
  slug: string;
  path: string;
  exists: boolean;
  marketplace_path: string;
  install_commands: string[];
  skills: { name: string; description: string }[];
  mcp_tools: { name: string; description: string }[];
};
